"""
LaTeX resume builder for JobApplicationAgent (Phase 2).

This module uses Jinja2 templating to render a LaTeX resume and then
invokes ``pdflatex`` to compile the final PDF.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .resume_generator import ResumeContent
from .utils import AppConfig, PROJECT_ROOT, ensure_dir, latex_escape, slugify


logger = logging.getLogger(__name__)


class LatexBuilder:
    """
    Render a LaTeX resume via Jinja2 and compile it to PDF using ``pdflatex``.
    """

    def __init__(self, config: AppConfig):
        self.config = config

        template_path = PROJECT_ROOT / self.config.resume.get(
            "template_path", "templates/resume_template.tex"
        )
        self.template_dir = template_path.parent
        self.template_name = template_path.name

        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(enabled_extensions=(), default_for_string=False),
            block_start_string="{%",
            block_end_string="%}",
            variable_start_string="{{",
            variable_end_string="}}",
        )

    def render_and_compile(
        self,
        resume: ResumeContent,
        candidate_profile: Dict[str, Any],
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Render the LaTeX template and compile a PDF for a given job.

        Parameters
        ----------
        resume:
            Tailored resume content for the specific job.
        candidate_profile:
            Dictionary including ``candidate_name`` and ``contact`` keys used
            by the template.
        output_path:
            If set, write the PDF (and .tex) to this path instead of the
            default output_dir. Used for temporary files (e.g. extension flow).

        Returns
        -------
        Path
            Filesystem path to the generated PDF.
        """

        logger.info("Rendering LaTeX for '%s' at '%s'", resume.job_title, resume.company)
        template = self.env.get_template(self.template_name)

        # Escape LLM-generated text for LaTeX (e.g. & _ # % in "Software & Simulation")
        raw_skills = getattr(resume, "skills", []) or []
        skills_escaped: List[Dict[str, Any]] = []
        for group in raw_skills:
            if not isinstance(group, dict):
                continue
            heading = group.get("heading", "")
            items_raw = group.get("items", [])
            if isinstance(items_raw, list):
                items = [latex_escape(str(x)) for x in items_raw]
            else:
                items = [latex_escape(str(items_raw))]
            skills_escaped.append({"heading": latex_escape(str(heading)), "items": items})

        raw_research = getattr(resume, "research_experience", []) or []
        research_escaped: List[Dict[str, Any]] = []
        for r in raw_research:
            research_escaped.append({
                "title": latex_escape(r.title),
                "bullets": [latex_escape(b) for b in r.bullets],
            })

        context: Dict[str, Any] = {
            "job_title": latex_escape(resume.job_title),
            "company": latex_escape(resume.company),
            "summary": latex_escape(resume.summary),
            "phd_degree": latex_escape(getattr(resume, "phd_degree", "")),
            "skills": skills_escaped,
            "research_experience": research_escaped,
            **candidate_profile,
        }

        tex_content = template.render(**context)

        if output_path is not None:
            output_dir = output_path.parent
            base_name = output_path.stem
        else:
            output_root = PROJECT_ROOT / self.config.resume.get("output_dir", "data/resumes")
            ensure_dir(output_root)
            base_name = f"{slugify(resume.company)}_{slugify(resume.job_title)}"
            output_dir = output_root

        ensure_dir(output_dir)
        tex_path = output_dir / f"{base_name}.tex"
        pdf_path = output_dir / f"{base_name}.pdf"

        logger.info("Writing LaTeX source to %s", tex_path)
        tex_path.write_text(tex_content, encoding="utf-8")

        self._run_pdflatex(tex_path)

        if not pdf_path.exists():
            logger.warning("Expected PDF not found at %s", pdf_path)
        else:
            logger.info("Generated resume PDF at %s", pdf_path)

        return pdf_path

    def _run_pdflatex(self, tex_path: Path) -> None:
        """
        Run ``pdflatex`` on the given .tex file.

        A TeX distribution (such as TeX Live or MacTeX) must be installed in
        the environment running this code.
        """

        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            tex_path.name,
        ]

        logger.info("Invoking pdflatex for %s", tex_path)
        result = subprocess.run(
            cmd,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.error("pdflatex failed (exit %s). stderr:\n%s", result.returncode, stderr)
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                result.stdout,
                result.stderr,
            )


