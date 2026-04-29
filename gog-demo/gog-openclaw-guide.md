# Connecting Google Workspace to OpenClaw in a NemoClaw Sandbox

This guide walks you through giving an OpenClaw agent access to Gmail, Calendar, and Drive using `gogcli` — a Google Workspace CLI — running inside an OpenShell sandbox. By the end, your agent will be able to search your inbox, summarize calendar events, and browse Drive files on your behalf, with every outbound API call subject to NemoClaw's egress approval flow.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running OpenClaw sandbox | A working OpenShell sandbox with OpenClaw. See [NemoClaw hello-world setup](https://github.com/NVIDIA/NemoClaw). |
| GCP OAuth credentials | A client secret JSON file downloaded from [Google Cloud Console](https://console.cloud.google.com) — see [Getting the GCP OAuth credentials JSON](gogcli-skill/README.md#getting-the-gcp-oauth-credentials-json). |
| Go toolchain | Go 1.21+ (installed automatically by `bootstrap.sh` if missing). |

## Part 1: Bootstrap (Build, Credentials, Token Server, Sandbox)

The bootstrap script handles everything end-to-end:

1. **Installs Go** if not found or below 1.21.
2. **Clones and builds `gogcli`** (if the binary isn't already present).
3. **Runs the GCP OAuth consent flow** — a browser window opens for you to sign in and grant access.
4. **Starts the push daemon** on the host, which holds the refresh token and pushes short-lived access tokens directly into the sandbox filesystem.
5. **Pushes gogcli into the sandbox** with a thin wrapper that reads the token from the file written by the daemon.
6. **Adds `gog` to the sandbox PATH** via `.bashrc` so the OpenClaw agent can find it.
7. **Applies the network policy** restricting sandbox egress to Google APIs (read-only).

```bash
cd <nemoclaw-demos-repo>
export GOG_KEYRING_PASSWORD=<password>

./gogcli-skill/bootstrap.sh \
  --credentials /path/to/client_secret.json \
  --email your@gmail.com \
  --sandbox <sandbox-name>
```

`GOG_KEYRING_PASSWORD` is the password used to encrypt the local token file. Use the same value in every subsequent step.

## Part 2: Re-deploy (After a Reboot or Sandbox Reset)

`setup.sh` restarts the push daemon, re-uploads the sandbox wrapper, and reapplies the network policy — without repeating the OAuth consent flow:

```bash
cd <nemoclaw-demos-repo>
GOG_KEYRING_PASSWORD=<password> ./gogcli-skill/setup.sh <sandbox-name>
```

Verify inside the sandbox:

```bash
openshell sandbox exec -n <sandbox-name> -- bash -c 'source ~/.bashrc && gog gmail search "is:inbox" --max 3'
```

## Trying It Out

Open the OpenClaw TUI or web UI and try these prompts:

- "Search my Gmail for unread messages from NVIDIA and summarize them."
- "Check my calendar for meetings tomorrow and give me a prep briefing."
- "List the most recent files in my Google Drive."

OpenClaw ships a built-in `gog` skill — as long as `gog` is on PATH (set by bootstrap), the agent will find and use it automatically.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `gog auth list` shows no accounts | Expected — auth is handled by the push daemon on the host, not stored in the sandbox keyring. Run `gog gmail search "is:inbox"` instead to verify access. |
| Token expired or not found inside sandbox | The push daemon isn't running or failed to push. Check `~/.config/gogcli/push-daemon.log` on the host and re-run `setup.sh`. |
| `l7_decision=deny` for `gmail.googleapis.com` | The Google API policy blocks weren't applied. Re-run `setup.sh` and confirm `google_gmail` / `google_calendar` / `google_drive` appear in `openshell policy get --full <sandbox-name>`. |
| Agent can't find `gog` | The sandbox `.bashrc` PATH entry may be missing. Re-run `setup.sh` which re-adds it. |
| Gmail send fails | Only `gmail.readonly` scope is enabled by default. Read and search work; sending requires the Gmail send scope to be added to your OAuth client and re-running `bootstrap.sh`. |
