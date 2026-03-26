"""
Parse a single job posting from a URL (Indeed, company career page, etc.).

Fetches the page, extracts main text with trafilatura, then uses the LLM
to extract structured job fields (title, company, location, description).

Author: Cursor
Prompted by: Mehul Bapat
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
import trafilatura

from .llm_engine import BaseLLMClient, LLMRequest
from .utils import AppConfig

logger = logging.getLogger(__name__)

# Allow only http/https
ALLOWED_SCHEMES = ("http", "https")
DEFAULT_TIMEOUT_SEC = 20
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


@dataclass
class ParsedJob:
    """Structured job info extracted from a URL."""

    title: str
    company: str
    location: str
    description: str


def _validate_url(url: str) -> None:
    """Raise ValueError if URL scheme is not allowed."""
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError(f"URL must use http or https, got: {parsed.scheme or 'empty'}")


def fetch_and_extract_text(
    url: str,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """
    Fetch URL and return main body text extracted from HTML.

    Raises
    ------
    ValueError
        If URL scheme is not http/https.
    httpx.HTTPError
        On request failure or non-2xx response.
    """
    _validate_url(url)
    logger.info("Fetching job page: %s", url)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        if len(resp.content) > max_bytes:
            raise ValueError(f"Response too large ({len(resp.content)} bytes, max {max_bytes})")
        html = resp.text
    text = trafilatura.extract(html)
    if not text or not text.strip():
        # Fallback: use raw text from HTML to avoid losing content on some sites
        from html import unescape
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) < 100:
        raise ValueError("Could not extract enough text from the page for a job description")
    return text[:50000]  # Cap for LLM context


def _extract_jobposting_json_blob(text: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort extraction of a schema.org JobPosting JSON object from page text.

    Many career pages embed a JSON blob like:
        { ..., "@type": "JobPosting", ... }

    This function locates the first occurrence of "@type":"JobPosting" (or variants),
    then walks braces from the nearest preceding '{' to reconstruct the JSON object.
    """

    match = re.search(r'"@type"\s*:\s*"JobPosting"', text)
    if not match:
        return _extract_jobposting_from_text_heuristic(text)

    idx = match.start()
    start = text.rfind("{", 0, idx)
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Fall through to heuristic parsing below.
                    break

    # If we couldn't cleanly parse JSON (often because the description text
    # has been de-escaped and is no longer valid JSON), fall back to
    # heuristic extraction using regexes.
    return _extract_jobposting_from_text_heuristic(text)


def _extract_jobposting_from_text_heuristic(text: str) -> Optional[Dict[str, Any]]:
    """
    Heuristic extraction of key JobPosting fields from a JSON-like blob that is
    no longer valid JSON (e.g. description has been unescaped).

    This covers cases like the Workday example where the page text contains:
        { "jobLocation" : { ... }, "identifier" : { "value" : "R2600569" }, ... }
    followed by additional script content.
    """

    title = ""
    job_id = ""
    locations: List[str] = []
    description = ""

    # title (accept single or double quotes)
    m = re.search(r"""['"]title['"]\s*:\s*['"]([^'"]+)['"]""", text)
    if m:
        title = m.group(1).strip()

    # identifier value
    m = re.search(
        r"""['"]identifier['"]\s*:\s*\{[^}]*['"]value['"]\s*:\s*['"]([^'"]+)['"]""",
        text,
        re.DOTALL,
    )
    if m:
        job_id = m.group(1).strip()

    # locations (addressLocality)
    for loc_match in re.findall(r"""['"]addressLocality['"]\s*:\s*['"]([^'"]+)['"]""", text):
        loc = loc_match.strip()
        if loc:
            locations.append(loc)

    # description: text after the description key up to the @context key (both quoted or unquoted)
    desc_key_idx = text.find("description")
    if desc_key_idx != -1:
        ctx_idx = text.find("@context", desc_key_idx)
        segment = text[desc_key_idx:ctx_idx if ctx_idx != -1 else len(text)]
        colon_idx = segment.find(":")
        if colon_idx != -1:
            desc_raw = segment[colon_idx + 1 :].strip()
            # Strip leading quotes/braces/commas
            desc_raw = desc_raw.lstrip(' "\'{')
            # Strip trailing quotes/braces/commas
            desc_raw = desc_raw.rstrip(' "\'},')
            description = desc_raw.strip()

    if not any([title, job_id, locations, description]):
        return None

    job_location_struct = []
    for loc in locations:
        job_location_struct.append(
            {
                "address": {
                    "addressLocality": loc,
                }
            }
        )

    identifier_struct: Union[Dict[str, Any], str, None]
    if job_id:
        identifier_struct = {"value": job_id}
    else:
        identifier_struct = None

    data: Dict[str, Any] = {
        "title": title,
        "jobLocation": job_location_struct,
        "description": description,
    }
    if identifier_struct is not None:
        data["identifier"] = identifier_struct

    return data


