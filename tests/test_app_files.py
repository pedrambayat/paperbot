from paperbot.app import detect_pdf_files, slack_pdf_ref
from paperbot.models import PaperKind


def test_detect_pdf_files_allows_file_share_events():
    event = {
        "files": [
            {"id": "F123", "mimetype": "application/pdf", "name": "paper.pdf"},
            {"id": "F456", "mimetype": "text/plain", "name": "notes.txt"},
            {"id": "F789", "mimetype": "application/octet-stream", "name": "appendix.pdf"},
        ]
    }

    assert [file_info["id"] for file_info in detect_pdf_files(event)] == ["F123", "F789"]


def test_slack_pdf_ref_uses_file_id_for_dedupe():
    ref = slack_pdf_ref(
        {
            "id": "F123",
            "permalink": "https://example.slack.com/files/U123/F123/paper.pdf",
            "url_private_download": "https://files.slack.com/files-pri/T123-F123/download/paper.pdf",
        }
    )

    assert ref.kind == PaperKind.PDF
    assert ref.identifier == "F123"
    assert ref.canonical_id == "pdf:f123"
    assert ref.source_url == "https://example.slack.com/files/U123/F123/paper.pdf"
