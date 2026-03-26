import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

import spacy

from .utils import AppConfig, ensure_dir, read_json, write_json


logger = logging.getLogger(__name__)


@dataclass
class CVKeywords:
    """
    Structured set of keywords extracted from a CV.
    """

    skills: List[str]
    technical_keywords: List[str]
    domain_phrases: List[str]

    def to_json(self) -> Dict:
        return asdict(self)


class KeywordExtractor:
    """
    Extract skills and domain keywords from parsed CV text.

    This implementation uses spaCy noun chunks and simple heuristics instead of
    a full TF-IDF pipeline to avoid unnecessary heavy dependencies, while
    keeping the module independently testable.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        logger.info("Loading spaCy model '%s' for keyword extraction", config.spacy_model)
        self._nlp = spacy.load(config.spacy_model)

    def extract_from_parsed_cv(
        self,
        parsed_cv_json: Optional[Path] = None,
    ) -> CVKeywords:
        """
        Load a parsed CV JSON file and extract keyword sets.
        """

        if parsed_cv_json is None:
            # default: use parsed JSON derived from configured CV path
            cv_stem = self.config.cv_path.stem
            parsed_cv_json = self.config.data_dir / "cv" / f"{cv_stem}_parsed.json"

        parsed_cv_json = parsed_cv_json.resolve()
        if not parsed_cv_json.exists():
            raise FileNotFoundError(f"Parsed CV JSON not found at {parsed_cv_json}")

        logger.info("Extracting keywords from parsed CV at %s", parsed_cv_json)
        data = read_json(parsed_cv_json)
        raw_text: str = data.get("raw_text", "")

        doc = self._nlp(raw_text)

        skills: List[str] = []
        technical_keywords: List[str] = []
        domain_phrases: List[str] = []

        # Collect candidate phrases from noun chunks
        for chunk in doc.noun_chunks:
            phrase = chunk.text.strip()
            if len(phrase) < 2:
                continue
            normalized = phrase.lower()
            if normalized not in domain_phrases:
                domain_phrases.append(normalized)

        # Token-level heuristics for skills & technical keywords
        for token in doc:
            if token.is_stop or token.is_punct or token.is_space:
                continue

            text = token.text.strip()
            norm = token.lemma_.lower()

            # Simple heuristic: uppercase or contains digits -> likely tech keyword
            if any(ch.isdigit() for ch in text) or text.isupper():
                if norm not in technical_keywords:
                    technical_keywords.append(norm)

            # POS-based heuristic for skills (nouns & proper nouns)
            if token.pos_ in {"NOUN", "PROPN"} and len(norm) > 2:
                if norm not in skills:
                    skills.append(norm)

        keywords = CVKeywords(
            skills=skills,
            technical_keywords=technical_keywords,
            domain_phrases=domain_phrases,
        )

        output_path = self._get_output_path(parsed_cv_json)
        logger.info("Writing extracted CV keywords JSON to %s", output_path)
        ensure_dir(output_path.parent)
        write_json(output_path, keywords.to_json())

        return keywords

    def _get_output_path(self, parsed_cv_json: Path) -> Path:
        base_name = parsed_cv_json.stem.replace("_parsed", "")
        return self.config.data_dir / "cv" / f"{base_name}_keywords.json"