def _format_structured_jobposting(data: Dict[str, Any]) -> str:
    """
    Turn a JobPosting JSON object into a user-friendly multi-line description.
    """

    parts: list[str] = []

    title = str(data.get("title") or "").strip()
    if title:
        parts.append(f"Title: {title}")

    identifier: Union[Dict[str, Any], str, None] = data.get("identifier")
    job_id: Optional[str] = None
    if isinstance(identifier, dict):
        job_id = str(identifier.get("value") or identifier.get("name") or "").strip()
    elif isinstance(identifier, str):
        job_id = identifier.strip()
    if job_id:
        parts.append(f"ID: {job_id}")

    # Locations
    job_location = data.get("jobLocation")
    locations: list[str] = []
    if isinstance(job_location, list):
        items = job_location
    elif isinstance(job_location, dict):
        items = [job_location]
    else:
        items = []

    for loc in items:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            locality = str(addr.get("addressLocality") or "").strip()
            if locality:
                locations.append(locality)

    if locations:
        parts.append("Locations:")
        for loc in locations:
            parts.append(f"- {loc}")

    # Description
    desc_raw = str(data.get("description") or "").strip()
    if desc_raw:
        # Remove any HTML tags and normalise whitespace.
        desc = re.sub(r"<[^>]+>", " ", desc_raw)
        desc = re.sub(r"\s+", " ", desc).strip()

        # Insert line breaks before common section headings to improve readability.
        headings = [
            "Key Responsibilities",
            "Responsibilities",
            "Basic Qualifications",
            "Minimum Qualifications",
            "Preferred Skills",
            "Preferred Qualifications",
            "Working at",
            "About ",
            "Candidate AI Usage Policy",
            "Pay Range",
        ]
        for heading in headings:
            desc = desc.replace(heading, f"\n\n{heading}\n")

        parts.append("Description:")
        parts.append(desc)

    return "\n\n".join(parts) if parts else ""


def format_job_description_for_display(description: str) -> str:
    """
    Format a job description for readable display (web UI). Hard-coded logic only:
    section headers on their own lines, bullets split, long paragraphs broken
    into one sentence per line. Used for both LLM-parsed and fallback scraped text.
    """
    if not (description or "").strip():
        return ""

    text = description.strip()

    # Section headers: ensure they appear on their own line with space above/below.
    section_headers = [
        r"(?i)\b(Responsibilities?)\s*[:\.]?",
        r"(?i)\b(Requirements?)\s*[:\.]?",
        r"(?i)\b(Qualifications?)\s*[:\.]?",
        r"(?i)\b(About\s+(?:the\s+)?(?:role|us|the\s+company)?)\s*[:\.]?",
        r"(?i)\b(Summary|Overview|Description|What\s+you['\']ll\s+do)\s*[:\.]?",
        r"(?i)\b(Preferred|Nice\s+to\s+have)\s*[:\.]?",
        r"(?i)\b(Benefits?|Compensation)\s*[:\.]?",
        r"(?i)\b(Education|Experience)\s*[:\.]?",
        r"(?i)\b(Key\s+(?:Responsibilities?|Qualifications?|Requirements?))\s*[:\.]?",
        r"(?i)\b(Minimum\s+Qualifications?)\s*[:\.]?",
        r"(?i)\b(Basic\s+Qualifications?)\s*[:\.]?",
    ]
    for pattern in section_headers:
        text = re.sub(pattern, r"\n\n\1\n", text)

    # Bullet-like patterns: put each bullet on its own line when they're run together.
    text = re.sub(r"\s+[•\-*]\s+", "\n• ", text)

    # Normalize: at most two consecutive newlines, trim each line.
    lines = [ln.strip() for ln in text.splitlines()]
    normalized = []
    prev_blank = False
    for ln in lines:
        is_blank = not ln
        if is_blank and prev_blank:
            continue
        normalized.append(ln)
        prev_blank = is_blank
    text = "\n".join(normalized).strip()

    # Break long lines (hard-coded, no LLM): one sentence per line for readability.
    sentence_end = re.compile(r"(?<!\d)\.\s+(?=[A-Z])")
    max_line = 120
    out_lines = []
    for line in text.splitlines():
        if len(line) <= max_line:
            out_lines.append(line)
            continue
        parts = sentence_end.split(line)
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if i < len(parts) - 1 and not part.endswith("."):
                part = part + "."
            out_lines.append(part)
    text = "\n".join(out_lines).strip()

    return text


