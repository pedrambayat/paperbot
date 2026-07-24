# Paperbot

Slack bot that auto-summarizes scientific papers shared in a lab channel. Post a
link to essentially any journal article (Nature, Cell, Science, PNAS, arXiv,
bioRxiv/medRxiv, a DOI, or a direct PDF URL) or upload a PDF, and Paperbot
retrieves the paper, summarizes it with an LLM, and replies in-thread with a
structured summary (TL;DR, problem, method, result, limitations). SQLite
dedupes so re-posts point back to the original summary.

It runs as a single long-lived process using Slack **Socket Mode** — no public
URL needed — so it can live on any always-on machine.

## 1. Create the Slack app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**. Name it (e.g. `paperbot`), pick your workspace.
2. **Socket Mode → Enable.** Generate an app-level token with the `connections:write` scope → this is `SLACK_APP_TOKEN` (`xapp-…`).
3. **OAuth & Permissions → Scopes → Bot Token Scopes**, add: `channels:history`, `chat:write`, `files:read`, `links:read`.
4. **Event Subscriptions → Enable**, and under **Subscribe to bot events** add `message.channels`.
5. **Install to Workspace**, then copy the **Bot User OAuth Token** → this is `SLACK_BOT_TOKEN` (`xoxb-…`).
6. In Slack, invite the bot to your channel (`/invite @paperbot`) and get the channel ID (channel name → About → bottom, looks like `C0…`) → this is `PAPERBOT_CHANNEL_ID`.

## 2. Install and configure

Requires Python >= 3.11.

```bash
git clone git@github.com:pedrambayat/paperbot.git
cd paperbot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in the tokens from step 1 + your OpenAI key
```

`OPENAI_MODEL` defaults to `gpt-5-mini` to keep summaries cheap. Set
`UNPAYWALL_EMAIL` so bare-DOI links can use the Unpaywall open-access lookup.

## 3. Run

```bash
paperbot
```

That's it — post an arXiv link in the channel and a summary should appear
in-thread within a few seconds.

### Run as a service (Linux / systemd)

`deploy/paperbot.service` is a ready-to-edit systemd unit that loads `.env`,
runs the bot from the venv, and restarts it on crash or reboot:

```bash
sudo cp deploy/paperbot.service /etc/systemd/system/paperbot.service
# edit the paths and User in the unit to match your checkout
sudo systemctl daemon-reload
sudo systemctl enable --now paperbot
journalctl -u paperbot -f   # watch it live
```

## Testing without Slack or OpenAI

`paperbot-smoke` runs the full detect → retrieve → summarize pipeline from the
command line. By default it uses a free dry-run summarizer (no OpenAI key, no
token spend):

```bash
paperbot-smoke "https://arxiv.org/abs/2401.01234"
paperbot-smoke "10.1038/s41586-024-00000-0"        # DOIs work too
paperbot-smoke --real "https://arxiv.org/abs/..."  # real OpenAI summary
```

Unit tests:

```bash
pytest
```

## Retrieval notes

- **Any journal link works.** arXiv, bioRxiv/medRxiv, doi.org, bare DOIs, and
  nature.com URLs are recognized directly. Any *other* link is treated as a
  candidate: Paperbot fetches the page and reads its Google Scholar/Highwire
  citation meta tags (`citation_doi`, `citation_pdf_url`) — which every major
  publisher embeds — to find the paper. Links with no such metadata (news,
  docs, GitHub, etc.) are ignored silently.
- **Institutional (subscription) full text.** For a DOI, Paperbot first tries
  open-access copies (Unpaywall/OpenAlex), then falls back to the publisher's
  own PDF using a browser-impersonating client (`curl_cffi`). Publisher access
  is IP-based, so running this on a **campus/residential network** gets
  subscription full text for paywalled Nature/Cell papers; a datacenter IP
  (e.g. AWS) will usually be blocked and degrade to an abstract-only summary.
  This is the main reason to prefer an on-campus host (e.g. Proxmox) over AWS.
- Retrieval always degrades gracefully — full text → abstract-only — and the
  summary is labeled with the evidence level actually used.
- If a host blocks the download entirely, upload the PDF directly to Slack;
  Paperbot downloads Slack-hosted PDFs with the bot token and summarizes the
  full document. This works from any host.
