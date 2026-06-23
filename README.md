# Paperbot

Slack bot for summarizing papers shared in a lab channel. This implements the first development slice from `../1 - Rough Notes/paperbot.md`.

## MVP Decisions

- Trigger mode: automatic on links in one configured channel.
- Retrieval: arXiv, bioRxiv, medRxiv, direct PDF links, then DOI with Unpaywall/OpenAlex fallback.
- Slack uploads: PDF files uploaded directly to the watched channel are supported when `files:read` is granted.
- Paywalled papers: post a clearly labeled abstract-only summary when metadata is available.
- Persistence: SQLite is included from v1 for dedupe and future digests.
- LLM: OpenAI Responses API by default, using a cheaper mini-class model unless overridden.

## Setup

```bash
cd paperbot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `.env`, then run:

```bash
paperbot
```

## Local Smoke Test

Use the smoke command before connecting Slack:

```bash
paperbot-smoke "https://arxiv.org/abs/2401.01234"
```

Direct public PDF links are supported too:

```bash
paperbot-smoke "https://example.org/paper.pdf"
```

By default this retrieves the paper and uses the free dry-run summarizer, so it does not need an OpenAI API key and does not spend model tokens. To test a real model summary:

```bash
OPENAI_API_KEY=sk-... paperbot-smoke --real "https://arxiv.org/abs/2401.01234"
```

For DOI links, set `UNPAYWALL_EMAIL` so the open-access lookup can use Unpaywall:

```bash
UNPAYWALL_EMAIL=you@example.com paperbot-smoke "10.1038/s41586-024-00000-0"
```

For bioRxiv and medRxiv, Paperbot first tries the paper PDF. If that is blocked, it falls back to the public JATS/XML full text when available before degrading to abstract-only.

bioRxiv/medRxiv and many publishers serve full-text PDFs from behind Cloudflare, which blocks plain HTTP clients on their TLS fingerprint. Paperbot downloads full-text content with a browser-impersonating client (`curl_cffi`) so it can fetch the actual paper rather than degrading to abstract-only. If a host still blocks the download, upload the PDF file directly to Slack; Paperbot can download Slack-hosted PDFs with the bot token and summarize the full document.

## Required Slack App Settings

Use Socket Mode. The app needs:

- `SLACK_BOT_TOKEN`: bot token, usually `xoxb-...`
- `SLACK_APP_TOKEN`: app-level token, usually `xapp-...`
- `PAPERBOT_CHANNEL_ID`: the channel ID to watch

Bot scopes:

- `channels:history`
- `chat:write`
- `files:read`
- `links:read`
- `reactions:read` and `reactions:write` if status emoji mode is enabled later

Events:

- `message.channels`

## Environment

See `.env.example`.

Use `PAPERBOT_DRY_RUN=1` to run without calling OpenAI. The bot will still retrieve papers and post deterministic placeholder summaries.

`OPENAI_MODEL` defaults to `gpt-5-mini` in code and in `.env.example` to keep routine paper summaries inexpensive. Override it only when you want a higher-quality or account-specific model.

API keys needed:

- Local smoke test dry-run: no OpenAI key, no Slack tokens.
- Local smoke test with `--real`: `OPENAI_API_KEY`.
- Slack dry-run bot: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `PAPERBOT_CHANNEL_ID`.
- Slack real-summary bot: Slack tokens plus `OPENAI_API_KEY`.

## Run modes

Paperbot can run two ways from the same codebase:

- **Socket Mode** (`paperbot`): a long-running process (local, launchd, or any always-on host). Reacts instantly; uses SQLite for dedup. Needs `SLACK_APP_TOKEN`.
- **Serverless webhook** (`api/`): Slack Events API → Vercel functions. Nothing runs at idle; instant; free on Vercel Hobby. Uses Upstash Redis for dedup and QStash to defer work past Slack's 3-second ack. No `SLACK_APP_TOKEN`.

Both share the same retrieval/summarization core (`paperbot/core.py`, `paperbot/events.py`).

## Serverless deployment (Vercel + Upstash)

Real-time and free, with nothing running between events.

```
Slack message → /api/slack/events  (verify signature, ack <3s, enqueue to QStash)
              → QStash             → /api/process  (verify, dedup, retrieve+summarize+post)
```

1. **Upstash** (free): create a **Redis** database (copy `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`) and a **QStash** instance (copy `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY`).
2. **Deploy**: `vercel deploy` (the `api/*.py` files become functions; `requirements.txt` installs deps; `vercel.json` sets `maxDuration` to 300s).
3. **Set env vars** in Vercel (Project → Settings → Environment Variables): `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `PAPERBOT_CHANNEL_ID`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `UNPAYWALL_EMAIL`, the Upstash + QStash values above, and `PAPERBOT_PROCESS_URL=https://<your-app>.vercel.app/api/process`. Redeploy so the URL is picked up.
4. **Slack app**: enable **Event Subscriptions**, set the Request URL to `https://<your-app>.vercel.app/api/slack/events` (Slack will verify it via the handshake), and subscribe to the **`message.channels`** bot event. Copy the **Signing Secret** into `SLACK_SIGNING_SECRET`. Make sure the bot is in the watched channel.
5. **Test**: post an arXiv/bioRxiv link in the channel — the summary should appear in-thread within seconds.

Socket Mode can be left enabled or disabled; the webhook path does not use it.

## Local Checks

```bash
pytest
python -m compileall paperbot
```
