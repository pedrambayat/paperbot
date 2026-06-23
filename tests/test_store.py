from tempfile import TemporaryDirectory
from pathlib import Path

from paperbot.models import PaperKind, PaperRef, PaperSummary, RetrievedPaper, RetrievalMode
from paperbot.store import SummaryStore


def test_store_saves_summary_metadata():
    with TemporaryDirectory() as tmpdir:
        store = SummaryStore(Path(tmpdir) / "paperbot.sqlite3")
        paper = RetrievedPaper(
            ref=PaperRef(
                kind=PaperKind.ARXIV,
                identifier="2401.01234v2",
                source_url="https://arxiv.org/abs/2401.01234v2",
            ),
            title="Useful paper",
            landing_url="https://arxiv.org/abs/2401.01234v2",
            pdf_url="https://arxiv.org/pdf/2401.01234",
            mode=RetrievalMode.FULL_TEXT,
        )
        summary = PaperSummary(
            tldr="A compact summary.",
            problem="A problem.",
            method="A method.",
            result="A result.",
            limitations="A limitation.",
            evidence_level="full_text",
        )

        store.save(paper, summary, "C123", "1719160000.000200")

        saved = store.get("arxiv:2401.01234")
        assert saved is not None
        assert saved["title"] == "Useful paper"
        assert saved["slack_channel"] == "C123"
        assert saved["slack_ts"] == "1719160000.000200"
        assert saved["mode"] == "full_text"


def test_claim_is_atomic_first_wins():
    with TemporaryDirectory() as tmpdir:
        store = SummaryStore(Path(tmpdir) / "paperbot.sqlite3")
        assert store.claim("arxiv:2401.01234") is True
        assert store.claim("arxiv:2401.01234") is False
