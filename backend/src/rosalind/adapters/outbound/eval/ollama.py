"""Local LLM question generator (Ollama via Instructor).

Implements the ``QuestionLLM`` port. Uses an OpenAI-compatible local Ollama
server through Instructor so the model returns a validated ``DraftQuestion``. No
email content leaves the machine. Requires the optional ``eval`` dependencies.
"""

from __future__ import annotations

from typing import Any

from rosalind.application.eval.generate import SYSTEM_PROMPT, build_prompt
from rosalind.application.eval.models import DraftQuestion, Passage

__all__ = ["OllamaQuestionLLM", "make_ollama_llm"]

DEFAULT_MODEL = "llama3.1"
DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaQuestionLLM:
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
    """Build an Ollama-backed generator. Requires the optional ``eval`` deps."""
    try:
        import instructor
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "question generation needs the optional 'eval' dependencies: "
            "run `uv sync --group eval`"
        ) from exc

    client: Any = instructor.from_openai(OpenAI(base_url=base_url, api_key="ollama"))
    return OllamaQuestionLLM(client, model)
