from typing import Any

from typer.testing import CliRunner

from cli import app
from cli.commands import index

runner = CliRunner()


def _patch_stream(monkeypatch, events: list[dict], record: dict | None = None):
    def fake(import_id: str, stage=None, self_email=None):
        if record is not None:
            record["self_email"] = self_email
        return iter(events)

    monkeypatch.setattr(index.client, "stream_index", fake)


def _no_prompt(monkeypatch) -> None:
    monkeypatch.setattr(index, "_resolve_self_email", lambda *a, **k: None)


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
    _no_prompt(monkeypatch)
    _patch_stream(monkeypatch, events)

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
    _no_prompt(monkeypatch)
    _patch_stream(monkeypatch, events)

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 1


def test_index_api_error(monkeypatch) -> None:
    def boom(import_id: str, stage=None, self_email=None):
        raise index.ApiClientError("boom")

    _no_prompt(monkeypatch)
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
    _no_prompt(monkeypatch)
    _patch_stream(monkeypatch, events)

    result = runner.invoke(app, ["--json", "index", "imp-1"])

    assert result.exit_code == 0
    assert '"stage"' in result.stdout


def _mbox_detail() -> dict[str, Any]:
    return {"files": [{"path": "Mail/All Mail.mbox", "format": "mbox"}]}


def test_index_prompts_for_mbox_and_defaults_to_account_email(monkeypatch) -> None:
    recorded: dict = {}
    monkeypatch.setattr(index, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        index.import_client, "get_import", lambda import_id: _mbox_detail()
    )
    monkeypatch.setattr(
        index.account_client, "whoami", lambda: {"email": "me@example.com"}
    )
    _patch_stream(monkeypatch, [], record=recorded)

    result = runner.invoke(app, ["index", "imp-1"], input="\n")

    assert result.exit_code == 0
    assert recorded["self_email"] == "me@example.com"


def test_index_prompt_accepts_typed_email(monkeypatch) -> None:
    recorded: dict = {}
    monkeypatch.setattr(index, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        index.import_client, "get_import", lambda import_id: _mbox_detail()
    )
    monkeypatch.setattr(
        index.account_client, "whoami", lambda: {"email": "me@example.com"}
    )
    _patch_stream(monkeypatch, [], record=recorded)

    result = runner.invoke(app, ["index", "imp-1"], input="other@example.com\n")

    assert result.exit_code == 0
    assert recorded["self_email"] == "other@example.com"


def test_index_self_email_skips_prompt_and_fetch(monkeypatch) -> None:
    recorded: dict = {}

    def boom(import_id: str):
        raise AssertionError("should not fetch the import when --self-email is given")

    monkeypatch.setattr(index.import_client, "get_import", boom)
    _patch_stream(monkeypatch, [], record=recorded)

    result = runner.invoke(app, ["index", "imp-1", "--self-email", "typed@example.com"])

    assert result.exit_code == 0
    assert recorded["self_email"] == "typed@example.com"


def test_index_noninteractive_mbox_requires_self_email(monkeypatch) -> None:
    monkeypatch.setattr(index, "_is_interactive", lambda: False)
    monkeypatch.setattr(
        index.import_client, "get_import", lambda import_id: _mbox_detail()
    )
    called = False

    def fake(import_id: str, stage=None, self_email=None):
        nonlocal called
        called = True
        return iter([])

    monkeypatch.setattr(index.client, "stream_index", fake)

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 1
    assert "--self-email" in result.stderr
    assert called is False


def test_index_non_mbox_does_not_prompt(monkeypatch) -> None:
    recorded: dict = {}
    monkeypatch.setattr(index, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        index.import_client,
        "get_import",
        lambda import_id: {"files": [{"path": "Contacts/x.json", "format": "json"}]},
    )
    _patch_stream(monkeypatch, [], record=recorded)

    result = runner.invoke(app, ["index", "imp-1"])

    assert result.exit_code == 0
    assert recorded["self_email"] is None


def test_index_non_canonicalize_stage_does_not_fetch(monkeypatch) -> None:
    recorded: dict = {}

    def boom(import_id: str):
        raise AssertionError("split-only run needs no import lookup")

    monkeypatch.setattr(index.import_client, "get_import", boom)
    _patch_stream(monkeypatch, [], record=recorded)

    result = runner.invoke(app, ["index", "imp-1", "--stage", "split"])

    assert result.exit_code == 0
    assert recorded["self_email"] is None
