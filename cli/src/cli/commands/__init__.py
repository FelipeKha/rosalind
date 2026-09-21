import typer

from cli.commands import status
from cli.commands.import_ import import_app
from cli.commands.process import process_app
from cli.commands.query import query_app
from cli.commands.source import source_app


def register(app: typer.Typer) -> None:
    app.command()(status.status)
    app.add_typer(source_app, name="source")
    app.add_typer(import_app, name="import")
    app.add_typer(process_app, name="process")
    app.add_typer(query_app, name="query")
