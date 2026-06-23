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

# Deploy Paperbot to your Slack channel (recommended: serverless, free)

This is the full, start-to-finish setup. The serverless path is **free** (Vercel
Hobby + Upstash free tiers), **instant**, and runs **nothing at idle** — no server
to babysit. End result: paste a paper link in your channel and a summary appears
in-thread.

```
Slack message ─▶ POST /api/slack/events   (verify Slack signature, ack <3s, enqueue to QStash)
              ─▶ QStash ─▶ POST /api/process   (verify QStash, claim/dedup, retrieve → summarize → post)
```

It's one Flask app (`index.py`) deployed to Vercel; QStash defers the slow work
past Slack's 3-second deadline; Upstash Redis stores dedup state.

### What you'll need

- A **Slack workspace** where you can create an app.
- A free **Vercel** account + the CLI: `npm i -g vercel`.
- A free **Upstash** account (for Redis + QStash).
- An **OpenAI API key**.

### 1. Create the Slack app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**. Name it (e.g. `paperbot`), pick your workspace.
2. **OAuth & Permissions → Scopes → Bot Token Scopes**, add: `channels:history`, `chat:write`, `files:read`, `links:read`.
3. **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-…`) → this is `SLACK_BOT_TOKEN`.
4. **Basic Information → App Credentials → Signing Secret** → this is `SLACK_SIGNING_SECRET`.
5. In Slack, **invite the bot to your channel**: `/invite @paperbot`. Get the channel ID (channel name → About → bottom, looks like `C0XXXXXXX`) → this is `PAPERBOT_CHANNEL_ID`.

(Leave Event Subscriptions until step 5 — the Request URL must exist first.)

### 2. Create the Upstash resources

In the [Upstash console](https://console.upstash.com):

1. **Redis → Create Database** (free). Open it → **REST API** section → copy `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`.
2. **QStash** → copy `QSTASH_TOKEN`, and under **Signing Keys** copy `QSTASH_CURRENT_SIGNING_KEY` and `QSTASH_NEXT_SIGNING_KEY`.

> ⚠️ **QStash region matters.** QStash is multi-region with **separate tokens per region**. The global endpoint `https://qstash.upstash.io` routes to **EU**. If your QStash lives in **US**, you must set `QSTASH_URL=https://qstash-us-east-1.upstash.io` (step 4) or publishes fail with `user not found in this region`. EU users can use `https://qstash.upstash.io`.

### 3. Deploy to Vercel

From the repo root:

```bash
vercel deploy --prod    # links the project on first run; deploys index.py
```

Note the production URL it prints, e.g. `https://your-app.vercel.app`.

### 4. Set environment variables (then redeploy)

In **Vercel → your project → Settings → Environment Variables** (scope **Production**), add:

| Variable | Value / where to get it |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-…`) from step 1 |
| `SLACK_SIGNING_SECRET` | Slack Signing Secret from step 1 |
| `PAPERBOT_CHANNEL_ID` | Channel ID (`C0…`) from step 1 |
| `OPENAI_API_KEY` | Your OpenAI key |
| `OPENAI_MODEL` | `gpt-5-mini` (default; cheap) |
| `UPSTASH_REDIS_REST_URL` | from step 2 |
| `UPSTASH_REDIS_REST_TOKEN` | from step 2 |
| `QSTASH_TOKEN` | from step 2 |
| `QSTASH_CURRENT_SIGNING_KEY` | from step 2 |
| `QSTASH_NEXT_SIGNING_KEY` | from step 2 |
| `QSTASH_URL` | **US:** `https://qstash-us-east-1.upstash.io` · **EU:** `https://qstash.upstash.io` (see ⚠️ above) |
| `PAPERBOT_PROCESS_URL` | `https://your-app.vercel.app/api/process` (from step 3) |
| `UNPAYWALL_EMAIL` | *(optional)* your email, for Unpaywall DOI lookups |
| `PAPERBOT_DRY_RUN` | *(optional)* `1` to test the pipeline with placeholder summaries (no OpenAI cost); set `0` or omit for real summaries |

Then **redeploy** so the values take effect: `vercel deploy --prod`.

### 5. Wire up Slack Event Subscriptions

In your Slack app settings:

1. **Socket Mode → OFF.** (Required — the HTTP Request URL is ignored while Socket Mode is on. Socket Mode and the webhook are mutually exclusive.)
2. **Event Subscriptions → Enable**, set the **Request URL** to:
   `https://your-app.vercel.app/api/slack/events`
   Wait for the green **Verified ✓** (Slack sends a signed handshake; the endpoint answers it).
3. **Subscribe to bot events** → add **`message.channels`** → **Save Changes**.
4. If Slack shows a **reinstall** banner, reinstall the app.

### 6. Test

Post an **arXiv** link (e.g. `https://arxiv.org/abs/1706.03762`) in the channel. A full-text summary should appear in-thread within a few seconds.

### Notes & gotchas

- **Redeploy after any env var change** — Vercel bakes env vars at deploy time.
- **bioRxiv/medRxiv → abstract-only on Vercel.** Their Cloudflare blocks datacenter IPs even with browser impersonation, so full-text PDF fetch fails and Paperbot degrades to an abstract-only summary. arXiv and most other sources get full text. (Running the Socket Mode bot from a residential IP gets full-text bioRxiv — see below.)
- **Watch it live:** `vercel logs your-app.vercel.app`.
- `OPENAI_MODEL` defaults to `gpt-5-mini` to keep summaries inexpensive.

## Alternative: Socket Mode (long-running process)

The same codebase also runs as a persistent process via `paperbot` — useful for
local development, or running from a residential IP (which gets full-text bioRxiv).
This mode uses **Socket Mode** instead of the Events API and **SQLite** instead of
Redis. It additionally needs `SLACK_APP_TOKEN` (an app-level token, `xapp-…`, from
**Basic Information → App-Level Tokens** with the `connections:write` scope) and
Socket Mode **enabled** in the Slack app.

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill SLACK_BOT_TOKEN, SLACK_APP_TOKEN, PAPERBOT_CHANNEL_ID, OPENAI_API_KEY
paperbot
```

`deploy/com.pedrambayat.paperbot.plist` + `scripts/run.sh` show how to run it as a
hands-off macOS launchd service. Set `PAPERBOT_DRY_RUN=1` to run without calling
OpenAI (placeholder summaries).

## Local Checks

```bash
pytest
python -m compileall paperbot
```
