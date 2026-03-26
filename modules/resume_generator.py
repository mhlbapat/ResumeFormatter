"""
Resume generation module for JobApplicationAgent (Phase 2).

This module:
    - Passes the full profile.md (candidate context) to the LLM for resume tailoring.
    - Uses a cache-friendly prompt structure: static prefix (instructions + full profile)
      and dynamic suffix (job-specific details) for GPT-5-mini / Responses API prompt caching.
    - Persists the structured content to JSON for auditability and LaTeX rendering.
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


def build_resume_static_prefix(full_profile_text: str) -> str:
    """
    Build the static (cache-friendly) part of the resume generation prompt.

    This content is identical across jobs when the candidate profile is unchanged.
    Intended for use as the system message so that GPT-5-mini / Responses API
    can cache the prefix and reuse it across many job applications.

    Contains: system behavior, resume rules, academic-to-industry translation,
    formatting rules, and the FULL candidate profile text.
    """
    return (
        """You are an expert resume tailoring assistant specializing in translating academic research experience into industry-relevant resume language.

Your goal is to maximize relevance to the target job while staying strictly factual.
Act like a hiring manager that only has 10-20 seconds to scan the resume and provide the SKILLS section and RESEARCH EXPERIENCE section (described below) that will be used to evaluate the candidate.

CRITICAL RULES:
- Use ONLY information from the candidate's provided text.
- Do NOT invent tools, outcomes, employers, or experience.
- You MAY rephrase technical details into industry-relevant language when the meaning remains true.

ACADEMIC to INDUSTRY TRANSLATION RULES:
- Translate research tasks into engineering or product development contributions.
- Emphasize outcomes, insights, and design implications rather than academic measurements.
- Replace overly academic wording with practical engineering language.
- Prefer verbs like: developed, designed, evaluated, analyzed, optimized, modeled, quantified.
- Frame simulation work as enabling material design decisions, process optimization, or performance understanding.

RELEVANCE RULES:
- Prioritize keywords and concepts appearing in the job description.
- Align bullets with the job's domain (e.g., polymer materials, product development, manufacturing, modeling).
- Avoid emphasizing purely academic analysis unless it clearly supports engineering outcomes.

SKILLS SECTION (draw from the FULL profile):
- Build the skills section from the candidate's ENTIRE profile, not only from projects you select for Research Experience.
- Include broadly relevant transferable skills when supported by the profile, such as: AI/ML, LLMs, automation, Python tooling, data workflows, scientific computing, modeling, optimization.
- Only include skills explicitly stated in the profile or directly supported by repeated project evidence.
- The Skills section may reflect capabilities from any project in the full profile as long as they are relevant to the job.

FORMAT RULES:
- Output a single VALID JSON object with exactly these keys:
  job_title, company, location, summary, skills, research_experience.
- No commentary.
- No code fences.
- Do not truncate.

BULLET STYLE GUIDE:
- Start each bullet with a strong action verb.
- Describe an engineering contribution or capability.
- Include a method or tool only if relevant.
- Emphasize outcomes or insights that influence material design, product development, or process understanding.
- Avoid overly academic phrasing; translate into engineering impact.
- Each bullet must be 10-15 words.

TASK (applied using the candidate profile above and the job description in the user message):
1. Write a professional summary tailored to the target job, under 100 words, using the candidate's full profile.

2. Select 3 skill groups with short headings with 4 to 6 items in each group from the candidate's full profile that match the job. Include transferable skills (e.g. AI/LLM, Python, data, automation) when present in the profile. Avoid duplicate skills across groups.

3. Select 5 projects from the candidate profile most relevant to the target job for the Research Experience section. For each: include the project title (or rephrase it to be more job-relevant), and choose 4 bullets from the bullet bank and/or rephrase them to be more job-relevant. Prioritize quantifiable impact; align with the job description; stay factual.

4. From the job description, extract the job posting's job title and company name and location. Include them in your JSON as "job_title", "company", and "location".

RESPONSE FORMAT (JSON only):
{
  "job_title": "<job posting title from the description>",
  "company": "<company/employer name from the description>",
  "location": "<location from the description>",
  "summary": "<summary text>",
  "skills": [{"heading": "<group name>", "items": ["Item 1", "Item 2", ...]}],
  "research_experience": [{"title": "<project title>", "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>", "<bullet 4>"]}],
}

