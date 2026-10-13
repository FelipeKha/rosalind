"""Retrieval E2E over the real model: gold-set correctness + quality metrics.

Drives the real ``POST /search`` endpoint (lexical, semantic, hybrid), asserts
hard correctness guarantees (evidence reaches the assembled context, exact facts
are present, trash/spam excluded), and records empirical quality metrics plus a
diagnostic report artifact.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from support import db, load_gold, mrr, ndcg_at_k, recall_at_k
from support.report import write_json, write_markdown

pytestmark = pytest.mark.rag

REPORT_DIR = Path(__file__).resolve().parents[1] / "report"

MODES = ("hybrid", "lexical", "semantic")


def _search(base_url: str, query: str, mode: str, *, filters=None, limit=25) -> dict:
    payload: dict = {"query": query, "mode": mode, "view": "snippet", "limit": limit}
    if filters:
        payload["filters"] = filters
    response = httpx.post(f"{base_url}/search", json=payload, timeout=120.0)
    assert response.status_code == 200, response.text
    return response.json()


def _ranked_message_ids(response: dict, id_to_message: dict[str, str]) -> list[str]:
    return [
        id_to_message.get(str(result["item_id"]), str(result["item_id"]))
        for result in response["results"]
    ]


def _snippets(response: dict) -> str:
    return "\n".join(
        f"{r['subject'] or ''}\n{r['snippet'] or ''}" for r in response["results"]
    )


def test_gold_set_retrieval(rag_corpus) -> None:
    cases = load_gold()
    id_to_message = {
        email_id: message_id
        for message_id, email_id in db.message_id_to_email_id(rag_corpus.conn).items()
    }

    metrics = {"recall@20": [], "mrr": [], "ndcg@10": []}
    report_queries = []

    for case in cases:
        relevant = {e.message_id for e in case.evidence}

        hybrid = _search(rag_corpus.base_url, case.query, "hybrid")
        hybrid_ranked = _ranked_message_ids(hybrid, id_to_message)

        found = [mid for mid in hybrid_ranked if mid in relevant]
        evidence_rank = hybrid_ranked.index(found[0]) + 1 if found else None

        if case.answerable:
            # Hard correctness: at least one expected source reaches assembly.
            assert found, f"{case.id}: no expected evidence in results"
            if case.min_rank is not None:
                assert evidence_rank is not None and evidence_rank <= case.min_rank, (
                    f"{case.id}: evidence {found[0]} at rank {evidence_rank} "
                    f"exceeds min_rank {case.min_rank}"
                )
            # Exact facts survive into the assembled snippets.
            snippets = _snippets(hybrid)
            for fact in case.required_facts:
                assert fact in snippets, (
                    f"{case.id}: required fact {fact!r} not in assembled context"
                )

        # Quality metrics (measured, not thresholded), answerable cases only.
        if case.answerable:
            ranked_relevant = [mid in relevant for mid in hybrid_ranked]
            metrics["recall@20"].append(recall_at_k(ranked_relevant, 20))
            metrics["mrr"].append(mrr(ranked_relevant))
            metrics["ndcg@10"].append(
                ndcg_at_k([1 if r else 0 for r in ranked_relevant], 10)
            )

        report_queries.append(
            {
                "id": case.id,
                "query": case.query,
                "answerable": case.answerable,
                "modes": [
                    _mode_summary(
                        _search(rag_corpus.base_url, case.query, mode),
                        id_to_message,
                        relevant,
                    )
                    for mode in MODES
                ],
                "evidence_rank": evidence_rank,
            }
        )

    _write_report(
        rag_corpus,
        metrics={
            key: sum(values) / len(values) if values else None
            for key, values in metrics.items()
        },
        queries=report_queries,
    )


def test_trash_spam_excluded_then_included(rag_corpus) -> None:
    id_to_message = {
        email_id: message_id
        for message_id, email_id in db.message_id_to_email_id(rag_corpus.conn).items()
    }

    default = _search(rag_corpus.base_url, "hotel reservation Lyon", "hybrid")
    default_mids = set(_ranked_message_ids(default, id_to_message))
    assert "msg-014@example.test" not in default_mids

    included = _search(
        rag_corpus.base_url,
        "hotel reservation Lyon",
        "hybrid",
        filters={"include_trash_spam": True},
    )
    included_mids = set(_ranked_message_ids(included, id_to_message))
    assert "msg-014@example.test" in included_mids


def test_semantic_mode_returns_embedding_backed_results(rag_corpus) -> None:
    response = _search(rag_corpus.base_url, "invoice number", "semantic")
    assert response["mode_effective"] == "semantic"
    assert response["results"]


def test_reranking_applied(rag_corpus) -> None:
    # The cross-encoder loads lazily on the first ranked search; a cold load can
    # exceed the deadline and degrade to fused order once, so retry a few times.
    warnings: set[str] = set()
    for _ in range(3):
        response = _search(rag_corpus.base_url, "What is the invoice number?", "hybrid")
        warnings = {w["code"] for w in response.get("warnings", [])}
        if "rerank_skipped" not in warnings:
            break
    assert "rerank_skipped" not in warnings
    assert response["results"]


def _mode_summary(response: dict, id_to_message, relevant) -> dict:
    ranked = _ranked_message_ids(response, id_to_message)
    found = [mid for mid in ranked if mid in relevant]
    return {
        "mode": response["mode_effective"],
        "evidence_found": bool(found),
        "evidence_assembled": bool(found),
        "evidence_rank": ranked.index(found[0]) + 1 if found else None,
        "top": ranked[:10],
    }


def _write_report(rag_corpus, *, metrics: dict, queries: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {
        "corpus_fixture": "e2e/fixtures/google/takeout/Mail/rosalind_synthetic_emails.mbox",
        "import_id": rag_corpus.import_id,
        "embedding_space": "bge_m3_v1",
        "metrics": metrics,
        "queries": queries,
    }
    write_json(REPORT_DIR / f"email_rag_{timestamp}.json", payload)
    write_markdown(REPORT_DIR / f"email_rag_{timestamp}.md", payload)
