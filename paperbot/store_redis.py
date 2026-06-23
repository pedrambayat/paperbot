from __future__ import annotations

import json

import httpx

from .models import PaperSummary, RetrievedPaper

NAMESPACE = "paperbot:summary:"


class RedisSummaryStore:
    """Dedup/summary store backed by Upstash Redis over its REST API.

    Matches the ``get`` / ``save`` interface of :class:`paperbot.store.SummaryStore`
    so the shared ``summarize_and_post`` works unchanged. Uses the stateless REST
    API (one HTTP request per command) which suits serverless functions — there is
    no persistent connection to pool.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        namespace: str = NAMESPACE,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.namespace = namespace
        self.client = client or httpx.Client(timeout=timeout)

    def _command(self, *args: str):
        response = self.client.post(
            self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            json=list(args),
        )
        response.raise_for_status()
        return response.json().get("result")

    def claim(self, canonical_id: str, ttl_seconds: int = 300) -> bool:
        """Atomically claim a paper for processing. Returns True only for the first
        caller; concurrent/duplicate deliveries get False and should skip. The claim
        is a short-lived placeholder (TTL) so a crashed worker doesn't block the
        paper forever; a successful summary overwrites it via ``save``.
        """
        result = self._command(
            "SET", self.namespace + canonical_id, "{}", "NX", "EX", str(ttl_seconds)
        )
        return result == "OK"

    def get(self, canonical_id: str) -> dict | None:
        result = self._command("GET", self.namespace + canonical_id)
        if result is None:
            return None
        return json.loads(result)

    def save(
        self,
        paper: RetrievedPaper,
        summary: PaperSummary,
        slack_channel: str,
        slack_ts: str,
    ) -> None:
        record = {
            "canonical_id": paper.ref.canonical_id,
            "title": paper.title,
            "source_url": paper.ref.source_url,
            "landing_url": paper.landing_url,
            "pdf_url": paper.pdf_url,
            "mode": paper.mode.value,
            "summary": summary.__dict__,
            "slack_channel": slack_channel,
            "slack_ts": slack_ts,
        }
        self._command("SET", self.namespace + paper.ref.canonical_id, json.dumps(record))
