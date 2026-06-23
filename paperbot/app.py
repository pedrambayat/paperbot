from __future__ import annotations

import logging
import os

import certifi
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Settings
from .core import build_summarizer, process_job
from .events import job_from_event
from .retriever import PaperRetriever
from .store import SummaryStore

logger = logging.getLogger(__name__)


def ensure_tls_certs() -> None:
    """Make TLS verification trust certifi's CA bundle.

    slack_sdk talks to Slack over urllib, whose default SSL context trusts only
    the interpreter's CA store. The macOS python.org framework build ships with an
    empty store, so Slack TLS fails with CERTIFICATE_VERIFY_FAILED unless certs are
    installed separately. Pointing SSL_CERT_FILE at certifi's bundle fixes this for
    any launch context (shell, venv, with or without a sourced .env). We use
    setdefault so an operator-provided bundle still wins.
    """
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())


def create_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    store = SummaryStore(settings.db_path)
    retriever = PaperRetriever(settings.unpaywall_email)
    summarizer = build_summarizer(settings)

    @app.event("message")
    def handle_message_events(body, client, logger):  # type: ignore[no-untyped-def]
        job = job_from_event(body, settings.channel_id)
        if not job:
            return
        process_job(
            job,
            retriever=retriever,
            store=store,
            summarizer=summarizer,
            client=client,
            bot_token=settings.slack_bot_token,
            post_failures=settings.post_failures,
        )

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ensure_tls_certs()
    settings = Settings.from_env()
    app = create_app(settings)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
