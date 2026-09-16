"""`rosalind google ...` commands."""

import time
import webbrowser

import typer

from cli import client

google_app = typer.Typer(help="Connect and import data from Google.")

import_app = typer.Typer(help="Import data from Google.")


@google_app.command("connect")
def connect(
    open_browser: bool = typer.Option(
        True, "--browser/--no-browser", help="Open the authorization URL in a browser."
    ),
) -> None:
    """Authorize Rosalind to access your Google account."""
    try:
        created = client.connect_google()
    except client.ApiClientError as exc:
        typer.echo(f"Failed to start Google authorization: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    auth_url = str(created["auth_url"])
    state = str(created["state"])

    typer.echo("Authorize Rosalind by visiting this URL:")
    typer.echo(auth_url)
    if open_browser:
        webbrowser.open(auth_url)

    typer.echo("Waiting for authorization...")
    _poll_status(state)


@import_app.command("profile")
def import_profile() -> None:
    """Import your Google profile (People API) into Rosalind."""
    try:
        result = client.import_google_profile()
    except client.ApiClientError as exc:
        typer.echo(f"Failed to import Google profile: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    display = result.get("display_name") or result.get("account") or "unknown"
    typer.echo(f"Imported Google profile for {display}.")


def _poll_status(state: str, timeout: float = 120.0, interval: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = client.google_auth_status(state)
        except client.ApiClientError as exc:
            typer.echo(f"Failed to check authorization status: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        status = str(result["status"])
        if status == "connected":
            display = result.get("display_name") or "your account"
            typer.echo(f"Connected: {display}")
            return
        if status in {"expired", "not_found"}:
            typer.echo(f"Authorization failed: {status}", err=True)
            raise typer.Exit(code=1)

        if time.monotonic() >= deadline:
            typer.echo("Timed out waiting for authorization.", err=True)
            raise typer.Exit(code=1)

        time.sleep(interval)


google_app.add_typer(import_app, name="import")
