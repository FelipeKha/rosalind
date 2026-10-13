"""Local LLM adapters for draft-question generation.

Uses Ollama (an OpenAI-compatible local server) through Instructor so the model
returns a validated ``DraftQuestion``. No email content leaves the machine.

``instructor`` / ``openai`` live in the optional ``gen`` dependency group, so the
import is lazy and only this adapter needs them::

    uv sync --group gen
"""

from __future__ import annotations

from typing import Any

from rosalind_eval.corpus import Passage
from rosalind_eval.generate import SYSTEM_PROMPT, DraftQuestion, build_prompt

__all__ = ["OllamaQuestionLLM", "make_ollama_llm"]

DEFAULT_MODEL = "llama3.1"
DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaQuestionLLM:
    """A ``QuestionLLM`` backed by a local Ollama model via Instructor."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def generate(self, passage: Passage) -> DraftQuestion:
        result: DraftQuestion = self._client.chat.completions.create(
            model=self._model,
            response_model=DraftQuestion,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(passage)},
            ],
        )
        return DraftQuestion.model_validate(result)


def make_ollama_llm(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> OllamaQuestionLLM:
    """Build an Ollama-backed generator. Requires the optional ``gen`` deps."""
    try:
        import instructor  # type: ignore[import-not-found]
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "question generation needs the optional 'gen' dependencies: "
            "run `uv sync --group gen`"
        ) from exc

    client: Any = instructor.from_openai(OpenAI(base_url=base_url, api_key="ollama"))
    return OllamaQuestionLLM(client, model)
