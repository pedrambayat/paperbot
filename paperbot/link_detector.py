from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from .models import PaperKind, PaperRef

URL_RE = re.compile(r"https?://[^\s<>\"|]+")
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
# nature.com article slugs map directly to a DOI: 10.1038/<slug>.
NATURE_ARTICLE_RE = re.compile(r"nature\.com/articles/(?P<slug>[a-z0-9][a-z0-9.-]*)", re.I)
TRAILING_PUNCTUATION = ".,;:)]}>"
DOI_URL_SUFFIXES = (".full.pdf", ".full", ".pdf")

# Hosts that are common in lab chat but never journal article pages. Everything
# else that isn't matched by a specific rule becomes a WEBPAGE candidate, which
# the retriever resolves via the page's citation meta tags (or drops silently).
NON_PAPER_HOSTS = {
    "slack.com",
    "google.com",
    "github.com",
    "gitlab.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "wikipedia.org",
    "zoom.us",
    "notion.so",
    "dropbox.com",
}


def host_matches(host: str, domains: set[str] | frozenset[str]) -> bool:
    host = host.lower().rsplit(":", 1)[0]
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(text):
        url = match.group(0).rstrip(TRAILING_PUNCTUATION)
        if url not in urls:
            urls.append(url)
    return urls


def detect_papers(text: str) -> list[PaperRef]:
    refs: list[PaperRef] = []
    seen: set[str] = set()
    url_spans: list[tuple[int, int]] = []

    for url_match in URL_RE.finditer(text):
        url = url_match.group(0).rstrip(TRAILING_PUNCTUATION)
        url_spans.append(url_match.span())
        ref = paper_ref_from_url(url)
        if ref and ref.canonical_id not in seen:
            refs.append(ref)
            seen.add(ref.canonical_id)

    text_without_urls = mask_spans(text, url_spans)
    for doi_match in DOI_RE.finditer(text_without_urls):
        doi = normalize_doi(doi_match.group(0))
        ref = PaperRef(PaperKind.DOI, doi, f"https://doi.org/{doi}")
        if ref.canonical_id not in seen:
            refs.append(ref)
            seen.add(ref.canonical_id)

    return refs


def mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def paper_ref_from_url(url: str) -> PaperRef | None:
    clean_url = url.rstrip(TRAILING_PUNCTUATION)
    parsed = urlparse(clean_url)
    host = parsed.netloc.lower()
    path = unquote(parsed.path)

    arxiv = ARXIV_RE.search(clean_url)
    if arxiv:
        arxiv_id = arxiv.group("id").removesuffix(".pdf")
        return PaperRef(PaperKind.ARXIV, arxiv_id, clean_url)

    doi = doi_from_url(clean_url)
    if doi:
        if "biorxiv.org" in host:
            return PaperRef(PaperKind.BIORXIV, doi, clean_url)
        if "medrxiv.org" in host:
            return PaperRef(PaperKind.MEDRXIV, doi, clean_url)
        return PaperRef(PaperKind.DOI, doi, clean_url)

    if host == "doi.org" and path.strip("/"):
        return PaperRef(PaperKind.DOI, normalize_doi(path.strip("/")), clean_url)

    nature = NATURE_ARTICLE_RE.search(clean_url)
    if nature:
        return PaperRef(PaperKind.DOI, normalize_doi(f"10.1038/{nature.group('slug')}"), clean_url)

    if path.lower().endswith(".pdf"):
        return PaperRef(PaperKind.PDF, clean_url, clean_url)

    if host and not host_matches(host, NON_PAPER_HOSTS):
        return PaperRef(PaperKind.WEBPAGE, webpage_identifier(parsed), clean_url)

    return None


def webpage_identifier(parsed) -> str:  # type: ignore[no-untyped-def]
    """Stable identity for a webpage candidate: host + path, no query/fragment."""
    host = parsed.netloc.lower().removeprefix("www.")
    return f"{host}{unquote(parsed.path).rstrip('/')}"


def doi_from_url(url: str) -> str | None:
    decoded = unquote(url)
    match = DOI_RE.search(decoded)
    if not match:
        return None
    return normalize_doi(match.group(0))


def normalize_doi(doi: str) -> str:
    value = doi.strip().rstrip(TRAILING_PUNCTUATION)
    value = re.sub(r"^doi:", "", value, flags=re.I)
    for suffix in DOI_URL_SUFFIXES:
        if value.lower().endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value.lower()
