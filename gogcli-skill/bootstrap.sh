#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap gogcli on the HOST from existing NemoClaw Gmail credentials.
# No new OAuth consent flow needed — reuses the same client + refresh token.
#
# After this runs, call setup.sh to push gogcli into the sandbox.
#
# Usage:
#   GOG_KEYRING_PASSWORD=<pw> ./gogcli-skill/bootstrap.sh <gmail-address>
#
# gmail-address        — the Gmail account the refresh token belongs to
# GOG_KEYRING_PASSWORD — encrypts the local token file (your choice, keep for setup.sh)

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_FILE="$HOME/.nemoclaw/credentials.json"
GOG_BIN="${GOG_BIN:-}"
EMAIL="${1:-${GOG_EMAIL:-}}"

if [[ -z "$EMAIL" ]]; then
  echo "Error: Gmail address required."
  echo "  $0 you@gmail.com"
  exit 1
fi

# ── Locate gog binary ─────────────────────────────────────────────────────────

if [[ -z "$GOG_BIN" ]]; then
  for candidate in \
    "$(command -v gog 2>/dev/null || true)" \
    "$HOME/demo/gogcli/bin/gog" \
    "$(dirname "$(dirname "$SKILL_DIR")")/gogcli/bin/gog"; do
    if [[ -x "$candidate" ]]; then
      GOG_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$GOG_BIN" ]]; then
  echo "Error: gog binary not found. Build it first:"
  echo "  cd ~/demo/gogcli && make"
  exit 1
fi

echo "Using: $GOG_BIN"

# ── Validate inputs ───────────────────────────────────────────────────────────

if [[ ! -f "$CREDS_FILE" ]]; then
  echo "Error: $CREDS_FILE not found"
  exit 1
fi

if [[ -z "${GOG_KEYRING_PASSWORD:-}" ]]; then
  echo "Error: GOG_KEYRING_PASSWORD is required."
  echo "  export GOG_KEYRING_PASSWORD=<choose-any-password>"
  exit 1
fi

# ── Read NemoClaw credentials ─────────────────────────────────────────────────

CLIENT_ID="$(python3 -c "import json,sys; d=json.load(open('$CREDS_FILE')); print(d['GMAIL_CLIENT_ID'])")"
CLIENT_SECRET="$(python3 -c "import json,sys; d=json.load(open('$CREDS_FILE')); print(d['GMAIL_CLIENT_SECRET'])")"
REFRESH_TOKEN="$(python3 -c "import json,sys; d=json.load(open('$CREDS_FILE')); print(d['GMAIL_REFRESH_TOKEN'])")"

echo "Account: $EMAIL"

# ── Write gogcli credentials.json ─────────────────────────────────────────────

GOG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gogcli"
mkdir -p "$GOG_CONFIG_DIR"
chmod 700 "$GOG_CONFIG_DIR"

GOGCLI_CREDS="$GOG_CONFIG_DIR/credentials.json"
python3 -c "
import json
creds = {'client_id': '${CLIENT_ID}', 'client_secret': '${CLIENT_SECRET}'}
with open('${GOGCLI_CREDS}', 'w') as f:
    json.dump(creds, f, indent=2)
    f.write('\n')
"
chmod 600 "$GOGCLI_CREDS"
echo "Wrote $GOGCLI_CREDS"

# ── Import refresh token into keyring ─────────────────────────────────────────

TOKEN_FILE="$(mktemp /tmp/gog-token-XXXXXX.json)"
python3 -c "
import json
tok = {
    'email': '${EMAIL}',
    'refresh_token': '${REFRESH_TOKEN}',
    'services': ['gmail', 'calendar', 'drive'],
}
with open('${TOKEN_FILE}', 'w') as f:
    json.dump(tok, f, indent=2)
    f.write('\n')
"
chmod 600 "$TOKEN_FILE"

echo "Importing token into keyring..."
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
GOG_KEYRING_BACKEND=file \
GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD" \
"$GOG_BIN" auth tokens import "$TOKEN_FILE"

rm -f "$TOKEN_FILE"

# ── Verify ────────────────────────────────────────────────────────────────────

echo "Verifying..."
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
GOG_KEYRING_BACKEND=file \
GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD" \
"$GOG_BIN" auth list

echo ""
echo "gogcli bootstrapped for: $EMAIL"
echo ""
echo "Next: push into sandbox:"
echo "  GOG_KEYRING_PASSWORD=\$GOG_KEYRING_PASSWORD ./gogcli-skill/setup.sh <sandbox-name> $GOG_BIN"
