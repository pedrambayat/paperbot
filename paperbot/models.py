from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re


class PaperKind(StrEnum):
    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    MEDRXIV = "medrxiv"
    DOI = "doi"
    PDF = "pdf"
    # A URL that may be a journal article page; resolved to a DOI/PDF ref by
    # PaperRetriever.resolve_ref() before dedupe, or dropped if it isn't a paper.
    WEBPAGE = "webpage"


class RetrievalMode(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"


@dataclass(frozen=True)
class PaperRef:
    kind: PaperKind
    identifier: str
    source_url: str

    @property
    def canonical_id(self) -> str:
        identifier = self.identifier.lower()
        if self.kind in {PaperKind.ARXIV, PaperKind.BIORXIV, PaperKind.MEDRXIV}:
            identifier = re.sub(r"v\d+$", "", identifier)
        return f"{self.kind.value}:{identifier}"


@dataclass
class RetrievedPaper:
    ref: PaperRef
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    full_text: str | None = None
    pdf_url: str | None = None
    pdf_bytes: bytes | None = None
    landing_url: str | None = None
    mode: RetrievalMode = RetrievalMode.ABSTRACT_ONLY


@dataclass(frozen=True)
class PaperSummary:
    tldr: str
    problem: str
    method: str
    result: str
    limitations: str
    evidence_level: str
