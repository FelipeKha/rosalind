"""`rosalind search` command.

Thin HTTP client over the backend's ``POST /search`` endpoint: it maps CLI
inputs onto the search request and renders the response. No retrieval logic
lives here.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import search as client
from cli.output import json as json_output
from cli.output import tables

_MIN_LIMIT = 1
_MAX_LIMIT = 25


class SearchMode(str, Enum):
    hybrid = "hybrid"
    lexical = "lexical"
    semantic = "semantic"


def search(
    query: Annotated[str | None, typer.Argument(help="Natural-language query.")] = None,
    keywords: Annotated[
        str | None,
        typer.Option("--keywords", "-k", help="Exact-match terms for keyword search."),
    ] = None,
    sender: Annotated[
        list[str] | None,
        typer.Option(
            "--sender", "-s", help="Sender address or entity id (repeatable)."
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Inclusive lower date bound (YYYY-MM-DD)."),
    ] = None,
    before: Annotated[
        str | None,
        typer.Option("--before", help="Exclusive upper date bound (YYYY-MM-DD)."),
    ] = None,
    has_attachment: Annotated[
        bool | None,
        typer.Option(
            "--has-attachment/--no-attachment",
            help="Restrict to messages with (or without) attachments.",
        ),
    ] = None,
    mode: Annotated[
        SearchMode,
        typer.Option("--mode", help="Retrieval mode."),
    ] = SearchMode.hybrid,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum number of results (1-25)."),
    ] = 10,
    cursor: Annotated[
        str | None,
        typer.Option("--cursor", help="Opaque pagination cursor from a prior search."),
    ] = None,
) -> None:
    """Search email by query, keywords, and filters."""
    date_from = _parse_date("--since", since)
    date_before = _parse_date("--before", before)
    if not _MIN_LIMIT <= limit <= _MAX_LIMIT:
        typer.echo(f"--limit must be between {_MIN_LIMIT} and {_MAX_LIMIT}.", err=True)
        raise typer.Exit(code=2)

    try:
        response = client.search(
            query,
            keywords=keywords,
            sender=sender,
            since=date_from,
            before=date_before,
            has_attachment=has_attachment,
            mode=mode.value,
            limit=limit,
            cursor=cursor,
        )
    except ApiClientError as exc:
        typer.echo(f"Failed to search: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(response)
        return

    _render_warnings(response)
    _render(response)


def _parse_date(flag: str, value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        typer.echo(f"{flag}: invalid date {value!r} (expected YYYY-MM-DD).", err=True)
        raise typer.Exit(code=2) from exc


def _render_warnings(response: dict[str, Any]) -> None:
    for warning in response.get("warnings") or []:
        typer.echo(f"warning: {warning.get('message')}", err=True)


def _render(response: dict[str, Any]) -> None:
    if response.get("short_circuit"):
        explanation = response.get("explanation") or response["short_circuit"]
        typer.echo(explanation)
        return

    results = response.get("results") or []
    if not results:
        typer.echo("No results found.")
        return

    headers = ("DATE", "FROM", "SUBJECT", "SCORE")
    rows = [
        (
            str(item.get("date") or "")[:10],
            str(item.get("sender") or "-"),
            str(item.get("subject") or "-"),
            _format_score(item.get("score")),
        )
        for item in results
    ]
    tables.render_table(headers, rows)

    for item in results:
        snippet = item.get("snippet")
        if snippet:
            typer.echo("")
            for line in str(snippet).splitlines():
                typer.echo(f"  {line}")

    cursor = response.get("next_cursor")
    if cursor:
        typer.echo("")
        typer.echo(f"Next cursor: {cursor}")


def _format_score(score: Any) -> str:
    if score is None:
        return "-"
    return f"{score:.3f}"
