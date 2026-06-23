import pytest

from index import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("PAPERBOT_CHANNEL_ID", "C1")
    monkeypatch.setenv("QSTASH_CURRENT_SIGNING_KEY", "k1")
    monkeypatch.setenv("QSTASH_NEXT_SIGNING_KEY", "k2")
    return app.test_client()


def test_slack_events_rejects_bad_signature(client):
    resp = client.post(
        "/api/slack/events",
        data=b"{}",
        headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=bad"},
    )
    assert resp.status_code == 401


def test_process_rejects_bad_qstash_signature(client):
    resp = client.post("/api/process", data="{}", headers={"Upstash-Signature": "bad"})
    assert resp.status_code == 401


def test_unknown_path_is_404(client):
    assert client.post("/nope", data=b"").status_code == 404


def test_slack_events_only_allows_post(client):
    assert client.get("/api/slack/events").status_code == 405
