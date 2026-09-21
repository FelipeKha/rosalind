from collections.abc import Iterator

import pytest

from cli import output


@pytest.fixture(autouse=True)
def _reset_output_mode() -> Iterator[None]:
    output.json_mode = False
    yield
    output.json_mode = False
