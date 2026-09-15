import typer

from cli.commands import show, status
from cli.commands.import_commands import import_app


def register(app: typer.Typer) -> None:
    app.command()(status.status)
    app.add_typer(import_app, name="import")
    app.command()(show.show)
