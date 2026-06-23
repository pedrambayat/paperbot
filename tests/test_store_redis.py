import json

import httpx

from paperbot.models import PaperKind, PaperRef, PaperSummary, RetrievalMode, RetrievedPaper
from paperbot.store_redis import RedisSummaryStore

BASE = "https://fake-upstash.example.com"
TOKEN = "tkn"


def _fake_upstash():
    """An httpx MockTransport that emulates Upstash REST GET/SET on an in-memory dict."""
    data: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        command = json.loads(request.content)
        op = command[0].upper()
        if op == "SET":
            data[command[1]] = command[2]
            return httpx.Response(200, json={"result": "OK"})
        if op == "GET":
            return httpx.Response(200, json={"result": data.get(command[1])})
        return httpx.Response(400, json={"error": f"unsupported {op}"})

    return httpx.Client(transport=httpx.MockTransport(handler)), data


def _store():
    client, data = _fake_upstash()
    return RedisSummaryStore(BASE, TOKEN, client=client), data


def _paper():
    ref = PaperRef(PaperKind.ARXIV, "2401.01234", "https://arxiv.org/abs/2401.01234")
    return RetrievedPaper(ref=ref, title="A Paper", mode=RetrievalMode.FULL_TEXT)


def _summary():
    return PaperSummary("tldr", "problem", "method", "result", "limits", "full_text")


def test_get_missing_key_returns_none():
    store, _ = _store()
    assert store.get("arxiv:2401.01234") is None


def test_save_then_get_round_trips_slack_ts():
    store, _ = _store()
    store.save(_paper(), _summary(), "C123", "1700000000.000100")
    record = store.get("arxiv:2401.01234")
    assert record is not None
    assert record["slack_ts"] == "1700000000.000100"


def test_save_writes_namespaced_key():
    store, data = _store()
    store.save(_paper(), _summary(), "C123", "1.1")
    assert any(key.endswith("arxiv:2401.01234") for key in data)
    assert all(key.startswith("paperbot:") for key in data)
