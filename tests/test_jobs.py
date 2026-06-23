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


def test_publish_job_uses_custom_base_url_for_region():
    client, seen = _capture()
    publish_job(TOKEN, DEST, {"x": 1}, base_url="https://qstash-us-east-1.upstash.io", client=client)
    assert seen["url"].startswith("https://qstash-us-east-1.upstash.io/v2/publish/")
    assert DEST in seen["url"]


def test_publish_job_raises_with_status_and_body_on_error():
    # The QStash error body must be surfaced (not swallowed) so failures are debuggable.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="destination url is not valid")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError) as exc_info:
        publish_job(TOKEN, DEST, {"x": 1}, client=client)
    message = str(exc_info.value)
    assert "404" in message
    assert "destination url is not valid" in message
