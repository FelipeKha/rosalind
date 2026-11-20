"""`rosalind policy ...` commands.

Thin HTTP client over the policy service. No interpretation or policy logic
lives in the CLI.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import policy as client
from cli.output import json as json_output

policy_app = typer.Typer(help="Create and manage privacy policies.")


@policy_app.command("models")
def models() -> None:
    """List prompt-parsing models allowed by the service."""
    try:
        response = client.list_models()
    except ApiClientError as exc:
        _fail("list models", exc)

    if output.json_mode:
        json_output.render_json(response)
        return
    items = response.get("models") or []
    if not items:
        typer.echo("No models configured.")
        return
    for item in items:
        marker = " (default)" if item.get("is_default") else ""
        quant = item.get("quantization") or "unknown quantization"
        state = "" if item.get("enabled", True) else " [disabled]"
        typer.echo(f"{item['name']}: {item['model']} ({quant}){marker}{state}")


@policy_app.command("create")
def create(
    prompt: Annotated[str, typer.Argument(help="Natural-language policy instruction.")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Prompt-parsing model name."),
    ] = None,
) -> None:
    """Interpret a prompt into one or more policy drafts."""
    try:
        state = client.create_draft(prompt, model)
    except ApiClientError as exc:
        _fail("create draft", exc)

    if output.json_mode:
        json_output.render_json(state)
        return
    _render_draft(state, show_next_steps=True)


@policy_app.command("answer")
def answer(
    draft_id: Annotated[str, typer.Argument()],
    constraint_index: Annotated[int, typer.Argument()],
    option_id: Annotated[str, typer.Argument()],
) -> None:
    """Answer a clarification question for one constraint."""
    try:
        state = client.answer(draft_id, constraint_index, option_id)
    except ApiClientError as exc:
        _fail("answer clarification", exc)

    if output.json_mode:
        json_output.render_json(state)
        return
    _render_draft(state, show_next_steps=True)


@policy_app.command("confirm")
def confirm(
    draft_id: Annotated[str, typer.Argument()],
    constraint: Annotated[
        list[int] | None,
        typer.Option(
            "--constraint",
            "-c",
            help="Constraint index to confirm (repeatable). Defaults to all ready.",
        ),
    ] = None,
) -> None:
    """Confirm ready constraints and persist them."""
    try:
        response = client.confirm(draft_id, constraint)
    except ApiClientError as exc:
        _fail("confirm draft", exc)

    if output.json_mode:
        json_output.render_json(response)
        return
    policies = response.get("policies") or []
    if not policies:
        typer.echo("Nothing confirmed.")
        return
    for policy in policies:
        typer.echo(
            f"Confirmed {policy['policy_id']} "
            f"(rev {policy['revision']}, {policy['status']}): {policy['title']}"
        )
    typer.echo("Enforcement is not active yet. These rules are recorded only.")


@policy_app.command("delete-draft")
def delete_draft(draft_id: Annotated[str, typer.Argument()]) -> None:
    """Abandon a draft without persisting anything."""
    try:
        client.delete_draft(draft_id)
    except ApiClientError as exc:
        _fail("delete draft", exc)
    typer.echo(f"Deleted draft {draft_id}.")


@policy_app.command("list")
def list_policies() -> None:
    """List confirmed policies."""
    try:
        policies = client.list_policies()
    except ApiClientError as exc:
        _fail("list policies", exc)

    if output.json_mode:
        json_output.render_json(policies)
        return
    if not policies:
        typer.echo("No policies.")
        return
    for policy in policies:
        typer.echo(
            f"{policy['policy_id']}  {policy['status']:<20} "
            f"{policy['policy_type']:<16} {policy['title']}"
        )


@policy_app.command("show")
def show(policy_id: Annotated[str, typer.Argument()]) -> None:
    """Show a policy, its spec and the owner's original instruction."""
    try:
        policy = client.get_policy(policy_id)
    except ApiClientError as exc:
        _fail("show policy", exc)

    if output.json_mode:
        json_output.render_json(policy)
        return
    typer.echo(f"Policy:   {policy['policy_id']} (rev {policy['revision']})")
    typer.echo(f"Type:     {policy['policy_type']}")
    typer.echo(f"Status:   {policy['status']}")
    typer.echo(f"Principal:{policy['principal_kind']}")
    source = policy.get("source") or {}
    if source.get("prompt"):
        typer.echo(f"You said: {source['prompt']}")
    if source.get("confirmed_description"):
        typer.echo("Preview:  " + source["confirmed_description"])
    typer.echo("Spec:")
    json_output.render_json(policy["spec"])


@policy_app.command("pause")
def pause(policy_id: Annotated[str, typer.Argument()]) -> None:
    """Pause a policy."""
    _set_status(policy_id, "pause")


@policy_app.command("resume")
def resume(policy_id: Annotated[str, typer.Argument()]) -> None:
    """Resume a paused policy."""
    _set_status(policy_id, "resume")


@policy_app.command("revoke")
def revoke(policy_id: Annotated[str, typer.Argument()]) -> None:
    """Revoke a policy."""
    _set_status(policy_id, "revoke")


def _set_status(policy_id: str, action: str) -> None:
    try:
        policy = client.set_status(policy_id, action)
    except ApiClientError as exc:
        _fail(action, exc)
    if output.json_mode:
        json_output.render_json(policy)
        return
    typer.echo(f"{policy['policy_id']} is now {policy['status']}.")


def _render_draft(state: dict[str, Any], *, show_next_steps: bool) -> None:
    typer.echo(f"Draft {state['draft_id']} (model {state['model']})")
    typer.echo(f"Interpreter {state['interpreter_version']}")
    constraints = state.get("constraints") or []
    if not constraints:
        typer.echo("No constraints were extracted. Try a more specific prompt.")
        return

    for item in constraints:
        typer.echo("")
        typer.echo(f"[{item['index']}] {item['state']}")
        if item.get("kind"):
            typer.echo(f"    kind: {item['kind']}")
        if item.get("preview"):
            typer.echo(f"    {item['preview']}")
        if item.get("error"):
            typer.echo(f"    reason: {item['error']}")
        for part in item.get("unsupported_parts") or []:
            typer.echo(f"    unsupported: {part}")
        for note in item.get("assumptions") or []:
            typer.echo(f"    assumption: {note}")
        for note in item.get("resolution_notes") or []:
            typer.echo(f"    resolution: {note}")
        clarification = item.get("clarification")
        if clarification:
            typer.echo(f"    question: {clarification['text']}")
            for option in clarification.get("options") or []:
                detail = f" — {option['detail']}" if option.get("detail") else ""
                typer.echo(f"      {option['id']}: {option['label']}{detail}")

    if not show_next_steps:
        return
    typer.echo("")
    if any(item["state"] == "needs_clarification" for item in constraints):
        typer.echo(
            "Answer clarifications with: "
            f"rosalind policy answer {state['draft_id']} <index> <option-id>"
        )
    if any(item["state"] == "ready" for item in constraints):
        typer.echo(f"Confirm with: rosalind policy confirm {state['draft_id']}")
    typer.echo("Nothing is persisted until you confirm. Enforcement is not active yet.")


def _fail(action: str, exc: ApiClientError) -> None:
    typer.echo(f"Failed to {action}: {exc}", err=True)
    raise typer.Exit(code=1) from exc
