"""Unit tests for ingestion stage logging (content-free ok/skipped/failed)."""

from __future__ import annotations

import json
import logging
import time

from rosalind.application.services.emails import (
    PHASE_DONE,
    PHASE_PROGRESS,
    STAGE_CANONICALIZE,
    STAGE_CHUNK,
    STAGE_EMBED,
    PipelineEvent,
    _event_outcomes,
    _record_event,
)
from rosalind.logging import JsonFormatter


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))


def _capture(callback):
    handler = _Capture()
    logger = logging.getLogger("rosalind.ingestion")
    previous_level = logger.level
    previous_propagate = logger.propagate
    previous_disabled = logger.disabled
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    logger.addHandler(handler)
    try:
        callback()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        logger.disabled = previous_disabled
    return handler.records


def test_event_outcomes_split_and_canonicalize() -> None:
    event = PipelineEvent(
        stage=STAGE_CANONICALIZE, phase=PHASE_DONE, created=3, reused=2, failed=1
    )
    assert _event_outcomes(event) == (3, 2, 1)


def test_event_outcomes_chunk_details() -> None:
    event = PipelineEvent(
        stage=STAGE_CHUNK,
        phase=PHASE_DONE,
        details={"chunks_written": 4, "chunks_unchanged": 1, "failed": 0},
    )
    assert _event_outcomes(event) == (4, 1, 0)


def test_event_outcomes_embed_details() -> None:
    event = PipelineEvent(
        stage=STAGE_EMBED,
        phase=PHASE_DONE,
        details={"embedded": 5, "reused": 2, "failed": 1},
    )
    assert _event_outcomes(event) == (5, 2, 1)


def test_record_event_logs_counts_and_accumulates_terminal() -> None:
    summary: dict[str, tuple[int, int, int]] = {}
    started = time.perf_counter()
    events = [
        PipelineEvent(
            stage=STAGE_CANONICALIZE,
            phase=PHASE_PROGRESS,
            processed=10,
            created=5,
            reused=3,
            failed=2,
        ),
        PipelineEvent(
            stage=STAGE_CANONICALIZE,
            phase=PHASE_DONE,
            created=5,
            reused=3,
            failed=2,
        ),
    ]

    def _run() -> None:
        for event in events:
            _record_event(event, summary, started)

    records = _capture(_run)

    assert all(r["event"] == "ingestion_stage" for r in records)
    assert all(r["stage"] == "canonicalize" for r in records)
    # Only the terminal event contributes to the summary, keyed by stage.
    assert summary["canonicalize"] == (5, 3, 2)
    terminal = next(r for r in records if r["phase"] == "done")
    assert terminal["ok"] == 5
    assert terminal["skipped_unchanged"] == 3
    assert terminal["failed"] == 2


def test_rerun_logs_skipped_unchanged() -> None:
    summary: dict[str, tuple[int, int, int]] = {}
    event = PipelineEvent(
        stage=STAGE_CANONICALIZE, phase=PHASE_DONE, created=0, reused=7, failed=0
    )
    records = _capture(lambda: _record_event(event, summary, time.perf_counter()))
    assert records[0]["skipped_unchanged"] == 7
    assert records[0]["ok"] == 0
    assert summary["canonicalize"] == (0, 7, 0)
