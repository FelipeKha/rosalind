"""Unit tests for per-level semantic-enforcement configuration."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from rosalind.application.authz import SemanticEnforcementLevels
from rosalind.application.semantic import SemanticScope, SemanticStatement, Treatment
from rosalind.config import PolicySettings, SemanticEnforcementLevelSettings


def test_default_levels_are_all_enabled() -> None:
    levels = SemanticEnforcementLevels()
    assert levels.output_safe
    assert levels.can_produce_sanitized_text
    assert levels.build_enabled
    assert levels.enabled_names() == (
        "candidate_generation",
        "verification",
        "sanitization",
        "lexical",
        "semantic",
        "listing",
        "metadata",
        "thread",
        "rerank",
        "assembly",
        "jit",
        "final_gate",
        "derived",
        "term_features",
        "quoted_copy",
    )
    assert levels.disabled_names() == ()


def test_disabled_levels_are_reported() -> None:
    levels = SemanticEnforcementLevels(
        candidate_generation=False, lexical=False, quoted_copy=False
    )
    assert levels.disabled_names() == (
        "candidate_generation",
        "lexical",
        "quoted_copy",
    )
    assert levels.output_safe
    assert levels.can_produce_sanitized_text


def test_output_safe_requires_assembly_or_final_gate() -> None:
    assert not SemanticEnforcementLevels(assembly=False, final_gate=False).output_safe
    assert SemanticEnforcementLevels(assembly=True, final_gate=False).output_safe
    assert SemanticEnforcementLevels(assembly=False, final_gate=True).output_safe


def test_sanitized_text_requires_sanitization_or_jit() -> None:
    assert not SemanticEnforcementLevels(
        sanitization=False, jit=False
    ).can_produce_sanitized_text
    assert SemanticEnforcementLevels(
        sanitization=True, jit=False
    ).can_produce_sanitized_text
    assert SemanticEnforcementLevels(
        sanitization=False, jit=True
    ).can_produce_sanitized_text


def test_build_enabled_tracks_offline_levels() -> None:
    assert not SemanticEnforcementLevels(
        candidate_generation=False, verification=False, sanitization=False
    ).build_enabled


def test_config_rejects_enforcement_without_output_safety() -> None:
    with pytest.raises(ValidationError):
        PolicySettings(
            semantic_enforcement_enabled=True,
            semantic_enforcement_levels=SemanticEnforcementLevelSettings(
                assembly=False, final_gate=False
            ),
        )


def test_config_rejects_enforcement_without_sanitization() -> None:
    with pytest.raises(ValidationError):
        PolicySettings(
            semantic_enforcement_enabled=True,
            semantic_enforcement_levels=SemanticEnforcementLevelSettings(
                sanitization=False, jit=False
            ),
        )


def test_config_allows_unsafe_levels_when_master_is_off() -> None:
    settings = PolicySettings(
        semantic_enforcement_enabled=False,
        semantic_enforcement_levels=SemanticEnforcementLevelSettings(
            assembly=False, final_gate=False, sanitization=False, jit=False
        ),
    )
    assert not settings.semantic_enforcement_levels.assembly
    assert not settings.semantic_enforcement_levels.final_gate


def test_semantic_scope_set_id_is_order_independent() -> None:
    account_id = uuid.uuid4()
    first = SemanticStatement(policy_id="pol_1", statement_id="st_1")
    second = SemanticStatement(
        policy_id="pol_2", statement_id="st_2", treatment=Treatment()
    )
    a = SemanticScope.build(
        account_id=account_id, policy_version=1, statements=(first, second)
    )
    b = SemanticScope.build(
        account_id=account_id, policy_version=1, statements=(second, first)
    )
    assert a.set_id == b.set_id


def test_semantic_scope_set_id_changes_with_treatment() -> None:
    account_id = uuid.uuid4()
    statement = SemanticStatement(policy_id="pol_1", statement_id="st_1")
    a = SemanticScope.build(
        account_id=account_id, policy_version=1, statements=(statement,)
    )
    b = SemanticScope.build(
        account_id=account_id,
        policy_version=1,
        statements=(
            SemanticStatement(
                policy_id="pol_1",
                statement_id="st_1",
                match_levels=("asserts",),
            ),
        ),
    )
    assert a.set_id != b.set_id


def test_holds_until_ready_only_for_building_statements() -> None:
    account_id = uuid.uuid4()
    building = SemanticStatement(
        policy_id="pol_1",
        statement_id="st_1",
        status="building",
        hold_until_ready=True,
    )
    active = SemanticStatement(
        policy_id="pol_1",
        statement_id="st_1",
        status="active",
        hold_until_ready=True,
    )
    scope = SemanticScope.build(
        account_id=account_id, policy_version=1, statements=(building,)
    )
    assert scope.holds_until_ready
    scope = SemanticScope.build(
        account_id=account_id, policy_version=1, statements=(active,)
    )
    assert not scope.holds_until_ready
