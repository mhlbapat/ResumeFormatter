"""
LLM abstraction layer for JobApplicationAgent.

This module provides a small, testable interface for interacting with
language models. It currently supports:

- OpenAI ChatCompletion API (default)
- Local Ollama HTTP API

Configuration is driven by the ``llm`` section in ``settings.yaml`` and
API keys / base URLs are provided via environment variables.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

try:
    from openai import OpenAI  # type: ignore[import]
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]
import requests

from .utils import AppConfig, get_env


logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    """Container for a single LLM completion request."""

    system_prompt: str
    user_prompt: str
    temperature: float = 0.3
    # max_tokens here means max *output* (completion) tokens. Input is only limited by the model's context window.
    max_tokens: int = 15000


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> str:
        """Generate a completion for the given request."""


class OpenAIClient(BaseLLMClient):
    """
    LLM client backed by the OpenAI API (openai>=1.0.0).
    Uses the OpenAI() client and chat.completions.create().
    """

    def __init__(self, model: str, default_params: Dict[str, object]):
        if OpenAI is None:
            raise RuntimeError(
                "openai is not installed. Install it with 'pip install openai' "
                "or set llm.provider to 'google' or 'ollama' in settings.yaml."
            )
        api_key = get_env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.default_params = default_params

    def complete(self, request: LLMRequest) -> str:
        logger.info("Calling OpenAI model '%s'", self.model)
        response = self._client.chat.completions.create(
            model=self.model,
            max_completion_tokens=request.max_tokens or self.default_params.get("max_tokens", 15000),
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        )
        message = response.choices[0].message
        return (message.content or "").strip()


class OllamaClient(BaseLLMClient):
    """
    LLM client backed by a local Ollama server.

    Uses the streaming ``/api/generate`` endpoint and concatenates all
    ``response`` chunks into a single string.
    """

    def __init__(self, model: str, base_url: Optional[str] = None):
        self.model = model
        self.base_url = base_url or get_env("OLLAMA_BASE_URL", "http://localhost:11434")

    def complete(self, request: LLMRequest) -> str:
        logger.info("Calling Ollama model '%s' at %s", self.model, self.base_url)

        payload = {
            "model": self.model,
            "prompt": f"{request.system_prompt}\n\n{request.user_prompt}",
            # Omit temperature so the Ollama model uses its own default.
            "options": {},
            "stream": True,
        }

        resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=300)
        resp.raise_for_status()

        text_parts = []
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            piece = obj.get("response")
            if piece:
                text_parts.append(piece)
            if obj.get("done"):
                break

        return "".join(text_parts)


class GoogleClient(BaseLLMClient):
    """
    LLM client backed by the Google Gemini API via the google-genai SDK.

    The client library reads the API key from the GEMINI_API_KEY environment
    variable when instantiated, matching the official quickstart.
    """

    def __init__(self, model: str, default_params: Dict[str, object]):
        try:
            from google import genai  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is not installed. Install it with 'pip install google-genai' "
                "and set GEMINI_API_KEY in your environment."
            ) from exc

        self._genai = genai
        self.client = genai.Client()
        self.model = model
        self.default_params = default_params

    def complete(self, request: LLMRequest) -> str:
        logger.info("Calling Google Gemini model '%s'", self.model)

        # Combine system and user prompts into a single text content. The Gemini
        # SDK accepts a plain string for the ``contents`` parameter.
        contents = f"{request.system_prompt}\n\n{request.user_prompt}"

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
        )

        # google-genai exposes a convenience ``text`` property that joins the
        # primary text parts from the response.
        return response.text


def build_llm_client(config: AppConfig) -> BaseLLMClient:
    """
    Factory function for creating an LLM client based on configuration.
    """

    provider = config.llm.get("provider", "openai")
    model = config.llm.get("model", "gpt-5-mini")
    max_out = config.llm.get("max_output_tokens") or config.llm.get("max_tokens")
    default_params: Dict[str, object] = {
        "max_tokens": int(max_out if max_out is not None else 15000),
    }

    if provider == "openai":
        return OpenAIClient(model=model, default_params=default_params)
    if provider == "ollama":
        return OllamaClient(model=model)
    if provider == "google":
        return GoogleClient(model=model, default_params=default_params)

    raise ValueError(f"Unsupported LLM provider: {provider}")

