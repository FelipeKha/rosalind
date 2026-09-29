"""`rosalind auth ...` commands."""

from __future__ import annotations

import webbrowser
from typing import Annotated

import typer

from cli.client import auth
from cli.storage.credentials import CredentialStore

auth_app = typer.Typer(help="Authenticate with the Rosalind identity provider.")


def _complete_device_flow(signup: bool, open_browser: bool) -> None:
    store = CredentialStore()
    try:
        device = auth.start_device_flow()
    except auth.AuthError as exc:
        typer.echo(f"Failed to start authentication: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    verification_uri = device.get("verification_uri_complete") or device.get(
        "verification_uri"
    )
    user_code = device.get("user_code")
    interval = int(device.get("interval", 5))
    expires_in = int(device.get("expires_in", 600))

    if signup:
        typer.echo("Create your account on the opened page, then approve the sign-in.")
    typer.echo("Visit this URL to authorize Rosalind:")
    typer.echo(verification_uri)
    if user_code:
        typer.echo(f"Enter code: {user_code}")
    if open_browser and verification_uri:
        webbrowser.open(verification_uri)

    try:
        credentials = auth.poll_device_token(
            device["device_code"], interval, timeout=float(expires_in)
        )
    except auth.AuthError as exc:
        typer.echo(f"Authentication failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    store.save(credentials)
    typer.echo("Signed in.")


@auth_app.command("sign-in")
def sign_in(
    open_browser: Annotated[
        bool,
        typer.Option(
            "--browser/--no-browser",
            help="Open the authorization URL in a browser.",
        ),
    ] = True,
) -> None:
    """Sign in to Rosalind."""
    _complete_device_flow(signup=False, open_browser=open_browser)


@auth_app.command("sign-up")
def sign_up(
    open_browser: Annotated[
        bool,
        typer.Option(
            "--browser/--no-browser",
            help="Open the authorization URL in a browser.",
        ),
    ] = True,
) -> None:
    """Create a Rosalind account and sign in."""
    _complete_device_flow(signup=True, open_browser=open_browser)


@auth_app.command("sign-out")
def sign_out() -> None:
    """Sign out of Rosalind, revoking stored tokens."""
    store = CredentialStore()
    credentials = store.load()
    if credentials is not None:
        if credentials.refresh_token:
            auth.revoke(credentials.refresh_token)
        if credentials.access_token:
            auth.revoke(credentials.access_token)
    store.clear()
    typer.echo("Signed out.")
