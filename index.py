"""Vercel entrypoint: one WSGI (Flask) app exposing the Slack webhook and the
QStash worker. Vercel detects Flask from requirements.txt, loads the ``app``
variable here, and routes every request to it; Flask dispatches by path.

The two routes are thin glue over the tested logic modules:
- POST /api/slack/events  -> verify, handshake, enqueue (ack within Slack's 3s)
- POST /api/process       -> verify QStash, dedup, retrieve, summarize, post
"""
from __future__ import annotations

import json
import os

from flask import Flask, Response, request

# Only light modules are imported at startup so the /api/slack/events ack stays
# well under Slack's 3-second deadline (a slow cold start makes Slack re-deliver,
# which causes duplicate summaries). The heavy worker deps (openai, curl_cffi,
# slack_sdk) are imported lazily inside _run_job, on the /api/process path only.
from paperbot.events import job_from_event, url_verification_challenge
from paperbot.jobs import publish_job, verify_qstash_signature
from paperbot.slack_verify import verify_slack_signature

app = Flask(__name__)


def _error(code: int, message: str) -> Response:
    return Response(json.dumps({"error": message}), status=code, mimetype="application/json")


@app.post("/api/slack/events")
def slack_events():
    body = request.get_data()
    if not verify_slack_signature(
        os.environ["SLACK_SIGNING_SECRET"],
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
        body,
    ):
        return _error(401, "bad signature")

    payload = json.loads(body or b"{}")
    challenge = url_verification_challenge(payload)
    if challenge:
        return {"challenge": challenge}

    try:
        job = job_from_event(payload, os.environ["PAPERBOT_CHANNEL_ID"])
        if job:
            publish_job(
                os.environ["QSTASH_TOKEN"],
                os.environ["PAPERBOT_PROCESS_URL"],
                job,
                base_url=os.environ.get("QSTASH_URL", "https://qstash.upstash.io"),
            )
    except Exception as exc:  # noqa: BLE001 - return 500 so Slack retries delivery
        print(f"paperbot enqueue failed: {exc}", flush=True)
        return _error(500, "enqueue failed")
    return {"ok": True}


@app.post("/api/process")
def process():
    body = request.get_data().decode("utf-8")
    if not verify_qstash_signature(
        os.environ["QSTASH_CURRENT_SIGNING_KEY"],
        os.environ["QSTASH_NEXT_SIGNING_KEY"],
        request.headers.get("Upstash-Signature", ""),
        body,
    ):
        return _error(401, "bad signature")

    _run_job(json.loads(body))
    return {"ok": True}


def _run_job(job: dict) -> None:
    # Heavy imports happen here (worker path only), not at module load.
    from slack_sdk import WebClient

    from paperbot.config import Settings
    from paperbot.core import build_summarizer, process_job
    from paperbot.retriever import PaperRetriever
    from paperbot.store_redis import RedisSummaryStore

    settings = Settings.from_env()
    store = RedisSummaryStore(
        os.environ["UPSTASH_REDIS_REST_URL"],
        os.environ["UPSTASH_REDIS_REST_TOKEN"],
    )
    process_job(
        job,
        retriever=PaperRetriever(settings.unpaywall_email),
        store=store,
        summarizer=build_summarizer(settings),
        client=WebClient(token=settings.slack_bot_token),
        bot_token=settings.slack_bot_token,
        post_failures=settings.post_failures,
    )
