from typer.testing import CliRunner

from cli import app
from cli.commands import pipeline

runner = CliRunner()


def test_pipeline_run_success(monkeypatch) -> None:
    events = [
        {"stage": "starting", "total_files": 1, "total_bytes": 100},
        {
            "stage": "splitting",
            "file": "Mail/All Mail.mbox",
            "processed": 2,
            "created": 2,
            "reused": 0,
            "failed": 0,
            "processed_bytes": 100,
        },
        {"stage": "done", "processed": 2, "created": 2, "reused": 0, "failed": 0},
    ]
    monkeypatch.setattr(
        pipeline.client, "stream_pipeline", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["pipeline", "run", "imp-1"])

    assert result.exit_code == 0
    assert "Pipeline complete" in result.stdout
    assert "Created:   2" in result.stdout


def test_pipeline_run_failed_exits_nonzero(monkeypatch) -> None:
    events = [{"stage": "done", "processed": 2, "created": 1, "reused": 0, "failed": 1}]
    monkeypatch.setattr(
        pipeline.client, "stream_pipeline", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["pipeline", "run", "imp-1"])

    assert result.exit_code == 1


def test_pipeline_run_api_error(monkeypatch) -> None:
    def boom(import_id: str, stage: str | None = None):
        raise pipeline.ApiClientError("boom")

    monkeypatch.setattr(pipeline.client, "stream_pipeline", boom)

    result = runner.invoke(app, ["pipeline", "run", "imp-1"])

    assert result.exit_code == 1
    assert "Failed to run pipeline" in result.stderr


def test_pipeline_run_json_mode(monkeypatch) -> None:
    events = [{"stage": "done", "processed": 1, "created": 1, "reused": 0, "failed": 0}]
    monkeypatch.setattr(
        pipeline.client, "stream_pipeline", lambda import_id, stage=None: iter(events)
    )

    result = runner.invoke(app, ["--json", "pipeline", "run", "imp-1"])

    assert result.exit_code == 0
    assert '"stage"' in result.stdout
