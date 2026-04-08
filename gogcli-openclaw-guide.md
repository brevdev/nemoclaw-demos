# Connecting Google Workspace to OpenClaw in a NemoClaw Sandbox

This guide walks you through giving an OpenClaw agent access to Gmail, Calendar, and Drive using `gogcli` — a Google Workspace CLI — running inside an OpenShell sandbox. By the end, your agent will be able to search your inbox, summarize calendar events, and browse Drive files on your behalf, with every outbound API call subject to NemoClaw's egress approval flow.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running OpenClaw sandbox | A working OpenShell sandbox with OpenClaw. See [NemoClaw hello-world setup](https://github.com/NVIDIA/NemoClaw). |
| NemoClaw credentials | `~/.nemoclaw/credentials.json` with `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`. These are created during NemoClaw onboarding. |
| Go toolchain | Go 1.21+ on the host to build the `gog` binary. |
| gogcli source | Clone or have the `gogcli` repo available locally (e.g. `~/demo/gogcli`). |

## Part 1: Build the gog Binary (On the Host)

```bash
cd ~/demo/gogcli
make
```

The binary is written to `bin/gog`. Verify it works:

```bash
./bin/gog --version
```

## Part 2: Bootstrap Credentials on the Host

The bootstrap script reads your existing NemoClaw OAuth credentials and imports them into a local gogcli keyring. No new OAuth consent screen is required.

```bash
cd ~/demo/nemoclaw-demos
GOG_KEYRING_PASSWORD=<password> \
  ./gogcli-skill/bootstrap.sh your@gmail.com
```

`GOG_KEYRING_PASSWORD` is the password used to encrypt the local token file. Use the same value in every subsequent step.

Verify the account was registered:

```bash
GOG_KEYRING_BACKEND=file GOG_KEYRING_PASSWORD=nemoclaw-demo \
  ~/demo/gogcli/bin/gog auth list
```

## Part 3: Start the Token Server and Push gogcli into the Sandbox

`setup-gogcli.sh` does four things in one step:

1. Starts `gog-token-server.py` on the host — this holds the refresh token and serves short-lived access tokens on demand. The token server listens on port `9100` by default.
2. Uploads a thin `gog` wrapper script into the sandbox at `/sandbox/.config/gogcli/gog`. The wrapper calls the token server on every invocation, so the sandbox never holds any credentials.
3. Applies the network policy — allows `gmail.googleapis.com`, `calendar.googleapis.com`, `drive.googleapis.com`, and the host token server endpoint. OAuth token exchange (`oauth2.googleapis.com`) is **not** needed from inside the sandbox.
4. Patches the sandbox `SOUL.md` so the agent knows `gog` is available.

```bash
cd ~/demo/nemoclaw-demos
GOG_KEYRING_PASSWORD=<password> \
  ./gogcli-skill/setup.sh <sandbox-name> ~/demo/gogcli/bin/gog
```

Replace `<sandbox-name>` with your OpenShell sandbox name (e.g. `email`).

The token server (`gogcli-skill/gog-token-server.py` in this repo) runs in the background on the host. Its log is at `~/.config/gogcli/token-server.log`.

Verify inside the sandbox:

```bash
openshell sandbox connect <sandbox-name>
/sandbox/.config/gogcli/gog auth list
```

## Part 4: Upload the gogcli Skill

The skill file tells the OpenClaw agent what `gog` commands are available and how to call them. Upload it from the `nemoclaw-demos` repo:

```bash
openshell sandbox upload <sandbox-name> \
  /path/to/nemoclaw-demos/gogcli-skill/SKILL.md \
  /sandbox/.openclaw/skills/gogcli/
```

Then restart the OpenClaw gateway to pick up the new skill:

```bash
openclaw gateway stop
sleep 3
nohup openclaw gateway run \
  --allow-unconfigured --dev \
  --bind loopback --port 18789 \
  --token hello \
  > /tmp/gateway.log 2>&1 &
```

## Trying It Out

Open the OpenClaw web UI and try these prompts. Each one triggers a network egress approval in the NemoClaw TUI the first time that API is contacted:

- "Search my Gmail for unread messages from NVIDIA and summarize them." *(triggers Gmail + OAuth approval)*
- "Check my calendar for meetings tomorrow and give me a prep briefing." *(triggers Calendar approval)*
- "List the most recent files in my Google Drive." *(triggers Drive approval)*

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `gog auth list` shows no accounts | Re-run `bootstrap-gogcli.sh`. Check that `~/.nemoclaw/credentials.json` contains `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`. |
| `gog: could not reach token server` inside sandbox | The host-side token server isn't running. Re-run `setup-gogcli.sh` to restart it, or check `~/.config/gogcli/token-server.log` for errors. |
| `l7_decision=deny` for `curl` to host IP | The `google_token_server` policy block is missing or has the wrong IP/port. Re-run `setup-gogcli.sh` to reapply. |
| `l7_decision=deny` for `gmail.googleapis.com` | The Google API policy blocks weren't applied. Re-run `setup-gogcli.sh` and confirm `google_gmail` / `google_calendar` / `google_drive` appear in `openshell policy get --full <sandbox-name>`. |
| Agent doesn't know about `gog` | Confirm `SKILL.md` was uploaded to `/sandbox/.openclaw/skills/gogcli/` and the gateway was restarted. |
| Gmail send fails | Only `gmail.readonly` scope is enabled in the current GCP project. Read and search operations work; sending requires the Gmail send scope to be added to your OAuth client. |
