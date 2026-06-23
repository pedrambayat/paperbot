from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import unescape

import httpx
from curl_cffi import requests as browser_requests

from .models import PaperKind, PaperRef, RetrievedPaper, RetrievalMode

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/{doi}"
OPENALEX_API = "https://api.openalex.org/works/https://doi.org/{doi}"
UNPAYWALL_API = "https://api.unpaywall.org/v2/{doi}"
BIO_RXIV_API = "https://api.biorxiv.org/details/{server}/{doi}"


class RetrievalError(RuntimeError):
    pass


class PaperRetriever:
    def __init__(self, unpaywall_email: str | None = None, timeout: float = 30.0) -> None:
        self.unpaywall_email = unpaywall_email
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "paperbot/0.1 (+https://github.com/pedram/paperbot)"},
        )
        # Full-text hosts (biorxiv/medrxiv, many publishers) sit behind Cloudflare,
        # which blocks plain HTTP clients on TLS fingerprint. Impersonate a real
        # browser for content downloads so we can reach the actual paper instead of
        # falling back to abstract-only.
        self.browser = browser_requests.Session(impersonate="chrome")

    def close(self) -> None:
        self.client.close()
        self.browser.close()

    def retrieve(self, ref: PaperRef) -> RetrievedPaper:
        if ref.kind == PaperKind.ARXIV:
            return self._retrieve_arxiv(ref)
        if ref.kind == PaperKind.BIORXIV:
            return self._retrieve_rxiv(ref, "biorxiv")
        if ref.kind == PaperKind.MEDRXIV:
            return self._retrieve_rxiv(ref, "medrxiv")
        if ref.kind == PaperKind.DOI:
            return self._retrieve_doi(ref)
        if ref.kind == PaperKind.PDF:
            return self._retrieve_pdf(ref)
        raise RetrievalError(f"Unsupported paper kind: {ref.kind}")

    def _retrieve_arxiv(self, ref: PaperRef) -> RetrievedPaper:
        arxiv_id = ref.identifier.removesuffix(".pdf")
        metadata = self.client.get(ARXIV_API, params={"id_list": arxiv_id})
        metadata.raise_for_status()
        title, authors, abstract = parse_arxiv_metadata(metadata.text)
        versionless_id = re.sub(r"v\d+$", "", arxiv_id)
        pdf_url = f"https://arxiv.org/pdf/{versionless_id}"
        pdf_bytes = self._download_pdf(pdf_url)
        return RetrievedPaper(
            ref=ref,
            title=title,
            authors=authors,
            abstract=abstract,
            pdf_url=pdf_url,
            pdf_bytes=pdf_bytes,
            landing_url=f"https://arxiv.org/abs/{arxiv_id}",
            mode=RetrievalMode.FULL_TEXT,
        )

    def _retrieve_rxiv(self, ref: PaperRef, server: str) -> RetrievedPaper:
        title = None
        authors: list[str] = []
        abstract = None
        landing_url = ref.source_url
        latest = self._rxiv_metadata(server, ref.identifier)
        if latest:
            title = latest.get("title")
            authors = split_authors(latest.get("authors") or "")
            abstract = latest.get("abstract")
            landing_url = latest.get("jatsxml") or latest.get("rel_site") or landing_url

        pdf_url = f"https://www.{server}.org/content/{ref.identifier}.full.pdf"
        try:
            pdf_bytes = self._download_pdf(pdf_url)
            full_text = None
            mode = RetrievalMode.FULL_TEXT
        except RetrievalError:
            full_text = self._download_jats_text(latest.get("jatsxml")) if latest else None
            if full_text:
                pdf_bytes = None
                mode = RetrievalMode.FULL_TEXT
            elif not abstract:
                raise
            else:
                pdf_bytes = None
                mode = RetrievalMode.ABSTRACT_ONLY

        return RetrievedPaper(
            ref=ref,
            title=title,
            authors=authors,
            abstract=abstract,
            full_text=full_text,
            pdf_url=pdf_url if pdf_bytes else None,
            pdf_bytes=pdf_bytes,
            landing_url=landing_url,
            mode=mode,
        )

    def _rxiv_metadata(self, server: str, doi: str) -> dict[str, str] | None:
        for candidate in rxiv_doi_candidates(doi):
            details = self.client.get(BIO_RXIV_API.format(server=server, doi=candidate))
            if details.status_code != 200:
                continue
            collection = details.json().get("collection") or []
            if collection:
                return collection[-1]
        return None

    def _retrieve_pdf(self, ref: PaperRef) -> RetrievedPaper:
        pdf_bytes = self._download_pdf(ref.source_url)
        return RetrievedPaper(
            ref=ref,
            title=title_from_pdf_url(ref.source_url),
            pdf_url=ref.source_url,
            pdf_bytes=pdf_bytes,
            landing_url=ref.source_url,
            mode=RetrievalMode.FULL_TEXT,
        )

    def _download_jats_text(self, xml_url: str | None) -> str | None:
        if not xml_url:
            return None
        response = self.browser.get(xml_url, timeout=self.timeout, allow_redirects=True)
        if response.status_code >= 400:
            return None
        return extract_jats_text(response.text)

    def _retrieve_doi(self, ref: PaperRef) -> RetrievedPaper:
        metadata = self._crossref_metadata(ref.identifier)
        paper = RetrievedPaper(
            ref=ref,
            title=metadata.get("title"),
            authors=metadata.get("authors", []),
            abstract=metadata.get("abstract"),
            landing_url=metadata.get("landing_url") or ref.source_url,
        )

        pdf_url = self._unpaywall_pdf_url(ref.identifier)
        if pdf_url:
            try:
                paper.pdf_url = pdf_url
                paper.pdf_bytes = self._download_pdf(pdf_url)
                paper.mode = RetrievalMode.FULL_TEXT
                return paper
            except RetrievalError:
                pass

        openalex = self._openalex_metadata(ref.identifier)
        paper.title = paper.title or openalex.get("title")
        paper.authors = paper.authors or openalex.get("authors", [])
        paper.abstract = paper.abstract or openalex.get("abstract")
        paper.pdf_url = paper.pdf_url or openalex.get("pdf_url")
        paper.landing_url = paper.landing_url or openalex.get("landing_url")

        if paper.pdf_url:
            try:
                paper.pdf_bytes = self._download_pdf(paper.pdf_url)
                paper.mode = RetrievalMode.FULL_TEXT
                return paper
            except RetrievalError:
                pass

        if paper.abstract:
            paper.mode = RetrievalMode.ABSTRACT_ONLY
            return paper

        raise RetrievalError(f"No full text or abstract available for DOI {ref.identifier}")

    def _crossref_metadata(self, doi: str) -> dict[str, object]:
        response = self.client.get(CROSSREF_API.format(doi=doi))
        if response.status_code >= 400:
            return {}
        message = response.json().get("message", {})
        title = first(message.get("title"))
        authors = [
            " ".join(part for part in [author.get("given"), author.get("family")] if part)
            for author in message.get("author", [])
        ]
        return {
            "title": title,
            "authors": authors,
            "abstract": clean_abstract(message.get("abstract")),
            "landing_url": message.get("URL"),
        }

    def _unpaywall_pdf_url(self, doi: str) -> str | None:
        if not self.unpaywall_email:
            return None
        response = self.client.get(
            UNPAYWALL_API.format(doi=doi),
            params={"email": self.unpaywall_email},
        )
        if response.status_code >= 400:
            return None
        best = response.json().get("best_oa_location") or {}
        return best.get("url_for_pdf")

    def _openalex_metadata(self, doi: str) -> dict[str, object]:
        response = self.client.get(OPENALEX_API.format(doi=doi))
        if response.status_code >= 400:
            return {}
        data = response.json()
        authors = [
            authorship.get("author", {}).get("display_name")
            for authorship in data.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        location = data.get("best_oa_location") or {}
        return {
            "title": data.get("title"),
            "authors": authors,
            "abstract": inverted_index_to_text(data.get("abstract_inverted_index")),
            "pdf_url": location.get("pdf_url"),
            "landing_url": data.get("doi"),
        }

    def _download_pdf(self, url: str) -> bytes:
        response = self.browser.get(url, timeout=self.timeout, allow_redirects=True)
        if response.status_code >= 400:
            raise RetrievalError(f"PDF download failed: HTTP {response.status_code} for {url}")
        content_type = response.headers.get("content-type", "").lower()
        content = response.content
        if not content.startswith(b"%PDF") and "pdf" not in content_type:
            raise RetrievalError(f"Expected PDF, got {content_type or 'unknown content type'}")
        return content


def parse_arxiv_metadata(xml_text: str) -> tuple[str | None, list[str], str | None]:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None, [], None
    title = clean_space(entry.findtext("atom:title", default="", namespaces=ns))
    summary = clean_space(entry.findtext("atom:summary", default="", namespaces=ns))
    authors = [
        clean_space(author.findtext("atom:name", default="", namespaces=ns))
        for author in entry.findall("atom:author", ns)
    ]
    return title or None, [a for a in authors if a], summary or None


def inverted_index_to_text(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[str | None] = [None] * (max(max(pos) for pos in index.values()) + 1)
    for word, positions in index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(word for word in words if word)


def clean_abstract(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"</?jats:[^>]+>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return clean_space(unescape(value))


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_jats_text(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    body = next((element for element in root.iter() if local_name(element.tag) == "body"), None)
    if body is None:
        return None

    segments: list[str] = []
    seen: set[str] = set()
    for element in body.iter():
        name = local_name(element.tag)
        if name not in {"title", "p", "caption"}:
            continue
        text = clean_space(" ".join(element.itertext()))
        if text and text not in seen:
            segments.append(text)
            seen.add(text)

    full_text = "\n\n".join(segments)
    return full_text or None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def title_from_pdf_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\?.*$", "", tail)
    tail = re.sub(r"\.pdf$", "", tail, flags=re.I)
    return clean_space(unescape(tail.replace("-", " ").replace("_", " "))) or "PDF document"


def split_authors(value: str) -> list[str]:
    return [author.strip() for author in re.split(r";|,", value) if author.strip()]


def first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def rxiv_doi_candidates(doi: str) -> list[str]:
    unversioned = re.sub(r"v\d+$", "", doi, flags=re.I)
    if unversioned == doi:
        return [doi]
    return [doi, unversioned]
