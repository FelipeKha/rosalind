import typer

from cli.commands import status
from cli.commands.import_google import import_app


def register(app: typer.Typer) -> None:
    app.command()(status.status)
    app.add_typer(import_app, name="import")
