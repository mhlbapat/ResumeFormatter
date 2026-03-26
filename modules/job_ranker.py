import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer, util

from .utils import AppConfig, ensure_dir, slugify, write_json


logger = logging.getLogger(__name__)


@dataclass
class RankedJob:
    """
    Job posting augmented with similarity score to the CV.
    """

    title: str
    company: str
    location: str
    description: str
    apply_link: str
    source_site: str
    similarity: float

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


class JobRanker:
    """
    Rank job postings by semantic similarity to a CV using sentence-transformers.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        model_name = config.ranking.get(
            "model_name", "sentence-transformers/all-MiniLM-L6-v2"
        )
        logger.info("Loading sentence-transformers model '%s'", model_name)
        self._model = SentenceTransformer(model_name)

    def rank_jobs(
        self,
        cv_text: str,
        jobs: Sequence[Dict[str, Any]],
        label: Optional[str] = None,
        top_k_override: Optional[int] = None,
    ) -> List[RankedJob]:
        """
        Rank a list of jobs according to similarity with the CV text.

        Parameters
        ----------
        cv_text:
            Raw CV text.
        jobs:
            Iterable of job dictionaries with description and metadata.
        label:
            Optional label used in naming the output file.
        top_k_override:
            If set, overrides config.ranking.top_k for this run.
        """

        if not jobs:
            logger.warning("No jobs provided for ranking")
            return []

        descriptions = [job.get("description", "") for job in jobs]
        cv_embedding = self._model.encode(cv_text, convert_to_tensor=True)
        job_embeddings = self._model.encode(descriptions, convert_to_tensor=True)

        similarities_tensor = util.cos_sim(cv_embedding, job_embeddings)[0]
        similarities = similarities_tensor.cpu().numpy().tolist()

        ranked: List[RankedJob] = []
        for job, sim in zip(jobs, similarities):
            ranked.append(
                RankedJob(
                    title=str(job.get("title", "")).strip(),
                    company=str(job.get("company", "")).strip(),
                    location=str(job.get("location", "")).strip(),
                    description=str(job.get("description", "")).strip(),
                    apply_link=str(job.get("apply_link", "")).strip(),
                    source_site=str(job.get("source_site", "")).strip(),
                    similarity=float(sim),
                )
            )

        ranked.sort(key=lambda j: j.similarity, reverse=True)

        top_k = int(
            top_k_override
            if top_k_override is not None
            else self.config.ranking.get("top_k", 50)
        )
        similarity_threshold = float(self.config.ranking.get("similarity_threshold", 0.0))
        filtered = [
            job for job in ranked[:top_k] if job.similarity >= similarity_threshold
        ]

        self._persist_results(filtered, label or "default")
        return filtered

    def _persist_results(self, ranked_jobs: List[RankedJob], label: str) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        slug = slugify(label)
        output_path = (
            self.config.data_dir / "ranked_jobs" / f"ranked_jobs_{slug}_{timestamp}.json"
        )
        logger.info(
            "Writing %d ranked jobs with label '%s' to %s",
            len(ranked_jobs),
            label,
            output_path,
        )
        ensure_dir(output_path.parent)
        payload = [job.to_json() for job in ranked_jobs]
        write_json(output_path, payload)

