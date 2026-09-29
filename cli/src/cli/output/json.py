"""Machine-readable JSON output."""

from __future__ import annotations

import json
from typing import Any

import typer


def render_json(data: Any) -> None:
    typer.echo(json.dumps(data, default=str, indent=2))
