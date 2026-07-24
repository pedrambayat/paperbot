from __future__ import annotations

from .link_detector import detect_papers


def detect_pdf_files(event: dict) -> list[dict]:
    """PDF file uploads attached to a Slack message."""
    return [
        file_info
        for file_info in event.get("files", [])
        if file_info.get("mimetype") == "application/pdf"
        or str(file_info.get("name", "")).lower().endswith(".pdf")
    ]


def job_from_event(payload: dict, channel_id: str) -> dict | None:
    """Build a background job from a Slack ``event_callback`` payload.

    Returns a small dict describing the work when the event is a non-bot
    message in the watched channel that contains a paper link/DOI or a PDF
    upload; otherwise None.
    """
    if payload.get("type") != "event_callback":
        return None
    event = payload.get("event") or {}
    if event.get("type") != "message":
        return None

    subtype = event.get("subtype")
    if (subtype and subtype != "file_share") or event.get("bot_id"):
        return None
    if event.get("channel") != channel_id:
        return None

    text = event.get("text") or ""
    files = detect_pdf_files(event)
    if not detect_papers(text) and not files:
        return None

    return {
        "channel": event.get("channel"),
        "thread_ts": event.get("thread_ts") or event.get("ts"),
        "text": text,
        "files": files,
    }
