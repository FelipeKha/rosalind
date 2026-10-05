import random
from datetime import UTC, datetime, timedelta

from rosalind.domain.email.threading import ThreadEdge, compute_thread_roots

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _edge(
    message_id: str,
    *,
    in_reply_to: str | None = None,
    references: tuple[str, ...] = (),
    offset: int = 0,
) -> ThreadEdge:
    return ThreadEdge(
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        occurred_at=T0 + timedelta(seconds=offset),
    )


def _roots(edges: list[ThreadEdge]) -> dict[str, str]:
    return compute_thread_roots(edges)


def test_linear_chain_single_root() -> None:
    edges = [
        _edge("a"),
        _edge("b", in_reply_to="a", references=("a",), offset=1),
        _edge("c", in_reply_to="b", references=("a", "b"), offset=2),
        _edge("d", in_reply_to="c", references=("a", "b", "c"), offset=3),
    ]
    assert _roots(edges) == {"a": "a", "b": "a", "c": "a", "d": "a"}


def test_reply_before_root_keys_on_missing_ancestor() -> None:
    assert _roots([_edge("m", in_reply_to="root@x", references=("root@x",))]) == {
        "m": "root@x"
    }


def test_truncated_references_walk_to_true_root() -> None:
    edges = [
        _edge("a", in_reply_to="r", references=("r",)),
        _edge("m", references=("a",), offset=1),
    ]
    assert _roots(edges) == {"a": "r", "m": "r"}


def test_in_reply_to_only_and_references_only() -> None:
    assert _roots([_edge("m1", in_reply_to="x")]) == {"m1": "x"}
    assert _roots([_edge("m2", references=("y",))]) == {"m2": "y"}


def test_no_parent_is_self_root() -> None:
    assert _roots([_edge("m")]) == {"m": "m"}


def test_self_reference_and_duplicates_ignored() -> None:
    edges = [_edge("m", references=("x", "x", "m", "y", "y"))]
    assert _roots(edges) == {"m": "x"}


def test_known_ancestor_with_missing_middle() -> None:
    # B is absent; C references [A, B]. B becomes a placeholder with parent A.
    edges = [_edge("a"), _edge("c", references=("a", "b"), offset=1)]
    assert _roots(edges) == {"a": "a", "c": "a"}


def test_siblings_with_different_missing_parents_share_earliest_reference() -> None:
    edges = [
        _edge("m1", references=("a", "b")),
        _edge("m2", references=("a", "c"), offset=1),
    ]
    assert _roots(edges) == {"m1": "a", "m2": "a"}


def test_references_bridge_two_separate_threads() -> None:
    edges = [
        _edge("x"),
        _edge("z", offset=1),
        _edge("m", references=("x", "z"), offset=2),
    ]
    assert _roots(edges) == {"x": "x", "z": "x", "m": "x"}


def test_conflicting_parent_claims_earliest_wins() -> None:
    # M (earlier) implies N's parent is P2 via References; N (later) claims P1.
    edges = [
        _edge("p1"),
        _edge("p2", offset=1),
        _edge("m", references=("p2", "n"), offset=2),
        _edge("n", in_reply_to="p1", offset=3),
    ]
    assert _roots(edges) == {"p1": "p1", "p2": "p2", "m": "p2", "n": "p2"}


def test_cyclic_reference_terminates_deterministically() -> None:
    edges = [
        _edge("a", in_reply_to="b"),
        _edge("b", in_reply_to="a", offset=1),
    ]
    roots = _roots(edges)
    assert roots["a"] == roots["b"]


def test_shuffled_input_gives_identical_roots() -> None:
    edges = [
        _edge("a"),
        _edge("b", in_reply_to="a", references=("a",), offset=1),
        _edge("c", in_reply_to="b", references=("a", "b"), offset=2),
        _edge("d", in_reply_to="c", references=("a", "b", "c"), offset=3),
        _edge("e", references=("d",), offset=4),
    ]
    expected = _roots(edges)
    for _ in range(20):
        shuffled = list(edges)
        random.Random(42).shuffle(shuffled)
        assert _roots(shuffled) == expected


def test_long_chain_is_iterative() -> None:
    count = 5000
    edges = [_edge("m0")]
    for i in range(1, count):
        edges.append(_edge(f"m{i}", in_reply_to=f"m{i - 1}", offset=i))
    roots = _roots(edges)
    assert roots[f"m{count - 1}"] == "m0"
    assert len(set(roots.values())) == 1
