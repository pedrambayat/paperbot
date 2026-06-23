import json

import httpx
import pytest

from paperbot.jobs import publish_job

DEST = "https://paperbot.vercel.app/api/process"
TOKEN = "qstash-token"


def _capture():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messageId": "msg_1"})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_publish_job_posts_to_qstash_destination_with_auth_and_body():
    client, seen = _capture()
    job = {"channel": "C1", "thread_ts": "1.1", "text": "https://arxiv.org/abs/2401.01234", "files": []}
    publish_job(TOKEN, DEST, job, client=client)
    assert DEST in seen["url"]
    assert seen["url"].startswith("https://qstash.upstash.io/v2/publish/")
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["body"] == job


def test_publish_job_raises_on_qstash_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        publish_job(TOKEN, DEST, {"x": 1}, client=client)
