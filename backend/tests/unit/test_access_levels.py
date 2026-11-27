"""Unit tests for per-level access-enforcement configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rosalind.application.authz import AccessEnforcementLevels
from rosalind.config import AccessEnforcementLevelSettings, PolicySettings


def test_default_levels_are_all_enabled() -> None:
    levels = AccessEnforcementLevels()
    assert levels.output_safe
    assert levels.enabled_names() == (
        "lexical",
        "semantic",
        "listing",
        "metadata",
        "thread",
        "assembly",
        "verification",
    )
    assert levels.disabled_names() == ()


def test_disabled_levels_are_reported() -> None:
    levels = AccessEnforcementLevels(lexical=False, listing=False, verification=False)
    assert levels.disabled_names() == ("lexical", "listing", "verification")
    assert levels.output_safe  # assembly is still enabled


def test_output_safe_requires_assembly_or_verification() -> None:
    assert not AccessEnforcementLevels(assembly=False, verification=False).output_safe
    assert AccessEnforcementLevels(assembly=True, verification=False).output_safe
    assert AccessEnforcementLevels(assembly=False, verification=True).output_safe


def test_config_rejects_enforcement_without_output_safety() -> None:
    with pytest.raises(ValidationError):
        PolicySettings(
            access_enforcement_enabled=True,
            access_enforcement_levels=AccessEnforcementLevelSettings(
                assembly=False, verification=False
            ),
        )


def test_config_allows_unsafe_levels_when_master_is_off() -> None:
    settings = PolicySettings(
        access_enforcement_enabled=False,
        access_enforcement_levels=AccessEnforcementLevelSettings(
            assembly=False, verification=False
        ),
    )
    assert not settings.access_enforcement_levels.assembly
    assert not settings.access_enforcement_levels.verification
