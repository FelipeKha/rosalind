import typer

from cli.commands import status


def register(app: typer.Typer) -> None:
    app.command()(status.status)
