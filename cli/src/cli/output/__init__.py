"""Output rendering for the CLI.

Human-readable tables are the default; ``--json`` switches to machine-readable
output. The flag is set once by the root callback in ``cli.app``.
"""

from __future__ import annotations

json_mode = False


def enable_json() -> None:
    global json_mode
    json_mode = True
