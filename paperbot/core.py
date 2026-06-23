from __future__ import annotations

import logging

import httpx

from .config import Settings
from .formatter import duplicate_blocks, failure_blocks, slack_blocks
from .link_detector import detect_papers
from .models import PaperKind, PaperRef, RetrievalMode, RetrievedPaper
from .retriever import RetrievalError
from .summarizer import DryRunSummarizer, OpenAISummarizer, Summarizer

logger = logging.getLogger(__name__)


def build_summarizer(settings: Settings) -> Summarizer:
    if settings.dry_run:
        return DryRunSummarizer()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required unless PAPERBOT_DRY_RUN=1")
    return OpenAISummarizer(settings.openai_api_key, settings.openai_model)


def summarize_and_post(
    ref: PaperRef,
    paper_factory,  # type: ignore[no-untyped-def]
    store,  # type: ignore[no-untyped-def]
    summarizer: Summarizer,
    client,  # type: ignore[no-untyped-def]
    channel_id: str,
    thread_ts: str,
) -> None:
    """Dedup, retrieve, summarize, post, and record one paper.

    ``store`` only needs ``get(canonical_id) -> dict | None`` and
    ``save(paper, summary, channel, ts)``, so it works with the SQLite store
    (Socket Mode) or the Redis store (serverless). The retrieval is deferred
    behind ``paper_factory`` so a duplicate never triggers a network fetch.
    """
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


def process_job(
    job: dict,
    *,
    retriever,  # type: ignore[no-untyped-def]
    store,  # type: ignore[no-untyped-def]
    summarizer: Summarizer,
    client,  # type: ignore[no-untyped-def]
    bot_token: str,
    post_failures: bool = True,
    slack_pdf_retriever=None,  # type: ignore[no-untyped-def]
) -> None:
    """Summarize every paper link and PDF in a job, posting failures inline.

    Shared by the Socket Mode handler and the serverless worker so both behave
    identically. ``slack_pdf_retriever`` is injectable for testing; it defaults
    to the real Slack-hosted PDF download.
    """
    if slack_pdf_retriever is None:
        slack_pdf_retriever = retrieve_slack_pdf

    channel = job["channel"]
    thread_ts = job["thread_ts"]
    text = job.get("text") or ""
    files = job.get("files") or []

    for ref in detect_papers(text):
        _summarize_one(
            ref,
            lambda ref=ref: retriever.retrieve(ref),
            store, summarizer, client, channel, thread_ts, post_failures,
        )

    for file_info in files:
        ref = slack_pdf_ref(file_info)
        _summarize_one(
            ref,
            lambda file_info=file_info, ref=ref: slack_pdf_retriever(file_info, ref, bot_token),
            store, summarizer, client, channel, thread_ts, post_failures,
        )


def _summarize_one(
    ref: PaperRef,
    paper_factory,  # type: ignore[no-untyped-def]
    store,  # type: ignore[no-untyped-def]
    summarizer: Summarizer,
    client,  # type: ignore[no-untyped-def]
    channel: str,
    thread_ts: str,
    post_failures: bool,
) -> None:
    try:
        summarize_and_post(
            ref=ref,
            paper_factory=paper_factory,
            store=store,
            summarizer=summarizer,
            client=client,
            channel_id=channel,
            thread_ts=thread_ts,
        )
    except (RetrievalError, httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.exception("Failed to summarize %s", ref.canonical_id)
        if post_failures:
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                blocks=failure_blocks(ref.source_url, str(exc)),
                text=f"Could not summarize paper: {exc}",
            )


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
