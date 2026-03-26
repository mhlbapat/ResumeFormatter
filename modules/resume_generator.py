"""
Clean resume generation module.

This version:
  - Reads the static system prompt from `prompts/resume_static_prefix.txt` (or
    `resume.static_prompt_path` in config/settings.yaml).
  - Replaces the `<<FULL_PROFILE_TEXT>>` token with the runtime `profile.md`
    (resume.projects_path).
  - Never embeds the static prompt text in code.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .llm_engine import BaseLLMClient, LLMRequest
from .utils import AppConfig, PROJECT_ROOT

RankedJob = Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchExperienceItem:
    """One research project in the Research Experience section."""

    title: str
    bullets: List[str]


@dataclass
class ResumeContent:
    """
    Tailored resume content for a specific job.
    """

    job_title: str
    company: str
    summary: str
    phd_degree: str
    skills: List[Dict[str, Any]]
    research_experience: List[ResearchExperienceItem]

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


FULL_PROFILE_TOKEN = "<<FULL_PROFILE_TEXT>>"


def build_resume_static_prefix(
    full_profile_text: str, prompt_path: Optional[Path] = None
) -> str:
    """
    Build the static (cache-friendly) part of the resume generation prompt.

    The template file must include the token `<<FULL_PROFILE_TEXT>>`, which is
    replaced by the runtime candidate profile markdown.
    """

    effective_prompt_path = prompt_path or (
        PROJECT_ROOT / "prompts" / "resume_static_prefix.txt"
    )
    if not effective_prompt_path.is_absolute():
        effective_prompt_path = PROJECT_ROOT / effective_prompt_path

    if not effective_prompt_path.exists():
        raise FileNotFoundError(
            f"Static resume prompt template not found at {effective_prompt_path}. "
            "Create it at prompts/resume_static_prefix.txt or set resume.static_prompt_path "
            "in config/settings.yaml."
        )

    template = effective_prompt_path.read_text(encoding="utf-8")
    profile_text = full_profile_text.strip() or "(No candidate profile provided.)"

    if FULL_PROFILE_TOKEN not in template:
        raise ValueError(
            f"Static prompt template must include token {FULL_PROFILE_TOKEN}."
        )

    return template.replace(FULL_PROFILE_TOKEN, profile_text)


def build_resume_dynamic_suffix(job: RankedJob) -> str:
    """Build the dynamic (job-specific) part of the resume generation prompt."""

    return f"""
