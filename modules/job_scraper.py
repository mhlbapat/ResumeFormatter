from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from jobspy import scrape_jobs
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
import trafilatura

from .llm_engine import LLMRequest, BaseLLMClient, build_llm_client
from .utils import AppConfig, ensure_dir, slugify, write_json


logger = logging.getLogger(__name__)


@dataclass
class JobPosting:
    """
    Normalized job posting structure.
    """

    title: str
    company: str
    location: str
    description: str
    apply_link: str
    source_site: str

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


class JobScraper:
    """
    Smart, modular job scraping with provider routing ("waterfall" strategy).

    - Discovery mode (no URL): bulk search via jobspy across multiple sites.
    - Workday/ATS mode (Workday-style URLs): Playwright to intercept JSON APIs.
    - Universal AI fallback: trafilatura + LLM to parse arbitrary job pages.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def scrape(
        self,
        keywords: List[str],
        results_wanted_override: Optional[int] = None,
        url: Optional[str] = None,
    ) -> List[JobPosting]:
        """
        Orchestrate job scraping using a waterfall routing strategy.

        Parameters
        ----------
        keywords:
            List of search keywords for discovery mode. Ignored when url is provided.
        results_wanted_override:
            If set, overrides config.scraping.results_wanted for discovery runs.
        url:
            If provided, scrape a specific job URL instead of running discovery.
        """

        # URL-based mode: single job.
        if url:
            logger.info("JobScraper: routing to URL mode for %s", url)
            job: Optional[JobPosting] = None

            if self._looks_like_workday(url):
                logger.info("JobScraper: URL looks like Workday/ATS, trying Playwright first")
                try:
                    job = self._scrape_with_playwright(url)
                except Exception:
                    logger.exception("JobScraper: Playwright ATS scrape failed for %s", url)

                if job is None:
                    logger.info(
                        "JobScraper: Playwright failed or returned no job; "
                        "falling back to AI scrape for %s",
                        url,
                    )

            if job is None:
                try:
                    job = self._scrape_with_ai(url)
                except Exception:
                    logger.exception("JobScraper: AI fallback scrape failed for %s", url)
                    job = None

            return [job] if job else []

        # Discovery mode: bulk search via jobspy (Indeed/LinkedIn/Glassdoor etc.).
        logger.info("JobScraper: routing to discovery mode (jobspy)")
        try:
            jobs = self._scrape_discovery_jobspy(keywords, results_wanted_override)
        except Exception:
            logger.exception("JobScraper: discovery via jobspy failed")
            jobs = []

        return jobs

    # ------------------------------------------------------------------
    # Discovery via jobspy
    # ------------------------------------------------------------------

    def _scrape_discovery_jobspy(
        self,
        keywords: List[str],
        results_wanted_override: Optional[int],
    ) -> List[JobPosting]:
        """
        Bulk discovery of job postings via jobspy.
        """

        provider = self.config.scraping.get("provider", "jobspy")
        if provider != "jobspy":
            raise ValueError(f"Unsupported scraping provider: {provider}")

        search_term = self._build_search_term(keywords)
        logger.info("Scraping jobs via jobspy with search_term='%s'", search_term)

        results_wanted = int(
            results_wanted_override
            if results_wanted_override is not None
            else self.config.scraping.get("results_wanted", 100)
        )

        # Default to a mix of sites if none are configured explicitly.
        site_names = self.config.scraping.get(
            "site_names",
            ["indeed", "linkedin", "glassdoor"],
        )

        df = scrape_jobs(
            site_name=site_names,
            search_term=search_term,
            location=self.config.scraping.get("location", "United States"),
            results_wanted=results_wanted,
            hours_old=int(self.config.scraping.get("hours_old", 168)),
            country_indeed=self.config.scraping.get("country_indeed", "USA"),
            full_description=bool(self.config.scraping.get("full_description", True)),
        )

        logger.info("Scraped %d raw jobs from jobspy (%s)", len(df), ",".join(site_names))

        jobs: List[JobPosting] = []
        for _, row in df.iterrows():
            description = (
                str(row.get("description", "")) or str(row.get("full_description", ""))
            )
            job = JobPosting(
                title=str(row.get("title", "")).strip(),
                company=str(row.get("company", "")).strip(),
                location=str(row.get("location", "")).strip(),
                description=description.strip(),
                apply_link=str(row.get("job_url", row.get("url", ""))).strip(),
                source_site=str(row.get("site", "jobspy")).strip(),
            )
            jobs.append(job)

        if jobs:
            output_path = self._get_output_path(search_term)
            logger.info("Writing %d normalized jobs to %s", len(jobs), output_path)
            ensure_dir(output_path.parent)
            write_json(output_path, [job.to_json() for job in jobs])

        return jobs

    def _build_search_term(self, keywords: List[str]) -> str:
        # Simple strategy: join top-N keywords for the search term.
        max_keywords = 5
        selected = [kw for kw in keywords if kw][:max_keywords]
        if not selected:
            return self.config.scraping.get("search_term", "Software Engineer")
        return " ".join(selected)

    def _get_output_path(self, search_term: str) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        slug = slugify(search_term)
        return self.config.data_dir / "jobs" / f"jobs_{slug}_{timestamp}.json"

    # ------------------------------------------------------------------
    # Workday / ATS scraping via Playwright
    # ------------------------------------------------------------------

    def _looks_like_workday(self, url: str) -> bool:
        """
        Heuristic to detect Workday / similar ATS URLs.
        """

        host = urlparse(url).netloc.lower()
        return "myworkdayjobs.com" in host or "myworkday" in host or "wd" in host

    def _scrape_with_playwright(self, url: str) -> Optional[JobPosting]:
        """
        Use Playwright to open a Workday/ATS page and intercept JSON API responses.

        Looks for responses whose URL contains tokens like 'getJob', 'get-job',
        'jobPosting', or 'details', then normalizes one into a JobPosting.
        """

        logger.info("JobScraper: starting Playwright scrape for %s", url)

        browser_cfg = self.config.browser or {}
        browser_type_name = browser_cfg.get("browser_type", "chromium")
        headless = bool(browser_cfg.get("headless", True))
        slow_mo_ms = int(browser_cfg.get("slow_mo_ms", 0) or 0)

        captured_payloads: List[Dict[str, Any]] = []

        def _handle_response(response) -> None:
            try:
                resp_url = response.url
                if any(token in resp_url for token in ("getJob", "get-job", "jobPosting", "details")):
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        data = response.json()
                        captured_payloads.append(data)
                        logger.debug("JobScraper: captured JSON from %s", resp_url)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("JobScraper: error inspecting response: %s", exc)

        with sync_playwright() as p:
            browser_type = getattr(p, browser_type_name, None)
            if browser_type is None:
                raise ValueError(f"Unsupported Playwright browser_type: {browser_type_name}")

            browser = browser_type.launch(headless=headless, slow_mo=slow_mo_ms)
            context = browser.new_context()
            page = context.new_page()
            page.on("response", _handle_response)

            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                logger.warning("JobScraper: Playwright navigation timeout for %s", url)
            finally:
                browser.close()

        if not captured_payloads:
            logger.warning("JobScraper: no JSON job payloads captured via Playwright for %s", url)
            return None

        for payload in captured_payloads:
            job = self._normalize_ats_payload(url, payload)
            if job is not None:
                logger.info("JobScraper: Playwright ATS scrape succeeded for %s", url)
                return job

        logger.warning("JobScraper: unable to normalize any ATS payloads for %s", url)
        return None

    def _normalize_ats_payload(self, url: str, payload: Dict[str, Any]) -> Optional[JobPosting]:
        """
        Best-effort normalization of an ATS JSON payload into a JobPosting.

        This handles common Workday-like structures but is designed to degrade
        gracefully if fields are missing.
        """

        # Workday-style wrapping:
        job_data = (
            payload.get("jobPostingInfo")
            or payload.get("jobPosting")
            or payload.get("jobPostingDetails")
            or payload
        )
        if not isinstance(job_data, dict):
            return None

        title = (
            str(
                job_data.get("title")
                or job_data.get("jobTitle")
                or job_data.get("displayTitle")
                or "",
            ).strip()
        )

        company = ""
        hiring_org = job_data.get("hiringOrganization") or job_data.get("company")
        if isinstance(hiring_org, dict):
            company = str(hiring_org.get("name", "")).strip()
        elif isinstance(hiring_org, str):
            company = hiring_org.strip()

        # Location heuristics.
        location = ""
        loc_field = job_data.get("jobLocation") or job_data.get("location")
        if isinstance(loc_field, dict):
            addr = loc_field.get("address") or loc_field
            if isinstance(addr, dict):
                locality = addr.get("addressLocality") or addr.get("city") or ""
                region = addr.get("addressRegion") or addr.get("state") or ""
                country = addr.get("addressCountry") or ""
                parts = [str(p).strip() for p in (locality, region, country) if p]
                location = ", ".join(parts)
        elif isinstance(loc_field, str):
            location = loc_field.strip()

        # Description heuristics.
        description = ""
        desc_field = (
            job_data.get("jobDescription")
            or job_data.get("description")
            or job_data.get("summary")
        )
        if isinstance(desc_field, str):
            description = desc_field.strip()

        if not (title and description):
            # Not enough information to build a useful JobPosting.
            return None

        return JobPosting(
            title=title,
            company=company or self._infer_source_site(url),
            location=location,
            description=description,
            apply_link=url,
            source_site=self._infer_source_site(url),
        )

    # ------------------------------------------------------------------
    # Universal AI fallback: trafilatura + LLM
    # ------------------------------------------------------------------

    def _scrape_with_ai(self, url: str) -> Optional[JobPosting]:
        """
        Universal AI fallback: use trafilatura to extract main text, then ask the
        configured LLM to return a structured job posting in JSON.
        """

        logger.info("JobScraper: starting AI fallback scrape for %s", url)

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning("JobScraper: trafilatura.fetch_url returned no content for %s", url)
            return None

        text = trafilatura.extract(downloaded)
        if not text or not text.strip():
            logger.warning("JobScraper: trafilatura.extract returned empty text for %s", url)
            return None

        client: BaseLLMClient = build_llm_client(self.config)

        system_prompt = (
            "You are an assistant that extracts structured job posting information "
            "from arbitrary web page text."
        )
        user_prompt = (
            "Extract the job title, company, and full job description from the "
            "following text and return only a JSON object.\n\n"
            "TEXT:\n"
            f"{text[:30000]}"
        )

        max_out = self.config.llm.get("max_output_tokens") or self.config.llm.get("max_tokens")
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=int(max_out if max_out is not None else 15000),
        )

        raw = client.complete(request)
        data = self._parse_llm_job_json(raw)

        title = str(data.get("title", "")).strip()
        company = str(data.get("company", "")).strip()
        description = str(data.get("description", "")).strip()
        location = str(data.get("location", "")).strip()

        if not (title and description):
            logger.warning("JobScraper: LLM JSON missing required fields for %s", url)
            return None

        job = JobPosting(
            title=title,
            company=company or self._infer_source_site(url),
            location=location,
            description=description,
            apply_link=url,
            source_site=self._infer_source_site(url),
        )

        logger.info("JobScraper: AI fallback scrape succeeded for %s", url)
        return job

    def _parse_llm_job_json(self, raw: str) -> Dict[str, Any]:
        """
        Robust JSON extraction for LLM responses that may contain extra text
        or wrap the JSON in code fences.
        """

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Attempt to locate the first JSON object in the string.
        import re

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("LLM did not return a JSON object.")
        return json.loads(match.group(0))

    def _infer_source_site(self, url: str) -> str:
        """
        Infer a short source label from a URL host (e.g. 'myworkdayjobs.com' -> 'workday').
        """

        host = urlparse(url).netloc.lower()
        if "myworkday" in host:
            return "workday"
        if "linkedin" in host:
            return "linkedin"
        if "indeed" in host:
            return "indeed"
        if "glassdoor" in host:
            return "glassdoor"
        return host or "unknown"
