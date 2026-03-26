"""
Entry point for the JobApplicationAgent pipeline.

Current phases:
    - Phase 1: CV parsing + keyword extraction only (no job search)
    - Phase 2: Resume generation for already-known jobs

Subsequent phases extend this with browser automation.

Author: Cursor
Prompted by: Mehul Bapat
"""

import argparse
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from modules.cv_parser import CVParser
from modules.job_ranker import RankedJob, JobRanker
from modules.job_scraper import JobPosting, JobScraper
from modules.keyword_extractor import KeywordExtractor
from modules.latex_builder import LatexBuilder
from modules.llm_engine import build_llm_client
from modules.resume_generator import (
    ResumeGenerator,
    load_parsed_cv_text,
    load_ranked_jobs_latest,
)
from modules.utils import AppConfig, load_config, load_environment, setup_logging


def _get_cv_text(config: AppConfig) -> str:
    """Load parsed CV text; parse CV from config if parsed file does not exist."""
    try:
        return load_parsed_cv_text(config)
    except FileNotFoundError:
        parser = CVParser(config)
        parser.parse()
        return load_parsed_cv_text(config)


logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="JobApplicationAgent - semi-automated job application pipeline."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to YAML configuration file (defaults to config/settings.yaml).",
    )
    parser.add_argument(
        "--phase",
        type=str,
        choices=["1", "2", "3", "all"],
        default="1",
        help="Which pipeline phase to run.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Optional cap on number of jobs scraped (overrides config.results_wanted).",
    )
    parser.add_argument(
        "--jobs-for-resume",
        type=int,
        default=10,
        help="Number of top-ranked jobs to generate tailored resumes for in Phase 2.",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run full pipeline: Phase 1 (scrape & rank), Phase 2 (resumes for top N), then build summary PDF with links.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=200,
        help="With --run-all: number of top jobs to rank and generate resumes for; also size of summary table (default 200).",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        metavar="JOB_URL",
        help="Generate a single tailored resume from a job listing URL (no web server).",
    )
    return parser


def run_phase_1(
    config: AppConfig,
    max_jobs: Optional[int] = None,
    results_wanted_override: Optional[int] = None,
    top_k_override: Optional[int] = None,
) -> List[RankedJob]:
    """
    Phase 1: parse the CV and extract keywords.

    NOTE: Automatic job searching and ranking have been removed. The primary
    usage pattern is now to search for jobs manually, paste individual job
    URLs into the web app (or use --url), and generate tailored resumes from
    those links.

    Returns
    -------
    List[RankedJob]
        Ranked jobs (same as written to data/ranked_jobs/).
    """

    logger.info("=== Phase 1: CV parsing + keyword extraction (no job search) ===")

    # 1. CV parsing
    cv_parser = CVParser(config)
    parsed_cv = cv_parser.parse()

    # 2. Keyword extraction
    keyword_extractor = KeywordExtractor(config)
    cv_keywords = keyword_extractor.extract_from_parsed_cv()

    logger.info(
        "Phase 1 completed; parsed CV '%s' and extracted %d keywords (no job search performed).",
        config.cv_path,
        len(cv_keywords.skills) + len(cv_keywords.technical_keywords),
    )

    # Job discovery and ranking are now driven by per-URL workflows (web app / --url),
    # so Phase 1 no longer returns ranked jobs.
    return []


def run_phase_2(
    config: AppConfig,
    jobs_for_resume: int,
    ranked_jobs: Optional[List[RankedJob]] = None,
    return_pairs: bool = False,
) -> Optional[List[Tuple[RankedJob, Path]]]:
    """
    Phase 2: Resume generation.

    If ranked_jobs is provided, use it; otherwise load the latest ranked_jobs
    from disk. Generates tailored resume PDFs for the top jobs_for_resume jobs.

    Returns
    -------
    If return_pairs is True, returns a list of (RankedJob, pdf_path) for each
    generated resume. Otherwise returns None.
    """

    logger.info("=== Phase 2: Resume generation ===")

    cv_text = load_parsed_cv_text(config)
    if ranked_jobs is None:
        ranked_jobs = load_ranked_jobs_latest(config)

    if not ranked_jobs:
        logger.warning("No ranked jobs available for resume generation; aborting Phase 2.")
        return None if not return_pairs else []

    if jobs_for_resume <= 0:
        jobs_for_resume = len(ranked_jobs)

    selected_jobs = ranked_jobs[:jobs_for_resume]
    logger.info("Generating resumes for top %d jobs", len(selected_jobs))

    llm_client = build_llm_client(config)
    generator = ResumeGenerator(config, llm_client)
    latex_builder = LatexBuilder(config)

    resume_cfg = config.resume
    candidate_profile = {
        "candidate_name": resume_cfg.get("candidate_name", "Candidate"),
        "contact": {
            "email": resume_cfg.get("contact", {}).get("email", ""),
            "phone": resume_cfg.get("contact", {}).get("phone", ""),
            "location": resume_cfg.get("contact", {}).get("location", ""),
        },
    }

    pairs: List[Tuple[RankedJob, Path]] = []
    for job in selected_jobs:
        tailored = generator.generate_for_job(cv_text, job)
        pdf_path = latex_builder.render_and_compile(tailored, candidate_profile)
        pairs.append((job, pdf_path))
        logger.info(
            "Generated tailored resume PDF for '%s' at '%s': %s",
            job.title,
            job.company,
            pdf_path,
        )

    return pairs if return_pairs else None


