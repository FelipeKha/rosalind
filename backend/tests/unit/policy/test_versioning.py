from __future__ import annotations

from rosalind.config import ParserModelSettings
from rosalind.policy.application.versioning import interpreter_version

MODEL = ParserModelSettings(
    name="qwen3.5-9b",
    model="qwen3.5:9b",
    quantization="Q4_K_M",
)


def test_version_is_deterministic() -> None:
    assert interpreter_version(MODEL) == interpreter_version(MODEL)


def test_version_changes_with_model_or_quantization() -> None:
    base = interpreter_version(MODEL)
    other_model = interpreter_version(
        ParserModelSettings(name="other", model="other:8b", quantization="Q4_K_M")
    )
    other_quant = interpreter_version(
        ParserModelSettings(name="qwen3.5-9b", model="qwen3.5:9b", quantization="Q8_0")
    )

    assert base != other_model
    assert base != other_quant
    assert base.startswith("interp-")
