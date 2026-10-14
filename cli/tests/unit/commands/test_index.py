from typer.testing import CliRunner

from cli import app
from cli.commands import index

runner = CliRunner()


def test_index_success(monkeypatch) -> None:
    events = [
        {"stage": "split", "phase": "start", "total_files": 1, "total_bytes": 100},
        {
            "stage": "split",
            "phase": "progress",
            "file": "Mail/All Mail.mbox",
            "processed": 2,
            "created": 2,
            "reused": 0,
            "failed": 0,
            "processed_bytes": 100,
        },
        {
            "stage": "split",
            "phase": "done",
            "processed": 2,
            "created": 2,
            "reused": 0,
            "failed": 0,
        },
    ]
    monkeypatch.setattr(
        index.client, "stream_index", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 0
    assert "Index complete" in result.stdout
    assert "Created:   2" in result.stdout


def test_index_failed_exits_nonzero(monkeypatch) -> None:
    events = [
        {
            "stage": "split",
            "phase": "done",
            "processed": 2,
            "created": 1,
            "reused": 0,
            "failed": 1,
        }
    ]
    monkeypatch.setattr(
        index.client, "stream_index", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 1


def test_index_api_error(monkeypatch) -> None:
    def boom(import_id: str, stage: str | None = None):
        raise index.ApiClientError("boom")

    monkeypatch.setattr(index.client, "stream_index", boom)

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 1
    assert "Failed to run index" in result.stderr


def test_index_json_mode(monkeypatch) -> None:
    events = [
        {
            "stage": "split",
            "phase": "done",
            "processed": 1,
            "created": 1,
            "reused": 0,
            "failed": 0,
        }
    ]
    monkeypatch.setattr(
        index.client, "stream_index", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["--json", "index", "imp-1"])

    assert result.exit_code == 0
    assert '"stage"' in result.stdout
