import pytest

from paperbot.models import PaperKind, PaperRef, RetrievalMode
from paperbot.retriever import (
    PaperRetriever,
    RetrievalError,
    extract_citation_meta,
    pii_candidates,
)

CELL_PAGE = "https://www.cell.com/cell/fulltext/S0092-8674(23)01331-1"
UNKNOWN_PAGE = "https://journals.example.edu/article/12345"

ARTICLE_HTML = """
<html><head>
<meta name="citation_title" content="A Landmark Paper" />
<meta name="citation_author" content="Ada Lovelace"/>
<meta name="citation_author" content="Alan Turing"/>
<meta content="10.1016/j.cell.2023.12.016" name="citation_doi" />
<meta name='citation_pdf_url' content='/action/showPdf?pii=S0092-8674'/>
<meta property="og:description" content="We report a landmark result." />
</head><body></body></html>
"""


class FakeResp:
    def __init__(self, status_code=200, content=b"", json_data=None, headers=None, text="", url=""):
        self.status_code = status_code
        self.content = content
        self._json = json_data
        self.headers = headers or {}
        self.text = text
        self.url = url

    def json(self):
        return self._json


class RoutingFake:
    """Dispatches get() by URL substring; unmatched URLs get a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for fragment, resp in self.routes.items():
            if fragment in url:
                return resp if not callable(resp) else resp()
        return FakeResp(404)


def test_extract_citation_meta_reads_highwire_tags():
    meta = extract_citation_meta(ARTICLE_HTML)
    assert meta["doi"] == "10.1016/j.cell.2023.12.016"
    assert meta["title"] == "A Landmark Paper"
    assert meta["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert meta["pdf_url"] == "/action/showPdf?pii=S0092-8674"
    assert meta["abstract"] == "We report a landmark result."


def test_extract_citation_meta_empty_for_non_article_page():
    assert extract_citation_meta("<html><head><title>News</title></head></html>") == {}


def test_pii_candidates_punctuated_and_compact():
    assert pii_candidates(CELL_PAGE) == ["S0092-8674(23)01331-1"]
    assert pii_candidates("https://www.sciencedirect.com/science/article/pii/S0092867423013311") == [
        "S0092-8674(23)01331-1",
        "S0092867423013311",
    ]
    assert pii_candidates("https://example.com/no-pii") == []


def _webpage_ref(url):
    return PaperRef(PaperKind.WEBPAGE, url, url)


def test_resolve_ref_returns_doi_ref_from_page_meta():
    retriever = PaperRetriever()
    retriever.browser = RoutingFake({"journals.example.edu": FakeResp(200, text=ARTICLE_HTML, url=UNKNOWN_PAGE)})
    resolved = retriever.resolve_ref(_webpage_ref(UNKNOWN_PAGE))
    assert resolved.kind == PaperKind.DOI
    assert resolved.identifier == "10.1016/j.cell.2023.12.016"
    assert resolved.source_url == UNKNOWN_PAGE
    # scraped meta is cached for the DOI retrieval chain
    assert retriever._page_meta[resolved.identifier]["title"] == "A Landmark Paper"


def test_resolve_ref_returns_none_for_non_paper_page():
    retriever = PaperRetriever()
    retriever.browser = RoutingFake({"journals.example.edu": FakeResp(200, text="<html>a blog</html>")})
    assert retriever.resolve_ref(_webpage_ref(UNKNOWN_PAGE)) is None


def test_resolve_ref_blocked_cell_page_falls_back_to_pii_lookup():
    retriever = PaperRetriever()
    retriever.browser = RoutingFake({"cell.com": FakeResp(403)})
    retriever.client = RoutingFake(
        {"api.crossref.org/works": FakeResp(200, json_data={"message": {"items": [{"DOI": "10.1016/J.CELL.2023.12.016"}]}})}
    )
    resolved = retriever.resolve_ref(_webpage_ref(CELL_PAGE))
    assert resolved.kind == PaperKind.DOI
    assert resolved.identifier == "10.1016/j.cell.2023.12.016"


def test_resolve_ref_raises_for_unresolvable_journal_page():
    retriever = PaperRetriever()
    retriever.browser = RoutingFake({"pnas.org": FakeResp(403)})
    retriever.client = RoutingFake({})
    with pytest.raises(RetrievalError):
        retriever.resolve_ref(_webpage_ref("https://www.pnas.org/doi-landing/some-article"))


def test_resolve_ref_silently_drops_unresolvable_unknown_page():
    retriever = PaperRetriever()
    retriever.browser = RoutingFake({})
    retriever.client = RoutingFake({})
    assert retriever.resolve_ref(_webpage_ref(UNKNOWN_PAGE)) is None


def test_doi_chain_falls_back_to_publisher_pdf():
    """When Unpaywall/OpenAlex have no OA copy, the publisher's citation_pdf_url
    is tried with the browser client (institutional IP access)."""
    doi = "10.1016/j.cell.2023.12.016"
    ref = PaperRef(PaperKind.DOI, doi, CELL_PAGE)
    page_html = ARTICLE_HTML.replace("/action/showPdf?pii=S0092-8674", "https://www.cell.com/article.pdf")
    retriever = PaperRetriever()  # no unpaywall email -> unpaywall skipped
    retriever.client = RoutingFake({})  # crossref + openalex both fail
    retriever.browser = RoutingFake(
        {
            "article.pdf": FakeResp(200, content=b"%PDF-1.5 fake", headers={"content-type": "application/pdf"}),
            "cell.com": FakeResp(200, text=page_html, url=CELL_PAGE),
        }
    )
    paper = retriever.retrieve(ref)
    assert paper.mode == RetrievalMode.FULL_TEXT
    assert paper.pdf_bytes == b"%PDF-1.5 fake"
    assert paper.pdf_url == "https://www.cell.com/article.pdf"
    assert paper.title == "A Landmark Paper"


def test_doi_chain_degrades_to_abstract_when_publisher_pdf_blocked():
    doi = "10.1016/j.cell.2023.12.016"
    ref = PaperRef(PaperKind.DOI, doi, CELL_PAGE)
    retriever = PaperRetriever()
    retriever.client = RoutingFake({})
    retriever.browser = RoutingFake(
        {
            "article.pdf": FakeResp(403),
            "cell.com": FakeResp(
                200,
                text=ARTICLE_HTML.replace("/action/showPdf?pii=S0092-8674", "https://www.cell.com/article.pdf"),
                url=CELL_PAGE,
            ),
        }
    )
    paper = retriever.retrieve(ref)
    assert paper.mode == RetrievalMode.ABSTRACT_ONLY
    assert paper.abstract == "We report a landmark result."
    assert paper.pdf_bytes is None
