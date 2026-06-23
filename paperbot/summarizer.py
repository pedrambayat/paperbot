from __future__ import annotations

import base64
import json
from dataclasses import asdict

from openai import OpenAI

from .models import PaperSummary, RetrievedPaper, RetrievalMode

PROMPT = """You summarize biomedical, computational biology, and ML-for-biology papers for a lab Slack channel.

Return only JSON with these keys:
- tldr: one concise sentence
- problem: what question or gap the paper addresses
- method: the core method, model, assay, dataset, or experimental system
- result: the headline finding, including concrete numbers when present
- limitations: caveats, missing validations, or reasons to read cautiously
- evidence_level: "full_text" or "abstract_only"

Prefer accuracy over excitement. If a detail is not present, say "Not clear from the provided text."
Keep each field under 240 characters.
"""


class Summarizer:
    def summarize(self, paper: RetrievedPaper) -> PaperSummary:
        raise NotImplementedError


class DryRunSummarizer(Summarizer):
    def summarize(self, paper: RetrievedPaper) -> PaperSummary:
        title = paper.title or paper.ref.identifier
        return PaperSummary(
            tldr=f"Dry run summary for {title}.",
            problem="Dry run mode did not call an LLM.",
            method="Retrieval and Slack formatting can be tested without model usage.",
            result="No scientific result was generated.",
            limitations="Replace PAPERBOT_DRY_RUN=1 with real OpenAI credentials before deployment.",
            evidence_level=paper.mode.value,
        )


class OpenAISummarizer(Summarizer):
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def summarize(self, paper: RetrievedPaper) -> PaperSummary:
        content: list[dict[str, str]] = []
        instruction = summary_instruction(paper)
        if paper.pdf_bytes:
            encoded = base64.b64encode(paper.pdf_bytes).decode("ascii")
            content.append(
                {
                    "type": "input_file",
                    "filename": "paper.pdf",
                    "file_data": f"data:application/pdf;base64,{encoded}",
                }
            )
        content.append({"type": "input_text", "text": instruction})

        response = self.client.responses.create(
            model=self.model,
            instructions=PROMPT,
            input=[{"role": "user", "content": content}],
        )
        text = response.output_text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model returned non-JSON summary: {text[:500]}") from exc
        return PaperSummary(**{key: str(data.get(key, "")).strip() for key in asdict(DryRunSummarizer().summarize(paper))})


def summary_instruction(paper: RetrievedPaper) -> str:
    metadata = {
        "title": paper.title,
        "authors": paper.authors,
        "source_url": paper.ref.source_url,
        "landing_url": paper.landing_url,
        "pdf_url": paper.pdf_url,
        "retrieval_mode": paper.mode.value,
        "abstract": paper.abstract,
        "full_text": paper.full_text,
    }
    if paper.mode == RetrievalMode.ABSTRACT_ONLY:
        return (
            "Summarize this paper from metadata and abstract only. "
            "Set evidence_level to abstract_only and be explicit about uncertainty.\n\n"
            f"{json.dumps(metadata, indent=2)}"
        )
    if paper.full_text and not paper.pdf_bytes:
        return (
            "Summarize this full-text paper extracted from publisher XML. "
            "Set evidence_level to full_text.\n\n"
            f"{json.dumps(metadata, indent=2)}"
        )
    return (
        "Summarize the attached full-text paper. Use metadata below to disambiguate the paper.\n\n"
        f"{json.dumps(metadata, indent=2)}"
    )
