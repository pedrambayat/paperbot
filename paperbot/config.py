from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OPENAI_MODEL = "gpt-5-mini"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    slack_app_token: str
    channel_id: str
    openai_api_key: str | None
    openai_model: str
    unpaywall_email: str | None
    db_path: Path
    dry_run: bool
    post_failures: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
            # Optional: only Socket Mode needs an app-level token. The serverless
            # (Events API) worker runs without one.
            slack_app_token=os.getenv("SLACK_APP_TOKEN", ""),
            channel_id=os.environ["PAPERBOT_CHANNEL_ID"],
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            unpaywall_email=os.getenv("UNPAYWALL_EMAIL"),
            db_path=Path(os.getenv("PAPERBOT_DB_PATH", "paperbot.sqlite3")),
            dry_run=_bool_env("PAPERBOT_DRY_RUN", False),
            post_failures=_bool_env("PAPERBOT_POST_FAILURES", True),
        )
