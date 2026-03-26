import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def setup_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> None:
    """
    Configure application-wide logging.

    Parameters
    ----------
    level:
        Logging level name (e.g. \"DEBUG\", \"INFO\").
    log_dir:
        Optional directory to write a rotating log file into.
    """

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handlers = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "job_application_agent.log")
        handlers.append(file_handler)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=handlers,
    )


@dataclass
class AppConfig:
    """Strongly-typed subset of application configuration."""

    cv_path: Path
    data_dir: Path
    log_dir: Path
    log_level: str
    spacy_model: str

    scraping: Dict[str, Any]
    ranking: Dict[str, Any]
    llm: Dict[str, Any]
    resume: Dict[str, Any]
    browser: Dict[str, Any]


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """
    Load configuration from YAML file and environment.

    Environment variables can be used by downstream modules, but this function
    focuses on file-based configuration.
    """

    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "settings.yaml"

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    app_cfg = raw.get("app", {})

    data_dir = PROJECT_ROOT / app_cfg.get("data_dir", "data")
    log_dir = PROJECT_ROOT / app_cfg.get("log_dir", "logs")

    return AppConfig(
        cv_path=PROJECT_ROOT / app_cfg.get("cv_path", "data/cv/Resume.pdf"),
        data_dir=data_dir,
        log_dir=log_dir,
        log_level=app_cfg.get("log_level", "INFO"),
        spacy_model=raw.get("nlp", {}).get("spacy_model", "en_core_web_sm"),
        scraping=raw.get("scraping", {}),
        ranking=raw.get("ranking", {}),
        llm=raw.get("llm", {}),
        resume=raw.get("resume", {}),
        browser=raw.get("browser", {}),
    )


def load_environment(dotenv_path: Optional[Path] = None) -> None:
    """
    Load environment variables from a .env file if present.

    Parameters
    ----------
    dotenv_path:
        Optional explicit path to .env. Defaults to PROJECT_ROOT / \".env\".
    """

    if dotenv_path is None:
        dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)


def ensure_dir(path: Path) -> None:
    """Create directory if it does not exist."""

    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    """Read JSON from a file path."""

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    """Write JSON to a file path atomically."""

    ensure_dir(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def slugify(text: str, max_length: int = 60) -> str:
    """
    Create a filesystem-safe slug from arbitrary text.
    """

    safe = "".join(ch if ch.isalnum() else "-" for ch in text.lower())
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip("-")
    return safe or "item"


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Read an environment variable with an optional default.
    """

    return os.getenv(name, default)


def latex_escape(text: str) -> str:
    """
    Escape a string for safe use inside LaTeX (e.g. in table cells).
    """
    if not text:
        return ""
    replacements = [
        ("\\", "\\textbackslash{}"),
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]
    out = text
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def latex_escape_url(url: str) -> str:
    """
    Escape a URL for use inside \\href{...}{...} in LaTeX.
    """
    if not url:
        return ""
    return (
        url.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("#", "\\#")
        .replace("&", "\\&")
        .replace("~", "\\textasciitilde{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )

