from __future__ import annotations

import logging
import os

import certifi
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Settings
from .formatter import duplicate_blocks, failure_blocks, slack_blocks
from .link_detector import detect_papers
from .models import PaperKind, PaperRef, RetrievedPaper, RetrievalMode
from .retriever import PaperRetriever, RetrievalError
from .store import SummaryStore
from .summarizer import DryRunSummarizer, OpenAISummarizer, Summarizer

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


def build_summarizer(settings: Settings) -> Summarizer:
    if settings.dry_run:
        return DryRunSummarizer()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required unless PAPERBOT_DRY_RUN=1")
    return OpenAISummarizer(settings.openai_api_key, settings.openai_model)


def create_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    store = SummaryStore(settings.db_path)
    retriever = PaperRetriever(settings.unpaywall_email)
    summarizer = build_summarizer(settings)

    @app.event("message")
    def handle_message_events(body, client, logger):  # type: ignore[no-untyped-def]
        event = body.get("event", {})
        subtype = event.get("subtype")
        if (subtype and subtype != "file_share") or event.get("bot_id"):
            return
        if event.get("channel") != settings.channel_id:
            return

        text = event.get("text") or ""
        thread_ts = event.get("thread_ts") or event.get("ts")
        refs = detect_papers(text)
        pdf_files = detect_pdf_files(event)
        if not refs and not pdf_files:
            return

        for ref in refs:
            try:
                summarize_and_post(
                    ref=ref,
                    paper_factory=lambda ref=ref: retriever.retrieve(ref),
                    store=store,
                    summarizer=summarizer,
                    client=client,
                    channel_id=settings.channel_id,
                    thread_ts=thread_ts,
                )
            except (RetrievalError, httpx.HTTPError, ValueError, RuntimeError) as exc:
                logger.exception("Failed to summarize %s", ref.canonical_id)
                if settings.post_failures:
                    client.chat_postMessage(
                        channel=settings.channel_id,
                        thread_ts=thread_ts,
                        blocks=failure_blocks(ref.source_url, str(exc)),
                        text=f"Could not summarize paper: {exc}",
                    )

        for file_info in pdf_files:
            ref = slack_pdf_ref(file_info)
            try:
                summarize_and_post(
                    ref=ref,
                    paper_factory=lambda file_info=file_info, ref=ref: retrieve_slack_pdf(
                        file_info, ref, settings.slack_bot_token
                    ),
                    store=store,
                    summarizer=summarizer,
                    client=client,
                    channel_id=settings.channel_id,
                    thread_ts=thread_ts,
                )
            except (RetrievalError, httpx.HTTPError, ValueError, RuntimeError) as exc:
                logger.exception("Failed to summarize %s", ref.canonical_id)
                if settings.post_failures:
                    client.chat_postMessage(
                        channel=settings.channel_id,
                        thread_ts=thread_ts,
                        blocks=failure_blocks(ref.source_url, str(exc)),
                        text=f"Could not summarize PDF: {exc}",
                    )

    return app


def summarize_and_post(
    ref: PaperRef,
    paper_factory,  # type: ignore[no-untyped-def]
    store: SummaryStore,
    summarizer: Summarizer,
    client,  # type: ignore[no-untyped-def]
    channel_id: str,
    thread_ts: str,
) -> None:
    existing = store.get(ref.canonical_id)
    if existing:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=duplicate_blocks(existing["slack_ts"]),
            text="Already summarized this paper.",
        )
        return

    paper = paper_factory()
    summary = summarizer.summarize(paper)
    response = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=slack_blocks(paper, summary),
        text=summary.tldr,
    )
    store.save(paper, summary, channel_id, response.get("ts", thread_ts))


def detect_pdf_files(event: dict) -> list[dict]:
    return [
        file_info
        for file_info in event.get("files", [])
        if file_info.get("mimetype") == "application/pdf"
        or str(file_info.get("name", "")).lower().endswith(".pdf")
    ]


def slack_pdf_ref(file_info: dict) -> PaperRef:
    identifier = file_info.get("id") or file_info.get("url_private_download") or file_info.get("name")
    source_url = file_info.get("permalink") or file_info.get("url_private_download") or str(identifier)
    return PaperRef(PaperKind.PDF, str(identifier), str(source_url))


def retrieve_slack_pdf(file_info: dict, ref: PaperRef, bot_token: str) -> RetrievedPaper:
    url = file_info.get("url_private_download") or file_info.get("url_private")
    if not url:
        raise RetrievalError("Slack PDF file did not include a private download URL")
    response = httpx.get(
        url,
        headers={"Authorization": f"Bearer {bot_token}"},
        follow_redirects=True,
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise RetrievalError(f"Slack PDF download failed: HTTP {response.status_code}")
    if not response.content.startswith(b"%PDF"):
        content_type = response.headers.get("content-type", "unknown content type")
        raise RetrievalError(f"Expected Slack PDF, got {content_type}")
    return RetrievedPaper(
        ref=ref,
        title=file_info.get("title") or file_info.get("name") or "Slack PDF",
        pdf_url=url,
        pdf_bytes=response.content,
        landing_url=file_info.get("permalink") or ref.source_url,
        mode=RetrievalMode.FULL_TEXT,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ensure_tls_certs()
    settings = Settings.from_env()
    app = create_app(settings)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
