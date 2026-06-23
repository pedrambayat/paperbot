from __future__ import annotations

from .models import PaperSummary, RetrievedPaper, RetrievalMode


def slack_blocks(paper: RetrievedPaper, summary: PaperSummary) -> list[dict]:
    title = paper.title or paper.ref.identifier
    evidence = "Full text" if paper.mode == RetrievalMode.FULL_TEXT else "Abstract only"
    title_link = paper.landing_url or paper.ref.source_url
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<{title_link}|{escape_slack(title)}>*\n_{evidence} summary_",
            },
        },
        {"type": "divider"},
    ]
    for label, value in [
        ("TL;DR", summary.tldr),
        ("Problem", summary.problem),
        ("Method", summary.method),
        ("Result", summary.result),
        ("Limitations", summary.limitations),
    ]:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{label}:* {escape_slack(value)}"},
            }
        )
    return blocks


def failure_blocks(source_url: str, reason: str) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: I found a paper link but could not summarize it.\n*Link:* {source_url}\n*Reason:* {escape_slack(reason)}",
            },
        }
    ]


def duplicate_blocks(existing_slack_ts: str) -> list[dict]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: Already summarized in this channel at `{existing_slack_ts}`.",
            },
        }
    ]


def escape_slack(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

