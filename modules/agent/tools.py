import json
import tempfile
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from modules.utils import PROJECT_ROOT

class GenerateResumeInput(BaseModel):
    title: str = Field(description="Job Title")
    company: str = Field(description="Hiring Company")
    location: str = Field(description="Job Location")
    description: str = Field(description="Full Job Description")

class ExtractFormInput(BaseModel):
    form_schema: str = Field(description="JSON string representation of form fields")

def create_tools(app_state):
    
    @tool("generate_resume", args_schema=GenerateResumeInput)
    def generate_resume(title: str, company: str, location: str, description: str) -> str:
        """Generates a tailored resume for a specific job description and returns the PDF URL."""
        from web.app import ResumeJob
        job = ResumeJob(
            title=title,
            company=company,
            location=location,
            description=description,
            apply_link="",
            source_site="agent",
            similarity=0.0
        )
        
        resume_cfg = app_state.config.resume
        candidate_name = resume_cfg.get("candidate_name", "Candidate")
        candidate_profile = {
            "candidate_name": candidate_name,
            "contact": {
                "email": resume_cfg.get("contact", {}).get("email", ""),
                "phone": resume_cfg.get("contact", {}).get("phone", ""),
                "location": resume_cfg.get("contact", {}).get("location", ""),
            },
        }

        try:
            content = app_state.generator.generate_for_job(job)
            with tempfile.NamedTemporaryFile(
                prefix="resume_", suffix=".pdf", delete=False, dir=str(app_state.output_dir)
            ) as tmp:
                out_path = Path(tmp.name)
            pdf_path = app_state.latex.render_and_compile(content, candidate_profile, output_path=out_path)
            # URL is relative to the mount point in FastAPI
            return f"Resume successfully generated. You can download it at: /files/{pdf_path.name}"
        except Exception as exc:
            return f"Failed to generate resume: {str(exc)}"

    @tool("autofill_form", args_schema=ExtractFormInput)
    def autofill_form(form_schema: str) -> str:
        """Autofills a job application form given a JSON schema of the fields."""
        try:
            schema_dict = json.loads(form_schema)
        except Exception:
            return "Error: form_schema must be valid JSON."

        resume_cfg = app_state.config.resume
        profile_path = PROJECT_ROOT / resume_cfg.get("projects_path", "data/cv/profile.md")
        if not profile_path.exists():
            return "Error: Profile file not found."
        profile_text = profile_path.read_text("utf-8")

        job_search_cfg = app_state.config._data.get("job_search", {})
        prompt_path = PROJECT_ROOT / job_search_cfg.get("autofill_prompt_path", "prompts/autofill_prompt.txt")
        if not prompt_path.exists():
            return "Error: Autofill prompt file not found."
        system_prompt = prompt_path.read_text("utf-8").replace("<<FULL_PROFILE_TEXT>>", profile_text)

        user_prompt = f"Form Schema:\n{json.dumps(schema_dict, indent=2)}"

        from modules.llm_engine import LLMRequest
        llm_req = LLMRequest(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1)

        try:
            response_text = app_state.generator.llm.complete(llm_req)
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            return f"Autofilled Data: {clean_text}"
        except Exception as exc:
            return f"Error autofilling form: {str(exc)}"

    return [generate_resume, autofill_form]
