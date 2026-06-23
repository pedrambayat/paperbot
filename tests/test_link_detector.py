from paperbot.link_detector import detect_papers, extract_urls, normalize_doi
from paperbot.models import PaperKind


def test_extract_urls_strips_trailing_punctuation():
    assert extract_urls("Read https://arxiv.org/abs/2401.01234).") == [
        "https://arxiv.org/abs/2401.01234"
    ]


def test_detect_arxiv_abs_url():
    refs = detect_papers("new paper https://arxiv.org/abs/2401.01234v2")
    assert len(refs) == 1
    assert refs[0].kind == PaperKind.ARXIV
    assert refs[0].identifier == "2401.01234v2"
    assert refs[0].canonical_id == "arxiv:2401.01234"


def test_detect_biorxiv_doi_url():
    refs = detect_papers("https://www.biorxiv.org/content/10.1101/2024.01.02.123456v1")
    assert len(refs) == 1
    assert refs[0].kind == PaperKind.BIORXIV
    assert refs[0].identifier == "10.1101/2024.01.02.123456v1"
    assert refs[0].canonical_id == "biorxiv:10.1101/2024.01.02.123456"


def test_detect_biorxiv_pdf_url_strips_pdf_suffix():
    refs = detect_papers("https://www.biorxiv.org/content/10.1101/2024.01.02.123456v1.full.pdf")
    assert refs[0].kind == PaperKind.BIORXIV
    assert refs[0].identifier == "10.1101/2024.01.02.123456v1"
    assert refs[0].canonical_id == "biorxiv:10.1101/2024.01.02.123456"


def test_arxiv_versions_dedupe_to_one_ref():
    refs = detect_papers(
        "v1 https://arxiv.org/abs/2401.01234v1 and v2 https://arxiv.org/abs/2401.01234v2"
    )
    assert len(refs) == 1


def test_detect_slack_mrkdwn_link_once():
    refs = detect_papers(
        "<https://www.biorxiv.org/content/10.64898/2026.06.07.730684v2|paper>"
    )
    assert len(refs) == 1
    assert refs[0].kind == PaperKind.BIORXIV
    assert refs[0].identifier == "10.64898/2026.06.07.730684v2"


def test_detect_plain_doi():
    refs = detect_papers("Worth reading: 10.1038/s41586-024-00000-0")
    assert refs[0].kind == PaperKind.DOI
    assert refs[0].identifier == "10.1038/s41586-024-00000-0"


def test_detect_generic_pdf_url():
    refs = detect_papers("Read https://example.org/papers/cool-paper.pdf")
    assert len(refs) == 1
    assert refs[0].kind == PaperKind.PDF
    assert refs[0].identifier == "https://example.org/papers/cool-paper.pdf"


def test_normalize_doi():
    assert normalize_doi("DOI:10.1101/ABC.") == "10.1101/abc"
