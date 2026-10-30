from collections.abc import Iterator
from pathlib import Path

import pytest

from cli import output


@pytest.fixture(autouse=True)
def _isolated_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ROSALIND_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ROSALIND_CONFIG", raising=False)
    monkeypatch.delenv("ROSALIND_PROFILE", raising=False)


@pytest.fixture(autouse=True)
def _reset_output_mode() -> Iterator[None]:
    output.json_mode = False
    yield
    output.json_mode = False
