from paperbot.retriever import (
    clean_abstract,
    extract_jats_text,
    inverted_index_to_text,
    parse_arxiv_metadata,
    rxiv_doi_candidates,
    title_from_pdf_url,
)


def test_parse_arxiv_metadata():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title> A useful paper </title>
        <summary> This is the abstract. </summary>
        <author><name>Ada Lovelace</name></author>
        <author><name>Grace Hopper</name></author>
      </entry>
    </feed>
    """
    title, authors, abstract = parse_arxiv_metadata(xml)
    assert title == "A useful paper"
    assert authors == ["Ada Lovelace", "Grace Hopper"]
    assert abstract == "This is the abstract."


def test_clean_abstract_removes_jats_tags():
    assert clean_abstract("<jats:p>Hello <i>world</i>.</jats:p>") == "Hello world ."


def test_inverted_index_to_text():
    index = {"deep": [0], "learning": [1], "works": [2]}
    assert inverted_index_to_text(index) == "deep learning works"


def test_rxiv_doi_candidates_try_unversioned_fallback():
    assert rxiv_doi_candidates("10.64898/2026.06.07.730684v2") == [
        "10.64898/2026.06.07.730684v2",
        "10.64898/2026.06.07.730684",
    ]
    assert rxiv_doi_candidates("10.64898/2026.06.07.730684") == [
        "10.64898/2026.06.07.730684"
    ]


def test_extract_jats_text_from_body():
    xml = """<article xmlns="http://jats.nlm.nih.gov">
      <front><article-meta><title-group><article-title>Skip front matter</article-title></title-group></article-meta></front>
      <body>
        <sec><title>Introduction</title><p>First paragraph.</p></sec>
        <sec><title>Results</title><p>Second <italic>paragraph</italic>.</p></sec>
      </body>
    </article>"""

    assert extract_jats_text(xml) == "Introduction\n\nFirst paragraph.\n\nResults\n\nSecond paragraph ."


def test_title_from_pdf_url():
    assert title_from_pdf_url("https://example.org/my-paper_v2.pdf?download=1") == "my paper v2"
