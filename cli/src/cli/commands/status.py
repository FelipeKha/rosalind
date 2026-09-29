import typer

from cli.client import ApiClientError, get_health


def status() -> None:
    """Show the status of the Rosalind backend."""
    try:
        health = get_health()
    except ApiClientError as exc:
        typer.echo(f"Backend: unreachable ({exc})", err=True)
        raise typer.Exit(code=1) from exc

    if health.get("status") == "ok":
        typer.echo("Backend: healthy")
    else:
        typer.echo(f"Backend: unexpected status {health!r}", err=True)
        raise typer.Exit(code=1)
