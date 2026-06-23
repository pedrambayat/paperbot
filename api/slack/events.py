"""Vercel function A: receive Slack events, ack within 3s, enqueue to QStash.

This endpoint does the bare minimum so it always replies inside Slack's
3-second deadline: verify the request signature, answer the URL-verification
handshake, and (for a paper-bearing message) hand the job to QStash. The heavy
retrieve/summarize work happens in api/process.py.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from paperbot.events import job_from_event, url_verification_challenge
from paperbot.jobs import publish_job
from paperbot.slack_verify import verify_slack_signature


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (Vercel/BaseHTTPRequestHandler API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        timestamp = self.headers.get("X-Slack-Request-Timestamp", "")
        signature = self.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(os.environ["SLACK_SIGNING_SECRET"], timestamp, signature, body):
            self._json(401, {"error": "bad signature"})
            return

        payload = json.loads(body or b"{}")

        challenge = url_verification_challenge(payload)
        if challenge:
            self._json(200, {"challenge": challenge})
            return

        try:
            job = job_from_event(payload, os.environ["PAPERBOT_CHANNEL_ID"])
            if job:
                publish_job(os.environ["QSTASH_TOKEN"], os.environ["PAPERBOT_PROCESS_URL"], job)
        except Exception:  # noqa: BLE001 - let Slack retry by returning 500
            self._json(500, {"error": "enqueue failed"})
            return

        self._json(200, {"ok": True})

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
