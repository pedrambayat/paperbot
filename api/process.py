"""Vercel function B: QStash-delivered worker that summarizes one job.

QStash calls this endpoint (with retries) after function A enqueues a job. It
verifies the QStash signature, then runs the same ``process_job`` the Socket
Mode bot uses — retrieve, summarize, post — with dedup backed by Upstash Redis.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from slack_sdk import WebClient

from paperbot.config import Settings
from paperbot.core import build_summarizer, process_job
from paperbot.jobs import verify_qstash_signature
from paperbot.retriever import PaperRetriever
from paperbot.store_redis import RedisSummaryStore


def run_job(job: dict) -> None:
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


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (Vercel/BaseHTTPRequestHandler API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")

        signature = self.headers.get("Upstash-Signature", "")
        if not verify_qstash_signature(
            os.environ["QSTASH_CURRENT_SIGNING_KEY"],
            os.environ["QSTASH_NEXT_SIGNING_KEY"],
            signature,
            body,
        ):
            self._json(401, {"error": "bad signature"})
            return

        run_job(json.loads(body))
        self._json(200, {"ok": True})

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
