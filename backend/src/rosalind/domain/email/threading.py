"""Thread reconciliation: map messages to conversation roots.

A pure, side-effect-free algorithm (JWZ-style threading) that turns each
message's reply chain into a canonical thread root. It builds placeholder nodes
for referenced-but-absent messages so a message you were looped into — whose
ancestors aren't in the archive — still lands in the same thread as its
siblings, rather than keying each thread on the immediate (missing) parent.

Determinism rules:
- edges are processed in ``(occurred_at, message_id)`` order;
- the first parent claim for a node wins;
- a link that would create a cycle is refused at construction time (union-find
  keeps the graph a forest).

The root walk is iterative with path compression, so very long threads never
hit the recursion limit and construction is ~O(n α(n)).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ThreadEdge:
    """One message's contribution to the reply graph."""

    message_id: str
    in_reply_to: str | None
    references: tuple[str, ...]
    occurred_at: datetime


def compute_thread_roots(edges: list[ThreadEdge]) -> dict[str, str]:
    """Return ``{known message_id: root_message_id}`` for each message.

    The root may be a placeholder (a referenced id that is not itself a known
    message). Only known messages appear as keys.
    """
    known = {edge.message_id for edge in edges}
    ordered = sorted(edges, key=lambda edge: (edge.occurred_at, edge.message_id))

    parent: dict[str, str] = {}
    forest: dict[str, str] = {}

    for edge in ordered:
        references = _normalize_references(edge)
        for index in range(1, len(references)):
            _link(parent, forest, references[index], references[index - 1])
        own_parent = edge.in_reply_to or (references[-1] if references else None)
        _link(parent, forest, edge.message_id, own_parent)

    memo: dict[str, str] = {}
    return {message_id: _root(parent, memo, message_id) for message_id in sorted(known)}


def _normalize_references(edge: ThreadEdge) -> list[str]:
    """Drop duplicates, self-references, and empty entries, preserving order."""
    result: list[str] = []
    seen: set[str] = set()
    for reference in edge.references:
        reference = reference.strip()
        if not reference or reference == edge.message_id or reference in seen:
            continue
        seen.add(reference)
        result.append(reference)
    return result


def _link(
    parent: dict[str, str],
    forest: dict[str, str],
    child: str,
    proposed: str | None,
) -> None:
    if proposed is None or child == proposed:
        return
    if child in parent:
        return  # first claim wins
    if not _union(forest, child, proposed):
        return  # would create a cycle
    parent[child] = proposed


def _union(forest: dict[str, str], a: str, b: str) -> bool:
    """Union-find; returns False when ``a`` and ``b`` are already connected."""
    root_a = _find(forest, a)
    root_b = _find(forest, b)
    if root_a == root_b:
        return False
    forest[root_b] = root_a
    return True


def _find(forest: dict[str, str], node: str) -> str:
    if node not in forest:
        forest[node] = node
        return node
    root = node
    while forest[root] != root:
        root = forest[root]
    current = node
    while forest[current] != current:
        nxt = forest[current]
        forest[current] = root
        current = nxt
    return root


def _root(parent: dict[str, str], memo: dict[str, str], message_id: str) -> str:
    """Iteratively walk to the root with path compression and a cycle guard."""
    if message_id in memo:
        return memo[message_id]

    path: list[str] = []
    seen: dict[str, int] = {}
    current = message_id
    result: str = message_id

    while True:
        if current in memo:
            result = memo[current]
            break
        ancestor = parent.get(current)
        if ancestor is None:
            result = current
            break
        if current in seen:
            cycle = [current, *path[seen[current] :]]
            result = min(cycle)
            break
        seen[current] = len(path)
        path.append(current)
        current = ancestor

    for node in path:
        memo[node] = result
    memo[message_id] = result
    return result