def run_all(config: AppConfig, top_n: int = 200) -> None:
    """
    Run the full pipeline and produce a summary PDF.

    1. Phase 1: Parse CV, scrape jobs, rank top_n jobs (scrapes enough to get top_n).
    2. Phase 2: Generate a tailored resume PDF for each of the top_n jobs.
    3. Build job_summary.pdf: a table with links to each job page and each resume PDF.
    """

    logger.info("=== Run all: Phase 1 + Phase 2 + job summary PDF ===")

    # Phase 1: scrape enough jobs and rank to get top_n
    results_wanted = max(top_n + 100, 250)
    ranked_jobs = run_phase_1(
        config,
        max_jobs=None,
        results_wanted_override=results_wanted,
        top_k_override=top_n,
    )

    if not ranked_jobs:
        logger.warning("No ranked jobs; aborting run-all.")
        return

    # Phase 2: generate resumes and collect (job, pdf_path)
    pairs = run_phase_2(
        config,
        jobs_for_resume=top_n,
        ranked_jobs=ranked_jobs,
        return_pairs=True,
    )

    if not pairs:
        logger.warning("No resume pairs; skipping summary PDF.")
        return

    # Build summary table rows: rank, title, company, location, similarity, job_url, resume_filename
    rows = []
    for rank, (job, pdf_path) in enumerate(pairs, start=1):
        rows.append(
            {
                "rank": rank,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "similarity": job.similarity,
                "job_url": job.apply_link or "",
                "resume_filename": pdf_path.name,
            }
        )

    latex_builder = LatexBuilder(config)
    summary_path = latex_builder.render_job_summary_pdf(rows)
    logger.info("Job summary PDF with %d rows written to %s", len(rows), summary_path)


def run_from_url(config: AppConfig, job_url: str) -> None:
    """Parse job from URL and generate one tailored resume PDF (same flow as web app)."""
    from modules.job_url_parser import parse_job_from_url

    cv_text = _get_cv_text(config)
    llm_client = build_llm_client(config)
    parsed = parse_job_from_url(job_url, config, llm_client)
    job = RankedJob(
        title=parsed.title,
        company=parsed.company,
        location=parsed.location,
        description=parsed.description,
        apply_link=job_url,
        source_site="",
        similarity=0.0,
    )
    generator = ResumeGenerator(config, llm_client)
    latex_builder = LatexBuilder(config)
    resume_cfg = config.resume
    candidate_profile = {
        "candidate_name": resume_cfg.get("candidate_name", "Candidate"),
        "contact": {
            "email": resume_cfg.get("contact", {}).get("email", ""),
            "phone": resume_cfg.get("contact", {}).get("phone", ""),
            "location": resume_cfg.get("contact", {}).get("location", ""),
        },
    }
    content = generator.generate_for_job(cv_text, job)
    pdf_path = latex_builder.render_and_compile(content, candidate_profile)
    logger.info("Generated resume for %s at %s: %s", job.title, job.company, pdf_path)


def main() -> None:
    args = build_arg_parser().parse_args()

    load_environment()
    config = load_config(args.config)
    setup_logging(level=config.log_level, log_dir=config.log_dir)

    logger.info("JobApplicationAgent started")

    if args.url:
        run_from_url(config, args.url)
    elif args.run_all:
        run_all(config, top_n=args.top_n)
    else:
        if args.phase in ("1", "all"):
            run_phase_1(config, max_jobs=args.max_jobs)
        if args.phase in ("2", "all"):
            run_phase_2(config, jobs_for_resume=args.jobs_for_resume)

    logger.info("JobApplicationAgent finished")


if __name__ == "__main__":
    main()

