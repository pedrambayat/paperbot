# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Paperbot is a Slack bot that auto-summarizes scientific papers shared in one configured lab channel. It listens (Socket Mode) for messages containing paper links/DOIs or uploaded PDFs, retrieves the paper, summarizes it with an LLM, and posts a structured summary in-thread. SQLite is used for dedupe.

## Commands

```bash
# Setup (editable install; package dir is paperbot/ inside this repo)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in tokens

# Run the Slack bot (needs SLACK_BOT_TOKEN, SLACK_APP_TOKEN, PAPERBOT_CHANNEL_ID)
paperbot

# Local smoke test — exercises detect -> retrieve -> summarize without Slack.
# Defaults to the free DryRunSummarizer (no OpenAI key, no token spend).
paperbot-smoke "https://arxiv.org/abs/2401.01234"
paperbot-smoke --json "10.1038/s41586-024-00000-0"   # machine-readable output
OPENAI_API_KEY=sk-... paperbot-smoke --real "https://arxiv.org/abs/2401.01234"

# Tests
pytest                                  # full suite
pytest tests/test_link_detector.py      # one file
pytest tests/test_link_detector.py::test_detect_arxiv_abs_url   # one test
python -m compileall paperbot           # syntax check
```

Use `paperbot-smoke` as the primary dev loop — it runs the full pipeline minus Slack and minus model cost.

## Architecture

The message-handling pipeline is a fixed sequence, each stage in its own module:

1. **`link_detector.py`** — `detect_papers(text)` parses raw message text into `PaperRef`s. URL spans are masked out before bare-DOI scanning so a DOI inside a URL isn't double-counted. Recognizes arXiv, bioRxiv/medRxiv (by host), `doi.org`, generic DOIs, and `.pdf` links.
2. **`retriever.py`** — `PaperRetriever.retrieve(ref)` dispatches on `PaperKind` and produces a `RetrievedPaper`. Each source has a **graceful-degradation chain**: try to download the full-text PDF; if blocked, fall back (rxiv → JATS/XML full text → abstract-only; DOI → Unpaywall PDF → OpenAlex metadata/PDF → abstract-only). `mode` records whether full text or abstract was obtained. Two HTTP clients: `self.client` (httpx) for JSON metadata APIs, and `self.browser` (a `curl_cffi` Chrome-impersonating session) for **all full-text content downloads** — bioRxiv/medRxiv and many publishers serve PDFs from behind a Cloudflare WAF that blocks plain HTTP clients on TLS fingerprint, so `_download_pdf`/`_download_jats_text` must use `self.browser`.
3. **`summarizer.py`** — `Summarizer` interface with two impls: `OpenAISummarizer` (OpenAI **Responses API**, attaches the PDF as a base64 `input_file` when bytes are present, otherwise sends metadata/abstract text) and `DryRunSummarizer` (deterministic placeholder, no API call). The prompt asks for strict JSON with the `PaperSummary` fields; non-JSON responses raise `ValueError`.
4. **`store.py`** — `SummaryStore`, a thin SQLite wrapper. Dedupe key is `PaperRef.canonical_id`.
5. **`formatter.py`** — builds Slack Block Kit payloads (`slack_blocks`, `failure_blocks`, `duplicate_blocks`).
6. **`app.py`** — wires it together: `create_app(settings)` registers the Slack `message` handler; `summarize_and_post()` is the per-paper unit (dedupe check → retrieve via a `paper_factory` lambda → summarize → post → save). `main()` starts the `SocketModeHandler`. `main()` first calls `ensure_tls_certs()`, which sets `SSL_CERT_FILE` to certifi's bundle — `slack_sdk` uses `urllib`, whose default SSL store is empty on the macOS python.org build, causing `CERTIFICATE_VERIFY_FAILED`. This makes the bot start cleanly in any shell/venv. (The interpreter itself was also fixed once via `Install Certificates.command`, but don't rely on that being present elsewhere.)

`models.py` holds the shared dataclasses/enums (`PaperRef`, `RetrievedPaper`, `PaperSummary`, `PaperKind`, `RetrievalMode`) that flow through every stage. `config.py` centralizes env parsing in `Settings.from_env()`.

### Key conventions

- **`canonical_id`** (`models.py`) is the dedupe/identity key everywhere: `"{kind}:{identifier}"` with arXiv/rxiv version suffixes (`v\d+`) stripped, lowercased. Two links to different versions of the same paper collapse to one summary.
- **`RetrievalMode`** propagates source fidelity end-to-end: it drives the summarizer's instruction (full-text vs abstract-only), the `evidence_level` summary field, and the "Full text / Abstract only" label in Slack. Preserve it when adding retrieval paths.
- **`paper_factory` lambda** in `app.py` defers retrieval until *after* the dedupe check, so a duplicate link never triggers a network fetch.
- Retrieval is **best-effort**: helpers return `None` / empty dict on HTTP errors and the chain continues; only total failure raises `RetrievalError`. Don't convert these soft failures into hard raises.
- Slack PDF uploads are handled separately from links (`detect_pdf_files` / `retrieve_slack_pdf` in `app.py`) and download the private file using the bot token.

## Configuration notes

- All config is env-driven (`.env`, see `.env.example`). `PAPERBOT_DRY_RUN=1` skips OpenAI entirely. `OPENAI_MODEL` defaults to `gpt-5-mini` to keep routine summaries cheap.
- This project uses the **OpenAI** Responses API, not the Claude API — unlike the sibling projects described in the parent `~/CLAUDE.md`.
- Requires Python >= 3.11 (`pyproject.toml`); the checked-in venv is 3.12.
- Not a git repository.
