import os

import typer

from cli import commands, output, settings

app = typer.Typer()


@app.callback()
def _root(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of tables."
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Config profile to load (selects <config_dir>/<profile>.yaml).",
    ),
) -> None:
    """Rosalind personal-data warehouse client."""
    if profile:
        os.environ["ROSALIND_PROFILE"] = profile
    try:
        settings.get_settings()
    except ValueError as exc:
        typer.echo(f"invalid configuration: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if json_output:
        output.enable_json()


commands.register(app)


def main() -> None:
    app()
