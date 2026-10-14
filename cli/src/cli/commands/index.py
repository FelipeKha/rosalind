"""`rosalind index` command.

The offline pipeline turns raw archive files into searchable data. It currently
runs only the record-split stage; later stages (parse, canonicalize, enrich,
chunk, embed) will slot in behind the same entry point.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import account as account_client
from cli.client import imports as import_client
from cli.client import processing as client
from cli.commands import _format

_CANONICALIZE_STAGE = "canonicalize"


def index(
    import_id: str,
    stage: str | None = typer.Option(
        None,
        "--stage",
        help="Run a single index stage (split, canonicalize, reconcile, enrich, attachments, chunk, embed).",
    ),
    self_email: str | None = typer.Option(
        None,
        "--self-email",
        help=(
            "Email address to treat as yours when computing message direction. "
            "Required when indexing an mbox without an interactive terminal."
        ),
    ),
) -> None:
    """Build the searchable index for an import."""
    try:
        email = _resolve_self_email(import_id, stage, self_email)
    except ApiClientError as exc:
        typer.echo(f"Failed to run index: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    failed = 0
    last: dict[str, Any] | None = None
    try:
        events = client.stream_index(import_id, stage=stage, self_email=email)
        for event in events:
            last = event
            failed = int(event.get("failed", failed))
            _render_event(event)
    except ApiClientError as exc:
        typer.echo(f"Failed to run index: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if last is None:
        return

    if output.json_mode:
        return

    if last.get("phase") == "error":
        typer.echo(f"Index error: {last.get('message')}", err=True)
        raise typer.Exit(code=1)

    typer.echo("")
    typer.echo("Index complete")
    typer.echo(f"  Processed: {last.get('processed', 0)} messages")
    typer.echo(f"  Created:   {last.get('created', 0)}")
    typer.echo(f"  Reused:    {last.get('reused', 0)}")
    typer.echo(f"  Failed:    {failed}")
    if failed:
        raise typer.Exit(code=1)


def _is_interactive() -> bool:
    """True when it is safe to prompt the user for input."""
    return not output.json_mode and sys.stdin.isatty() and sys.stdout.isatty()


def _is_mbox(file: dict[str, Any]) -> bool:
    path = (file.get("path") or "").lower()
    return file.get("format") == "mbox" or path.endswith(".mbox")


def _account_email() -> str | None:
    """Best-effort default from the signed-in account (``/me``)."""
    try:
        profile = account_client.whoami()
    except ApiClientError:
        return None
    email = profile.get("email") or profile.get("preferred_username")
    return email if isinstance(email, str) and "@" in email else None


def _resolve_self_email(
    import_id: str, stage: str | None, self_email: str | None
) -> str | None:
    """Resolve the per-run self email, prompting for mbox imports when needed.

    Direction can only be computed for an mbox import when we know which
    address is the account owner's. An explicit ``--self-email`` always wins;
    otherwise an interactive run prompts (defaulting to the account email) and
    a non-interactive run fails.
    """
    if self_email and self_email.strip():
        return self_email.strip()

    if stage not in (None, _CANONICALIZE_STAGE):
        return None

    detail = import_client.get_import(import_id)
    files = detail.get("files") or []
    if not any(_is_mbox(file) for file in files):
        return None

    if not _is_interactive():
        typer.echo(
            "This import contains an mbox file; re-run with --self-email <address>.",
            err=True,
        )
        raise typer.Exit(code=1)

    default = _account_email()
    while True:
        if default:
            email = typer.prompt("Email address to treat as yours", default=default)
        else:
            email = typer.prompt("Email address to treat as yours")
        email = email.strip()
        if email and "@" in email:
            return email
        typer.echo("Please enter a valid email address.", err=True)


def _render_event(event: dict[str, Any]) -> None:
    stage = event.get("stage")
    phase = event.get("phase")

    if output.json_mode:
        typer.echo(json.dumps(event))
        return

    if stage == "split":
        if phase == "start":
            total_files = int(event.get("total_files", 0))
            total_bytes = int(event.get("total_bytes", 0))
            typer.echo(
                f"Splitting {total_files} mbox file(s) "
                f"({_format.human_size(total_bytes)})"
            )
        elif phase == "progress":
            typer.echo(
                f"  {event.get('file')}: {event.get('processed', 0)} messages "
                f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
                f"· {event.get('failed', 0)} failed"
            )
        elif phase == "done":
            typer.echo(
                f"Split: {event.get('processed', 0)} messages "
                f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
                f"· {event.get('failed', 0)} failed"
            )
    elif stage == "canonicalize":
        if phase == "start":
            typer.echo("Canonicalizing...")
        elif phase == "progress":
            typer.echo(
                f"  canonicalizing: {event.get('processed', 0)} records "
                f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
                f"· {event.get('failed', 0)} failed"
            )
        elif phase == "done":
            typer.echo(
                f"Canonicalized: {event.get('processed', 0)} messages "
                f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
                f"· {event.get('failed', 0)} failed"
            )
        elif phase == "error":
            typer.echo(f"Error: {event.get('message')}", err=True)
    elif stage == "reconcile":
        if phase == "start":
            typer.echo("Reconciling threads...")
        elif phase == "done":
            details = event.get("details") or {}
            typer.echo(
                "Reconciled threads: "
                f"{details.get('messages_reassigned', 0)} reassigned · "
                f"{details.get('threads_created', 0)} created · "
                f"{details.get('threads_removed', 0)} removed"
            )
    elif stage == "enrich":
        if phase == "start":
            typer.echo("Enriching...")
        elif phase == "done":
            details = event.get("details") or {}
            typer.echo(
                "Enriched: "
                f"{details.get('done', 0)} done · "
                f"{details.get('empty', 0)} empty · "
                f"{details.get('failed', 0)} failed"
            )
    elif stage == "attachments":
        if phase == "start":
            typer.echo("Extracting attachment text...")
        elif phase == "done":
            details = event.get("details") or {}
            typer.echo(
                "Attachments extracted: "
                f"{details.get('done', 0)} done · "
                f"{details.get('failed', 0)} failed · "
                f"{details.get('needs_ocr', 0)} needs_ocr"
            )
    elif stage == "chunk":
        if phase == "start":
            typer.echo("Chunking derived text...")
        elif phase == "done":
            details = event.get("details") or {}
            typer.echo(
                "Chunked: "
                f"{details.get('chunks_written', 0)} written · "
                f"{details.get('chunks_unchanged', 0)} unchanged · "
                f"{details.get('skipped_not_ready', 0)} skipped"
            )
    elif stage == "embed":
        if phase == "start":
            typer.echo("Embedding chunks...")
        elif phase == "done":
            details = event.get("details") or {}
            typer.echo(
                "Embedded: "
                f"{details.get('embedded', 0)} new · "
                f"{details.get('reused', 0)} reused · "
                f"{details.get('skipped_not_embeddable', 0)} skipped · "
                f"{details.get('failed', 0)} failed"
            )
        elif phase == "blocked":
            typer.echo(f"Embedding blocked: {event.get('message')}")
