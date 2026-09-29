import typer

from cli import commands, output

app = typer.Typer()


@app.callback()
def _root(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of tables."
    ),
) -> None:
    """Rosalind personal-data warehouse client."""
    if json_output:
        output.enable_json()


commands.register(app)


def main() -> None:
    app()
