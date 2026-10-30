"""Unit tests for the composition-root search model warm-up."""

from __future__ import annotations

from rosalind.adapters import composition


class _FakeWarmable:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    def warmup(self) -> None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("boom")


def _set_models(monkeypatch, *, embedder, reranker, enabled=True) -> None:
    monkeypatch.setattr(composition.settings, "embedder_warmup", enabled)
    monkeypatch.setattr(composition, "_embedder", embedder)
    monkeypatch.setattr(composition, "_search_reranker", reranker)


def test_warmup_disabled_is_noop(monkeypatch) -> None:
    embedder = _FakeWarmable()
    _set_models(monkeypatch, embedder=embedder, reranker=None, enabled=False)

    composition.warm_search_models()

    assert embedder.calls == 0


def test_warmup_without_embedder_is_noop(monkeypatch) -> None:
    _set_models(monkeypatch, embedder=None, reranker=None)

    composition.warm_search_models()


def test_warmup_loads_embedder(monkeypatch) -> None:
    embedder = _FakeWarmable()
    _set_models(monkeypatch, embedder=embedder, reranker=None)

    composition.warm_search_models()

    assert embedder.calls == 1


def test_warmup_loads_embedder_and_reranker(monkeypatch) -> None:
    embedder = _FakeWarmable()
    reranker = _FakeWarmable()
    _set_models(monkeypatch, embedder=embedder, reranker=reranker)

    composition.warm_search_models()

    assert embedder.calls == 1
    assert reranker.calls == 1


def test_warmup_failure_is_swallowed(monkeypatch) -> None:
    embedder = _FakeWarmable(fail=True)
    reranker = _FakeWarmable()
    _set_models(monkeypatch, embedder=embedder, reranker=reranker)

    composition.warm_search_models()

    assert embedder.calls == 1
    assert reranker.calls == 1
