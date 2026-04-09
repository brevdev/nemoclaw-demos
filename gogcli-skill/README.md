# gogcli-skill

NemoClaw skill that gives a sandboxed agent read-only access to Google Workspace (Gmail, Calendar, Drive) via the `gog` CLI.

## How it works

OAuth2 refresh tokens stay on the host inside a push daemon (`gog-token-server.py`). The daemon exchanges the refresh token for short-lived access tokens and writes them directly into the sandbox filesystem — no network socket is exposed.

```
host push daemon ──openshell sandbox upload──> /sandbox/.openclaw-data/gogcli/access_token
sandbox gog wrapper ──reads token──> Google APIs
```

## Files

| File | Purpose |
|---|---|
| `bootstrap.sh` | One-command setup: installs Go (if needed), clones and builds `gogcli`, stores credentials, runs OAuth consent, starts push daemon, pushes gogcli into sandbox, adds gog to sandbox PATH, applies network policy |
| `setup.sh` | Re-deploy only: restart push daemon + re-upload sandbox config (skips OAuth consent) |
| `gog-token-server.py` | Host-side push daemon — exchanges the refresh token for short-lived access tokens and writes them into the sandbox via `openshell sandbox upload` |
| `policy.yaml` | NemoClaw network policy — restricts sandbox egress to Google APIs (read-only) |

## Quick start

### 1. First-time setup (bootstrap)

```bash
export GOG_KEYRING_PASSWORD=<choose-a-password>

./gogcli-skill/bootstrap.sh \
  --credentials /path/to/client_secret.json \
  --email you@gmail.com \
  --sandbox <sandbox-name>
```

Bootstrap handles everything automatically: checks your OS, installs Go if needed, clones and builds `gogcli` (as a sibling directory), runs the OAuth consent flow, starts the push daemon, pushes gogcli into the sandbox, adds `gog` to the sandbox PATH via `.bashrc`, and applies the network policy.

### 2. Re-deploy (after a reboot or sandbox reset)

```bash
GOG_KEYRING_PASSWORD=<same-password> ./gogcli-skill/setup.sh <sandbox-name>
```

### 3. Verify

```bash
# On the host — confirm the push daemon is running
cat ~/.config/gogcli/push-daemon.log | tail -5

# Inside the sandbox
openshell sandbox exec -n <sandbox-name> -- bash -c 'source ~/.bashrc && gog gmail search "is:inbox" --max 3'
```

## Network policy

All three Google services are currently **read-only** (GET only). Write methods are commented out in `policy.yaml` and can be re-enabled per service if needed.

| Service | Endpoint | Allowed |
|---|---|---|
| Gmail | `gmail.googleapis.com` | GET |
| Calendar | `calendar.googleapis.com` | GET |
| Drive | `drive.googleapis.com` | GET |

## Prerequisites

- Linux or macOS
- GCP OAuth client credentials JSON (see below)
- `openshell` and `openclaw` CLIs available on the host
- `git`, `python3`, `curl`, `make` (Go and `gogcli` are installed/built automatically)

### Getting the GCP OAuth credentials JSON

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and select (or create) a project.
2. **Enable APIs:** Navigate to **APIs & Services > Library** and enable:
   - Gmail API
   - Google Calendar API
   - Google Drive API
3. **Configure the consent screen:** Go to **APIs & Services > OAuth consent screen**.
   - Choose **External** (or Internal if using Google Workspace).
   - Fill in app name and support email, then save.
   - Under **Scopes**, add the read-only scopes you need (e.g. `gmail.readonly`, `calendar.readonly`, `drive.readonly`).
   - Add your Gmail address as a **Test user**.
4. **Create credentials:** Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
   - Application type: **Desktop app**.
   - Give it a name and click **Create**.
5. **Download the JSON:** Click the download icon next to the new client ID. Save the file — this is the `--credentials` argument for `bootstrap.sh`.

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOG_KEYRING_PASSWORD` | Yes | — | Encrypts the local token file |
| `GOG_ACCOUNT` | No | first account in keyring | Gmail address for the push daemon |
