"""Interpreter versioning.

The version is a hash of everything that can change the mapping from prompt to
policy. It is recorded on every revision so a confirmed policy can always be
traced to the exact model, quantization, prompt template and resolver set.
"""

from __future__ import annotations

import hashlib

from rosalind.config import ParserModelSettings
from rosalind.policy.domain.spec import SCHEMA_VERSION

PROMPT_TEMPLATE_VERSION = "interpreter-prompt-v1"
RESOLVER_VERSION = "resolvers-v1"
RUNTIME_VERSION = "ollama-http-v1"


def interpreter_version(model: ParserModelSettings) -> str:
    material = "|".join(
        [
            model.name,
            model.provider,
            model.model,
            model.quantization or "",
            RUNTIME_VERSION,
            PROMPT_TEMPLATE_VERSION,
            SCHEMA_VERSION,
            RESOLVER_VERSION,
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"interp-{digest}"
