import pytest


from modules.resume_generator import _extract_first_json_object, ResumeGenerator
from modules.llm_engine import BaseLLMClient, LLMRequest
from modules.utils import AppConfig


class DummyLLM(BaseLLMClient):
    def complete(self, request: LLMRequest) -> str:
        # Not used by these unit tests; provided to satisfy the BaseLLMClient API.
        return ""


def _make_generator() -> ResumeGenerator:
    # Minimal config; tests call only JSON parsing/prompt helpers.
    return ResumeGenerator(
        config=AppConfig(
            cv_path=__import__("pathlib").Path("dummy.pdf"),
            data_dir=__import__("pathlib").Path("data"),
            log_dir=__import__("pathlib").Path("logs"),
            log_level="INFO",
            llm={},
            resume={"projects_path": "data/cv/profile.md", "use_projects_only": True},
        ),
        llm_client=DummyLLM(),
    )


def test_extract_first_json_object_handles_code_fences():
    raw = (
        "Here is the result:\n"
        "```json\n"
        '{ "job_title": "Engineer", "company": "ACME", "location": "NY", '
        '"phd_degree": "Mechanics, Chemistry and Materials", '
        '"summary": "x", "skills": [], "research_experience": [] }\n'
        "```"
    )
    extracted = _extract_first_json_object(raw)
    assert extracted is not None
    assert '"job_title": "Engineer"' in extracted


def test_parse_response_json_plain_json():
    gen = _make_generator()
    raw = (
        '{ "job_title": "Engineer", "company": "ACME", "location": "NY", '
        '"phd_degree": "Mechanics, Chemistry and Materials", '
        '"summary": "x", "skills": [], "research_experience": [] }'
    )
    data = gen._parse_response_json(raw)
    assert data["job_title"] == "Engineer"
    assert data["company"] == "ACME"


def test_parse_response_json_trailing_commas_cleanup():
    gen = _make_generator()
    raw = (
        "Noise before {\"job_title\":\"Engineer\",\"company\":\"ACME\","
        "\"location\":\"NY\",\"phd_degree\":\"Mechanics, Chemistry and Materials\","
        "\"summary\":\"x\",\"skills\":[],\"research_experience\":[],}"
        " Noise after"
    )
    data = gen._parse_response_json(raw)
    assert data["company"] == "ACME"
    assert data["job_title"] == "Engineer"

