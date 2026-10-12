"""Support helpers for the email-RAG e2e suite."""

from .gold import Evidence, GoldCase, load_gold
from .metrics import mrr, ndcg_at_k, recall_at_k

__all__ = [
    "Evidence",
    "GoldCase",
    "load_gold",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
]
