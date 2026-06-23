from paperbot.core import process_job, summarize_and_post
from paperbot.events import job_from_event
from paperbot.models import PaperKind, PaperRef, RetrievalMode, RetrievedPaper
from paperbot.retriever import RetrievalError
from paperbot.summarizer import DryRunSummarizer

REF = PaperRef(PaperKind.ARXIV, "2401.01234", "https://arxiv.org/abs/2401.01234")


class FakeStore:
    def __init__(self, existing=None):
        self.existing = existing
        self.saved = []

    def get(self, canonical_id):
        return self.existing

    def save(self, paper, summary, slack_channel, slack_ts):
        self.saved.append((paper, summary, slack_channel, slack_ts))


class FakeClient:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ts": "9.9"}


def _paper():
    return RetrievedPaper(ref=REF, title="A Paper", mode=RetrievalMode.FULL_TEXT)


def test_new_paper_posts_summary_and_saves_with_returned_ts():
    store, client = FakeStore(existing=None), FakeClient()
    summarize_and_post(
        ref=REF,
        paper_factory=_paper,
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        channel_id="C1",
        thread_ts="1.1",
    )
    assert len(client.posts) == 1
    assert client.posts[0]["channel"] == "C1"
    assert client.posts[0]["thread_ts"] == "1.1"
    assert store.saved and store.saved[0][3] == "9.9"


def test_duplicate_paper_posts_notice_and_does_not_retrieve_or_save():
    store, client = FakeStore(existing={"slack_ts": "5.5"}), FakeClient()
    retrieved = []

    def factory():
        retrieved.append(True)
        return _paper()

    summarize_and_post(
        ref=REF,
        paper_factory=factory,
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        channel_id="C1",
        thread_ts="1.1",
    )
    assert retrieved == []  # dedup short-circuits before any network retrieval
    assert store.saved == []
    assert len(client.posts) == 1  # only the "already summarized" notice


class FakeRetriever:
    def __init__(self, paper=None, error=None):
        self.paper = paper
        self.error = error

    def retrieve(self, ref):
        if self.error:
            raise self.error
        return self.paper


def _job(text="https://arxiv.org/abs/2401.01234", files=None):
    return {"channel": "C1", "thread_ts": "1.1", "text": text, "files": files or []}


def test_process_job_summarizes_link_and_saves():
    store, client = FakeStore(existing=None), FakeClient()
    process_job(
        _job(),
        retriever=FakeRetriever(paper=_paper()),
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        bot_token="xoxb",
    )
    assert len(client.posts) == 1
    assert store.saved


def test_process_job_posts_failure_when_retrieval_errors():
    store, client = FakeStore(existing=None), FakeClient()
    process_job(
        _job(),
        retriever=FakeRetriever(error=RetrievalError("blocked")),
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        bot_token="xoxb",
        post_failures=True,
    )
    assert store.saved == []
    assert len(client.posts) == 1
    assert "Could not" in client.posts[0]["text"]


def test_process_job_suppresses_failure_when_disabled():
    store, client = FakeStore(existing=None), FakeClient()
    process_job(
        _job(),
        retriever=FakeRetriever(error=RetrievalError("blocked")),
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        bot_token="xoxb",
        post_failures=False,
    )
    assert client.posts == []


def test_process_job_handles_pdf_file_via_injected_retriever():
    store, client = FakeStore(existing=None), FakeClient()
    pdf_file = {"id": "F1", "name": "paper.pdf", "mimetype": "application/pdf"}
    calls = []

    def fake_pdf_retriever(file_info, ref, bot_token):
        calls.append((file_info["id"], bot_token))
        return _paper()

    process_job(
        _job(text="", files=[pdf_file]),
        retriever=FakeRetriever(),
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        bot_token="xoxb-token",
        slack_pdf_retriever=fake_pdf_retriever,
    )
    assert calls == [("F1", "xoxb-token")]
    assert len(client.posts) == 1
    assert store.saved


def test_job_from_event_output_is_consumable_by_process_job():
    # End-to-end contract: the job dict produced by function A's logic must be
    # exactly what function B's worker consumes.
    event = {"type": "message", "channel": "C1", "ts": "1.1", "text": "https://arxiv.org/abs/2401.01234"}
    job = job_from_event({"type": "event_callback", "event": event}, "C1")
    store, client = FakeStore(existing=None), FakeClient()
    process_job(
        job,
        retriever=FakeRetriever(paper=_paper()),
        store=store,
        summarizer=DryRunSummarizer(),
        client=client,
        bot_token="xoxb",
    )
    assert len(client.posts) == 1
    assert store.saved
