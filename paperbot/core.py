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

    ``store`` only needs ``get(canonical_id) -> dict | None``, ``claim``, and
    ``save(paper, summary, channel, ts)``. The retrieval is deferred behind
    ``paper_factory`` so a duplicate never triggers a network fetch.
    """
    existing = store.get(ref.canonical_id)
    if existing and existing.get("slack_ts"):
        # Already fully summarized before -> point back to the prior summary.
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=duplicate_blocks(existing["slack_ts"]),
            text="Already summarized this paper.",
        )
        return

    if not store.claim(ref.canonical_id):
        # A concurrent delivery (e.g. a Slack retry) is already handling this paper.
        # Skip silently so the same paper isn't summarized and posted twice.
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

    ``slack_pdf_retriever`` is injectable for testing; it defaults to the real
    Slack-hosted PDF download.
    """
    if slack_pdf_retriever is None:
        slack_pdf_retriever = retrieve_slack_pdf

    channel = job["channel"]
    thread_ts = job["thread_ts"]
    text = job.get("text") or ""
    files = job.get("files") or []

    for ref in detect_papers(text):
        if ref.kind == PaperKind.WEBPAGE:
            # Resolve to a DOI/PDF ref before dedupe so a journal-page link and
            # its doi.org twin share one canonical_id. Non-paper links resolve
            # to None and are skipped without posting anything.
            try:
                resolved = retriever.resolve_ref(ref)
            except (RetrievalError, httpx.HTTPError) as exc:
                logger.exception("Failed to resolve %s", ref.source_url)
                if post_failures:
                    _post_failure(client, channel, thread_ts, ref.source_url, exc)
                continue
            if resolved is None:
                logger.info("Skipping non-paper link %s", ref.source_url)
                continue
            ref = resolved
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
            _post_failure(client, channel, thread_ts, ref.source_url, exc)


def _post_failure(client, channel: str, thread_ts: str, source_url: str, exc: Exception) -> None:  # type: ignore[no-untyped-def]
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        blocks=failure_blocks(source_url, str(exc)),
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