---
BEGIN CANDIDATE PROFILE (full text; use for both skills and research experience selection):
---
"""
        + (full_profile_text.strip() or "(No candidate profile provided.)")
        + """
---
END CANDIDATE PROFILE
"""
    )


def build_resume_dynamic_suffix(job: RankedJob) -> str:
    """
    Build the dynamic (job-specific) part of the resume generation prompt.

    This content changes per job. Intended for use as the user message so that
    only this portion varies across requests, maximizing cache hit rate for the
    static prefix (system message).
    """
    return f"""
TARGET JOB DESCRIPTION:
-----------------------
{job.description}
"""


def build_resume_generation_prompts(candidate_text: str, job: RankedJob) -> tuple[str, str]:
    """
    Build system and user prompts for resume generation (cache-friendly structure).

    - System prompt (static prefix): instructions + full candidate profile.
      Stable across jobs when profile is unchanged; suitable for prompt caching.
    - User prompt (dynamic suffix): job title, company, location, description, task.
    """
    system_prompt = build_resume_static_prefix(candidate_text)
    user_prompt = build_resume_dynamic_suffix(job)
    return system_prompt, user_prompt


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
            logger.warning("Projects Markdown file not found at %s; proceeding without it.", projects_path)
            return ""

        logger.info("Loading profile/projects from %s", projects_path)
        try:
            return projects_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read at %s: %s", projects_path, exc)
            return ""

    def generate_for_job(self, job: RankedJob) -> ResumeContent:
        """
        Create a tailored summary, skills, and research experience (4-5 projects, 4-5 bullets each).
        Always passes the full profile.md to the LLM so the model can use the entire candidate
        background for the skills section and still choose 4-5 projects for Research Experience.
        Uses a cache-friendly prompt structure: static prefix (instructions + full profile) as
        system message, dynamic suffix (job details) as user message.
        """
        logger.info("Generating tailored resume content for '%s' at '%s'", job.title, job.company)

        profile_md = self._load_projects_text()
        candidate_text = profile_md or ""
        if not candidate_text.strip():
            logger.warning("projects_path is empty or unreadable; LLM will receive no candidate text.")

        # Cache-friendly structure: system_prompt = static prefix (instructions + full profile),
        # user_prompt = dynamic suffix (job-specific). Same prefix across jobs → better prompt cache hit rate.
        system_prompt = build_resume_static_prefix(candidate_text)
        user_prompt = build_resume_dynamic_suffix(job)

        max_out = self.config.llm.get("max_output_tokens") or self.config.llm.get("max_tokens")
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=int(max_out if max_out is not None else 15000),
        )
        raw = self.llm.complete(request)

        data = self._parse_response_json(raw)

        if not data:
            logger.warning("LLM returned no parseable JSON. raw_len=%d", len(raw or ""))

        phd_degree = str(self.config.resume.get("phd_degree") or "Chemical Engineering").strip()

        summary = str(data.get("summary", "")).strip() or "Ph.D. researcher in computational modeling and scientific computing."

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
                items = [str(x).strip() for x in items_raw] if isinstance(items_raw, list) else []
                items = [x for x in items if x]
                if items:
                    skills.append({"heading": heading, "items": items})

        raw_research = data.get("research_experience") or data.get("researchExperience") or []
        research_experience: List[ResearchExperienceItem] = []
        if isinstance(raw_research, list):
            for item in raw_research:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                bullets_raw = item.get("bullets", [])
                bullets = [str(b).strip() for b in bullets_raw] if isinstance(bullets_raw, list) else []
                bullets = [b for b in bullets if b][:5]
                if title and bullets:
                    research_experience.append(ResearchExperienceItem(title=title, bullets=bullets))

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
        content = ResumeContent(
            job_title=llm_job_title or job.title,
            company=llm_company or job.company,
            summary=summary,
            phd_degree=phd_degree,
            skills=skills,
            research_experience=research_experience,
        )

        return content

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

        cleaned = extracted.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'")
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse LLM JSON after cleanup: %s", exc)
            return {}

    def _get_output_path(self, job: RankedJob) -> Path:
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