def format_job_text(page_text: str) -> str:
    """
    Produce a user-friendly job description string from raw page text.

    1. Try to extract a structured JobPosting JSON blob and format it nicely.
    2. If that fails, fall back to a cleaned version of the raw text.
    """

    try:
        data = _extract_jobposting_json_blob(page_text)
    except Exception:
        data = None

    if data:
        pretty = _format_structured_jobposting(data)
        if pretty:
            return pretty

    # Fallback (no structured JSON, no LLM): clean raw page text and apply
    # the same hard-coded display formatting so the description is readable.
    cleaned = page_text
    script_idx = cleaned.find("window.workday")
    if script_idx != -1:
        cleaned = cleaned[:script_idx]
    # Collapse runs of whitespace to a single space so section/bullet regexes can still match.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return format_job_description_for_display(cleaned)


def extract_job_with_llm(
    page_text: str,
    llm_client: BaseLLMClient,
    url: str = "",
) -> ParsedJob:
    """
    Use the LLM to extract title, company, location, and description from page text.

    Parameters
    ----------
    page_text : str
        Main text extracted from the job page.
    llm_client : BaseLLMClient
        Configured LLM client.
    url : str
        Original URL (optional, for context in prompt).

    Returns
    -------
    ParsedJob
        Structured job fields.
    """
    system_prompt, user_prompt = build_job_parse_prompts(page_text, url=url)
    request = LLMRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=4000,
    )
    raw = llm_client.complete(request)
    data = _parse_json(raw)
    return ParsedJob(
        title=str(data.get("title", "")).strip() or "Job",
        company=str(data.get("company", "")).strip() or "Company",
        location=str(data.get("location", "")).strip(),
        description=str(data.get("description", "")).strip(),
    )


def build_job_parse_prompts(page_text: str, url: str = "") -> tuple[str, str]:
    """
    Build the system and user prompts used to extract a job posting from page text.

    Exposed as a helper so that other modules (e.g. the web app) can show the exact
    prompts used when running in a debugging mode.
    """

    system_prompt = (
        "You are an assistant that extracts job posting information from web page text. "
        "Return only valid JSON with the keys: title, company, location, description. "
        "Use empty string for any field you cannot determine. "
        "description should be the full job description text (requirements, responsibilities, etc.)."
    )
    user_prompt = f"""
Extract the job posting fields from the following text (from a job listing page{f' at {url}' if url else ''}).

TEXT:
-----
{page_text[:30000]}

Return a single JSON object with exactly these keys: "title", "company", "location", "description".
"""
    return system_prompt, user_prompt


def _parse_json(raw: str) -> Dict[str, Any]:
    """Extract a JSON object from LLM response, handling code fences or extra text."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start == -1:
        raise ValueError("LLM did not return valid JSON for job extraction")
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    break
    raise ValueError("LLM did not return valid JSON for job extraction")


def parse_job_from_url(
    url: str,
    config: AppConfig,
    llm_client: BaseLLMClient,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ParsedJob:
    """
    Fetch a job URL, extract text, and use the LLM to return structured job info.

    Parameters
    ----------
    url : str
        Job listing URL (Indeed, company career page, etc.).
    config : AppConfig
        Application config (used for future options; timeouts are passed explicitly).
    llm_client : BaseLLMClient
        LLM client for extraction.
    timeout : float
        HTTP request timeout in seconds.
    max_bytes : int
        Maximum response body size in bytes.

    Returns
    -------
    ParsedJob
        Extracted title, company, location, description.
    """
    text = fetch_and_extract_text(url, timeout=timeout, max_bytes=max_bytes)
    return extract_job_with_llm(text, llm_client, url=url)
