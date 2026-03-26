import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Literal, Optional

import spacy
from pdfminer.high_level import extract_text as pdf_extract_text

from .utils import AppConfig, ensure_dir, write_json


logger = logging.getLogger(__name__)


CV_SOURCE_TYPE = Literal["pdf", "txt"]


@dataclass
class ParsedCV:
    """
    Structured representation of a parsed CV.

    Only light structure is imposed here: raw text and basic NLP tokens.
    Modules further down the pipeline (keyword extraction, ranking, LLM)
    can enrich this structure.
    """

    source_path: str
    source_type: CV_SOURCE_TYPE
    raw_text: str
    sentences: List[str]
    tokens: List[str]

    def to_json(self) -> Dict:
        return asdict(self)


class CVParser:
    """
    Parse CVs from PDF or TXT into a normalized text representation.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        logger.info("Loading spaCy model '%s' for CV parsing", config.spacy_model)
        self._nlp = spacy.load(config.spacy_model, exclude=["ner"])  # fast enough for this use

    def parse(self, cv_path: Optional[Path] = None) -> ParsedCV:
        """
        Parse the configured CV file and persist the structured representation.

        Returns
        -------
        ParsedCV
            Structured CV representation.
        """

        if cv_path is None:
            cv_path = self.config.cv_path

        cv_path = cv_path.resolve()
        if not cv_path.exists():
            raise FileNotFoundError(f"CV file not found at {cv_path}")

        logger.info("Parsing CV at %s", cv_path)

        source_type: CV_SOURCE_TYPE
        if cv_path.suffix.lower() == ".pdf":
            source_type = "pdf"
            raw_text = self._parse_pdf(cv_path)
        else:
            source_type = "txt"
            raw_text = self._parse_txt(cv_path)

        doc = self._nlp(raw_text)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        tokens = [t.lemma_.lower() for t in doc if not (t.is_punct or t.is_space)]

        parsed = ParsedCV(
            source_path=str(cv_path),
            source_type=source_type,
            raw_text=raw_text,
            sentences=sentences,
            tokens=tokens,
        )

        output_path = self._get_output_path(cv_path)
        logger.info("Writing parsed CV JSON to %s", output_path)
        ensure_dir(output_path.parent)
        write_json(output_path, parsed.to_json())

        return parsed

    def _parse_pdf(self, path: Path) -> str:
        logger.debug("Extracting text from PDF via pdfminer.six")
        text = pdf_extract_text(str(path)) or ""
        return text.strip()

    def _parse_txt(self, path: Path) -> str:
        logger.debug("Reading text from TXT file")
        with path.open("r", encoding="utf-8") as f:
            return f.read().strip()

    def _get_output_path(self, cv_path: Path) -> Path:
        base_name = cv_path.stem
        return self.config.data_dir / "cv" / f"{base_name}_parsed.json"

