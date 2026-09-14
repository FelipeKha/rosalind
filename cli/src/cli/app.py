import typer

from cli import commands

app = typer.Typer()


@app.callback()
def _root() -> None:
    """Rosalind personal-data warehouse client."""


commands.register(app)


def main() -> None:
    app()
