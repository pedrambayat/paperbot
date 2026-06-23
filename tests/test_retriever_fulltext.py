from paperbot.models import PaperKind, PaperRef, RetrievalMode
from paperbot.retriever import PaperRetriever


class FakeResp:
    def __init__(self, status_code=200, content=b"", json_data=None, headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self._json = json_data
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


class FakeHttpx:
    """Stands in for the httpx metadata client (api.biorxiv.org is not Cloudflare-walled)."""

    def __init__(self, json_data):
        self.json_data = json_data

    def get(self, url, **kwargs):
        return FakeResp(200, json_data=self.json_data)


class FakeBrowser:
    """Stands in for the curl_cffi browser session used for full-text downloads."""

    def __init__(self, *, status_code=200, content=b"", headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResp(self.status_code, content=self.content, headers=self.headers, text=self.text)


def _rxiv_retriever(browser):
    retriever = PaperRetriever()
    retriever.client = FakeHttpx(
        {
            "collection": [
                {
                    "title": "Engineering an in vitro spinal column",
                    "authors": "Iordachescu, A.; Grover, L. M.",
                    "abstract": "An abstract from the bioRxiv metadata API.",
                    "jatsxml": "https://www.biorxiv.org/content/early/x.source.xml",
                }
            ]
        }
    )
    retriever.browser = browser
    return retriever


def _rxiv_ref():
    return PaperRef(
        PaperKind.BIORXIV,
        "10.64898/2026.06.22.733686v1",
        "https://www.biorxiv.org/content/10.64898/2026.06.22.733686v1",
    )


def test_rxiv_retrieves_full_text_pdf_via_browser_client():
    # Cloudflare-protected PDF is reachable through the browser-impersonating client.
    browser = FakeBrowser(content=b"%PDF-1.7 full paper bytes", headers={"content-type": "application/pdf"})
    paper = _rxiv_retriever(browser).retrieve(_rxiv_ref())

    assert paper.mode == RetrievalMode.FULL_TEXT
    assert paper.pdf_bytes == b"%PDF-1.7 full paper bytes"
    assert paper.pdf_url and paper.pdf_url.endswith(".full.pdf")
    # The PDF must be fetched through the browser session, not the plain httpx client.
    assert browser.calls and browser.calls[0].endswith(".full.pdf")


def test_rxiv_falls_back_to_abstract_when_browser_is_blocked():
    # Both the PDF and JATS XML return 403 (Cloudflare block) -> abstract-only.
    browser = FakeBrowser(status_code=403, content=b"<html>blocked</html>")
    paper = _rxiv_retriever(browser).retrieve(_rxiv_ref())

    assert paper.mode == RetrievalMode.ABSTRACT_ONLY
    assert paper.pdf_bytes is None
    assert paper.abstract == "An abstract from the bioRxiv metadata API."
