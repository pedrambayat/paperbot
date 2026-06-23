#!/bin/bash
# Launch Paperbot. Used by the launchd LaunchAgent, and works for manual runs too.
# launchd runs with a minimal environment, so this script resolves its own paths,
# loads .env, and runs the bot inside the project virtualenv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Load Slack/OpenAI tokens, channel id, model, etc. from .env
set -a
. "$REPO_DIR/.env"
set +a

# Run in the venv. ensure_tls_certs() pins certifi at startup, so no SSL setup needed.
exec "$REPO_DIR/.venv312/bin/paperbot"
