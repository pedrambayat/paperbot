from paperbot.events import job_from_event, url_verification_challenge

CHANNEL = "C123"


def _callback(event: dict) -> dict:
    return {"type": "event_callback", "event": event}


def test_url_verification_returns_challenge():
    payload = {"type": "url_verification", "challenge": "abc123"}
    assert url_verification_challenge(payload) == "abc123"


def test_non_challenge_payload_returns_none():
    assert url_verification_challenge(_callback({"type": "message", "text": "hi"})) is None


def test_message_with_arxiv_link_produces_job():
    event = {"type": "message", "channel": CHANNEL, "ts": "1.1", "text": "look https://arxiv.org/abs/2401.01234"}
    job = job_from_event(_callback(event), CHANNEL)
    assert job is not None
    assert job["channel"] == CHANNEL
    assert job["thread_ts"] == "1.1"
    assert "arxiv.org/abs/2401.01234" in job["text"]


def test_message_in_other_channel_is_ignored():
    event = {"type": "message", "channel": "OTHER", "ts": "1.1", "text": "https://arxiv.org/abs/2401.01234"}
    assert job_from_event(_callback(event), CHANNEL) is None


def test_bot_message_is_ignored():
    event = {"type": "message", "channel": CHANNEL, "ts": "1.1", "bot_id": "B1", "text": "https://arxiv.org/abs/2401.01234"}
    assert job_from_event(_callback(event), CHANNEL) is None


def test_edited_message_subtype_is_ignored():
    event = {"type": "message", "subtype": "message_changed", "channel": CHANNEL, "ts": "1.1", "text": "https://arxiv.org/abs/2401.01234"}
    assert job_from_event(_callback(event), CHANNEL) is None


def test_message_without_paper_returns_none():
    event = {"type": "message", "channel": CHANNEL, "ts": "1.1", "text": "no papers here, just chatting"}
    assert job_from_event(_callback(event), CHANNEL) is None


def test_thread_reply_preserves_thread_ts():
    event = {"type": "message", "channel": CHANNEL, "ts": "2.2", "thread_ts": "1.1", "text": "https://arxiv.org/abs/2401.01234"}
    job = job_from_event(_callback(event), CHANNEL)
    assert job["thread_ts"] == "1.1"


def test_pdf_file_share_produces_job_with_files():
    file_info = {"id": "F1", "name": "paper.pdf", "mimetype": "application/pdf", "url_private_download": "https://files.slack.com/x.pdf"}
    event = {"type": "message", "subtype": "file_share", "channel": CHANNEL, "ts": "1.1", "text": "", "files": [file_info]}
    job = job_from_event(_callback(event), CHANNEL)
    assert job is not None
    assert job["files"] and job["files"][0]["id"] == "F1"


def test_non_pdf_file_without_link_returns_none():
    file_info = {"id": "F1", "name": "data.csv", "mimetype": "text/csv"}
    event = {"type": "message", "subtype": "file_share", "channel": CHANNEL, "ts": "1.1", "text": "", "files": [file_info]}
    assert job_from_event(_callback(event), CHANNEL) is None