TARGET JOB DESCRIPTION:
-----------------------
{job.description}
"""


def _extract_first_json_object(raw: str) -> Optional[str]:
    """Extract the first balanced JSON object from a string."""

    if not raw:
        return None

    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s*```$", "", s).strip()

    start = s.find("{")
    if start < 0:
        return None

    in_str = False
    esc = False
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "\"":
                in_str = False
            continue

        if ch == "\"":
            in_str = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]

    return None


class ResumeGenerator:
    """Generate tailored resume content for a job via an LLM.

    This implementation reads only `profile.md` (projects_path).
    """

    def __init__(self, config: AppConfig, llm_client: BaseLLMClient):
        self.config = config
        self.llm = llm_client

    def _load_projects_text(self) -> str:
        """Load profile.md (or configured projects path). Returns empty string if missing."""
        resume_cfg = getattr(self.config, "resume", {})
        projects_path_raw = resume_cfg.get("projects_path")
        if not projects_path_raw:
            return ""

        projects_path = Path(projects_path_raw)
        if not projects_path.is_absolute():
            projects_path = PROJECT_ROOT / projects_path

        projects_path = projects_path.resolve()
        if not projects_path.exists():
            logger.warning(
                "Projects Markdown file not found at %s; proceeding without it.",
                projects_path,
            )
            return ""

        logger.info("Loading profile/projects from %s", projects_path)
        try:
            return projects_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read at %s: %s", projects_path, exc)
            return ""

    def generate_for_job(self, job: RankedJob) -> ResumeContent:
        """Generate tailored resume content using the LLM."""

        logger.info(
            "Generating tailored resume content for '%s' at '%s'",
            job.title,
            job.company,
        )

        profile_md = self._load_projects_text()
        candidate_text = profile_md or ""
        if not candidate_text.strip():
            logger.warning(
                "projects_path is empty or unreadable; LLM will receive no candidate text."
            )

        static_prompt_path_raw = self.config.resume.get("static_prompt_path")
        static_prompt_path = (
            Path(static_prompt_path_raw) if static_prompt_path_raw else None
        )
        system_prompt = build_resume_static_prefix(
            candidate_text, prompt_path=static_prompt_path
        )
        user_prompt = build_resume_dynamic_suffix(job)

        max_out = self.config.llm.get("max_output_tokens") or self.config.llm.get(
            "max_tokens"
        )
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=int(max_out if max_out is not None else 15000),
        )
        raw = self.llm.complete(request)

        data = self._parse_response_json(raw)
        if not data:
            logger.warning("LLM returned no parseable JSON. raw_len=%d", len(raw or ""))

        phd_degree = str(
            self.config.resume.get("phd_degree") or "Chemical Engineering"
        ).strip()

        summary = (
            str(data.get("summary", "")).strip()
            or "Ph.D. researcher in computational modeling and scientific computing."
        )

        raw_skills = data.get("skills") or data.get("Skills") or []
        skills: List[Dict[str, Any]] = []
        if isinstance(raw_skills, list):
            for group in raw_skills:
                if not isinstance(group, dict):
                    continue
                heading = str(group.get("heading", "")).strip()
                items_raw = group.get("items", [])
                if not heading:
                    continue
                items = (
                    [str(x).strip() for x in items_raw]
                    if isinstance(items_raw, list)
                    else []
                )
                items = [x for x in items if x]
                if items:
                    skills.append({"heading": heading, "items": items})

        raw_research = data.get("research_experience") or data.get(
            "researchExperience"
        ) or []
        research_experience: List[ResearchExperienceItem] = []
        if isinstance(raw_research, list):
            for item in raw_research:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                bullets_raw = item.get("bullets", [])
                bullets = (
                    [str(b).strip() for b in bullets_raw]
                    if isinstance(bullets_raw, list)
                    else []
                )
                bullets = [b for b in bullets if b][:5]
                if title and bullets:
                    research_experience.append(
                        ResearchExperienceItem(title=title, bullets=bullets)
                    )

        research_experience = research_experience[:5]

        if not skills or not research_experience:
            logger.warning(
                "LLM response missing sections: skills=%d research_experience=%d raw_len=%d keys=%s",
                len(skills),
                len(research_experience),
                len(raw or ""),
                list(data.keys()) if data else [],
            )

        llm_job_title = (data.get("job_title") or data.get("jobTitle") or "").strip()
        llm_company = (data.get("company") or "").strip()
        return ResumeContent(
            job_title=llm_job_title or job.title,
            company=llm_company or job.company,
            summary=summary,
            phd_degree=phd_degree,
            skills=skills,
            research_experience=research_experience,
        )

    def _parse_response_json(self, raw: str) -> Dict[str, Any]:
        """Robust JSON extraction: code fences, commentary, trailing commas."""

        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        extracted = _extract_first_json_object(raw)
        if not extracted:
            logger.warning("LLM did not return a JSON object. raw_prefix=%r", raw[:200])
            return {}

        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

        cleaned = (
            extracted.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
        )
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse LLM JSON after cleanup: %s", exc)
            return {}

    def _get_output_path(self, job: RankedJob) -> Path:
        # Kept for backwards compatibility with earlier versions; unused in the current API flow.
        from datetime import datetime

        from .utils import slugify

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        company_slug = slugify(job.company)
        role_slug = slugify(job.title)
        return (
            self.config.data_dir
            / "resumes"
            / f"content_{company_slug}_{role_slug}_{timestamp}.json"
        )

