from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modules.latex_builder import LatexBuilder
from modules.llm_engine import build_llm_client
from modules.resume_generator import ResumeGenerator
from modules.utils import AppConfig, PROJECT_ROOT, load_config, load_environment, setup_logging


logger = logging.getLogger(__name__)

app = FastAPI(title="ResumeFormatter API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class ResumeJob:
    title: str
    company: str
    location: str
    description: str
    apply_link: str
    source_site: str
    similarity: float


class GenerateFromTextRequest(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = Field(min_length=40)


class GenerateFromTextResponse(BaseModel):
    pdf_url: str
    job: dict


@dataclass
class AppState:
    config: AppConfig
    generator: ResumeGenerator
    latex: LatexBuilder
    output_dir: Path


state: Optional[AppState] = None


@app.on_event("startup")
def on_startup() -> None:
    global state
    load_environment()
    config = load_config()
    setup_logging(level=config.log_level, log_dir=config.log_dir)
    llm_client = build_llm_client(config)
    generator = ResumeGenerator(config, llm_client)
    latex = LatexBuilder(config)

    output_root = PROJECT_ROOT / config.resume.get("output_dir", "data/resumes")
    output_root.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=str(output_root)), name="files")

    state = AppState(config=config, generator=generator, latex=latex, output_dir=output_root)
    logger.info("ResumeFormatter API started")


@app.get("/")
def health() -> dict:
    return {"status": "ok", "service": "ResumeFormatter"}


@app.post("/generate_from_text", response_model=GenerateFromTextResponse)
def generate_from_text(req: GenerateFromTextRequest) -> GenerateFromTextResponse:
    if state is None:
        raise HTTPException(status_code=500, detail="Server not initialized")
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Description cannot be empty")

    job = ResumeJob(
        title=req.title.strip() or "Job Role",
        company=req.company.strip() or "Company",
        location=req.location.strip(),
        description=req.description.strip(),
        apply_link="",
        source_site="extension",
        similarity=0.0,
    )

    resume_cfg = state.config.resume
    candidate_profile = {
        "candidate_name": resume_cfg.get("candidate_name", "Candidate"),
        "contact": {
            "email": resume_cfg.get("contact", {}).get("email", ""),
            "phone": resume_cfg.get("contact", {}).get("phone", ""),
            "location": resume_cfg.get("contact", {}).get("location", ""),
        },
    }

    try:
        content = state.generator.generate_for_job(job)
        with tempfile.NamedTemporaryFile(
            prefix="resume_", suffix=".pdf", delete=False, dir=str(state.output_dir)
        ) as tmp:
            out_path = Path(tmp.name)
        pdf_path = state.latex.render_and_compile(content, candidate_profile, output_path=out_path)
    except Exception as exc:
        logger.exception("Resume generation failed")
        raise HTTPException(status_code=500, detail=f"Resume generation failed: {exc}") from exc

    return GenerateFromTextResponse(
        pdf_url=f"/files/{pdf_path.name}",
        job={
            "title": content.job_title or job.title,
            "company": content.company or job.company,
            "location": req.location,
        },
    )
