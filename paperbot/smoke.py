from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from .config import DEFAULT_OPENAI_MODEL
from .formatter import slack_blocks
from .link_detector import detect_papers
from .retriever import PaperRetriever
from .summarizer import DryRunSummarizer, OpenAISummarizer, Summarizer


def build_smoke_summarizer(real: bool, model: str) -> Summarizer:
    if not real:
        return DryRunSummarizer()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --real smoke tests")
    return OpenAISummarizer(api_key, model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Paperbot link detection, retrieval, and summarization without Slack."
    )
    parser.add_argument("text", help="A paper URL, DOI, or Slack-like message text.")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Call the configured OpenAI model instead of using the free dry-run summarizer.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        help=f"OpenAI model to use with --real. Defaults to {DEFAULT_OPENAI_MODEL}.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a human-readable summary.",
    )
    args = parser.parse_args()

    refs = detect_papers(args.text)
    if not refs:
        raise SystemExit("No paper links or DOIs detected.")

    retriever = PaperRetriever(os.getenv("UNPAYWALL_EMAIL"))
    summarizer = build_smoke_summarizer(args.real, args.model)
    try:
        for index, ref in enumerate(refs, start=1):
            paper = retriever.retrieve(ref)
            summary = summarizer.summarize(paper)
            if args.json:
                print(
                    json.dumps(
                        {
                            "index": index,
                            "ref": asdict(ref),
                            "canonical_id": ref.canonical_id,
                            "paper": {
                                key: value
                                for key, value in asdict(paper).items()
                                if key != "pdf_bytes"
                            },
                            "summary": asdict(summary),
                            "slack_blocks": slack_blocks(paper, summary),
                        },
                        indent=2,
                    )
                )
                continue

            print(f"\n[{index}] {paper.title or ref.identifier}")
            print(f"Canonical ID: {ref.canonical_id}")
            print(f"Retrieval mode: {paper.mode.value}")
            if paper.landing_url:
                print(f"Landing URL: {paper.landing_url}")
            if paper.pdf_url:
                print(f"PDF URL: {paper.pdf_url}")
            print("\nSummary")
            print(f"TL;DR: {summary.tldr}")
            print(f"Problem: {summary.problem}")
            print(f"Method: {summary.method}")
            print(f"Result: {summary.result}")
            print(f"Limitations: {summary.limitations}")
            print(f"Evidence level: {summary.evidence_level}")
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
