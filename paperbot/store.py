from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import PaperSummary, RetrievedPaper


class SummaryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                  canonical_id TEXT PRIMARY KEY,
                  title TEXT,
                  source_url TEXT NOT NULL,
                  landing_url TEXT,
                  pdf_url TEXT,
                  mode TEXT NOT NULL,
                  summary_json TEXT NOT NULL,
                  slack_channel TEXT NOT NULL,
                  slack_ts TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def claim(self, canonical_id: str) -> bool:
        """Atomically claim a paper for processing. Returns True only for the first
        caller (relies on the primary-key conflict of INSERT OR IGNORE); a later
        ``save`` overwrites the placeholder with the full record.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO summaries
                  (canonical_id, source_url, mode, summary_json, slack_channel, slack_ts)
                VALUES (?, '', '', '{}', '', '')
                """,
                (canonical_id,),
            )
            return cursor.rowcount > 0

    def get(self, canonical_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
        return dict(row) if row else None

    def save(
        self,
        paper: RetrievedPaper,
        summary: PaperSummary,
        slack_channel: str,
        slack_ts: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO summaries (
                  canonical_id, title, source_url, landing_url, pdf_url, mode,
                  summary_json, slack_channel, slack_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper.ref.canonical_id,
                    paper.title,
                    paper.ref.source_url,
                    paper.landing_url,
                    paper.pdf_url,
                    paper.mode.value,
                    json.dumps(summary.__dict__, sort_keys=True),
                    slack_channel,
                    slack_ts,
                ),
            )

