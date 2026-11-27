from __future__ import annotations

from cli.client import policy as client


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def get(self, path: str) -> object:
        self.calls.append(("get", path, None))
        return {}

    def post(self, path: str, *, json: object = None) -> object:
        self.calls.append(("post", path, json))
        return {}

    def delete(self, path: str) -> None:
        self.calls.append(("delete", path, None))


def test_create_draft_omits_model_when_absent(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client, "_api", lambda: fake)

    client.create_draft("Agent A can't know I have cancer", None)

    assert fake.calls == [
        (
            "post",
            "/v1/policy-drafts",
            {"prompt": "Agent A can't know I have cancer"},
        )
    ]


def test_create_draft_includes_model(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client, "_api", lambda: fake)

    client.create_draft("prompt", "qwen3.5-9b")

    assert fake.calls == [
        (
            "post",
            "/v1/policy-drafts",
            {"prompt": "prompt", "model": "qwen3.5-9b"},
        )
    ]


def test_confirm_omits_empty_indexes(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client, "_api", lambda: fake)

    client.confirm("dr_1", None)

    assert fake.calls == [
        ("post", "/v1/policy-drafts/dr_1/confirm", {}),
    ]


def test_set_status_hits_action_route(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client, "_api", lambda: fake)

    client.set_status("pol_1", "pause")

    assert fake.calls == [("post", "/v1/policies/pol_1/pause", None)]
