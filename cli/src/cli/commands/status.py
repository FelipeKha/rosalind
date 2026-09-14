import typer

from cli import client


def status() -> None:
    """Show the status of the Rosalind backend."""
    try:
        health = client.get_health()
    except client.ApiClientError as exc:
        typer.echo(f"Backend: unreachable ({exc})", err=True)
        raise typer.Exit(code=1) from exc

    if health.get("status") == "ok":
        typer.echo("Backend: healthy")
    else:
        typer.echo(f"Backend: unexpected status {health!r}", err=True)
        raise typer.Exit(code=1)
