# Full Google Workspace for OpenClaw (Gmail, Calendar, Drive, Sheets, Contacts, Tasks)

Give your OpenClaw agent complete Google Workspace access -- send emails, manage calendar events, read and write spreadsheets, upload and share Drive files, look up contacts, and manage tasks. All with Tier 1 security: the refresh token never enters the sandbox.

This builds on the [gog-demo](../gog-demo/gog-openclaw-guide.md) with significant enhancements:

- **6 Google services** (Gmail, Calendar, Drive, Sheets, Contacts, Tasks) vs. 3
- **Full read/write** across all services (Drive uploads, Sheets editing, Tasks CRUD, Gmail send with attachments)
- **No `GOG_KEYRING_PASSWORD` needed** -- credentials stored in `~/.nemoclaw/credentials.json` alongside your other NemoClaw secrets
- **Push daemon** delivers tokens via `openshell sandbox upload` (no network port exposed)
- **Custom SKILL.md** so the agent automatically knows when and how to use each service
- **One-command install** with auto Go installation, gog CLI build, policy merge, and session clearing

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running NemoClaw sandbox | A working OpenShell sandbox with OpenClaw. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Google Cloud project | With Gmail, Calendar, Drive, Sheets, People, and Tasks APIs enabled. See [Google Cloud Setup](#google-cloud-setup) below. |
| OAuth Desktop App credentials | Client ID + Client Secret from Google Cloud Console. |
| Node.js (optional) | Only needed if using the OAuth browser flow. Not needed if pasting credentials directly. |

## Quick Start

```bash
cd google-workspace-demo
./install.sh [sandbox-name]
```

The install script handles everything:
1. Prompts for Google credentials (paste directly or run OAuth browser flow)
2. Installs Go and builds the `gog` CLI if needed
3. Starts the host-side push daemon
4. Uploads everything into the sandbox (binary, wrapper, config, SKILL.md)
5. Applies the network policy for all 6 services
6. Clears agent sessions

### Re-deploy after a reboot

```bash
./setup.sh [sandbox-name]
```

## Google Cloud Setup

### 1. Create a project

Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or select an existing one).

### 2. Enable APIs

Go to **APIs & Services > Library** and enable:

- Gmail API
- Google Calendar API
- Google Drive API
- Google Sheets API
- People API
- Tasks API

### 3. Configure OAuth consent screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External**, click **Create**
3. Fill in app name, support email, developer email
4. Add scopes:
   - `https://mail.google.com/`
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/spreadsheets`
   - `https://www.googleapis.com/auth/contacts.readonly`
   - `https://www.googleapis.com/auth/tasks`
5. Add your Gmail address as a test user

### 4. Create credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Select **Desktop app**
4. Copy the Client ID and Client Secret

## Trying It Out

Connect to your sandbox and try these prompts:

### Gmail
- "Check my email for unread messages"
- "Send an email to alice@example.com about the project update"
- "Reply to the last email from my boss"
- "Draft an email to the team about Friday's demo"

### Calendar
- "What's on my calendar today?"
- "Schedule a meeting with bob@example.com on Friday at 2pm"
- "Am I free tomorrow between 2-4pm?"
- "Block focus time Thursday afternoon"

### Drive
- "List my recent Drive files"
- "Upload this report to Drive and share it with the team"
- "Download the Q1 presentation as PDF"

### Sheets
- "Read cells A1:D10 from the budget spreadsheet"
- "Add a row to the sales tracker: Acme Corp, $50000, Q2"
- "Create a new spreadsheet called Expense Report"

### Contacts & Tasks
- "Look up Sarah's email in my contacts"
- "Create a task to follow up with the client by Friday"

### Multi-step workflows
- "Pull the sales numbers from the Q1 spreadsheet, summarize them, and email the summary to the team"
- "Check my calendar for conflicts this week, then email affected attendees about rescheduling"

## Security Model

This demo uses **Tier 1 security** -- the Google refresh token never enters the sandbox.

```
Host                                    Sandbox
+-----------------------------------+   +----------------------------------+
| ~/.nemoclaw/credentials.json      |   | /sandbox/.openclaw-data/gogcli/  |
|   GOOGLE_CLIENT_ID                |   |   access_token  (60 min, pushed) |
|   GOOGLE_CLIENT_SECRET            |   |   token_expiry                   |
|   GOOGLE_REFRESH_TOKEN            |   |                                  |
|                                   |   | gog wrapper reads token from     |
| gog-push-daemon.py                |   | file, passes to gog-bin via      |
|   exchanges refresh token         |   | GOG_ACCESS_TOKEN env var         |
|   pushes access token via         |   |                                  |
|   openshell sandbox upload -------+-->| gog-bin --> Google APIs           |
|                                   |   |   (L7 proxy inspects all traffic)|
| No network port exposed           |   | No credentials stored here       |
+-----------------------------------+   +----------------------------------+
```

The network policy restricts sandbox egress to specific Google API endpoints, and only the `gog-bin` binary is authorized to make requests.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Agent doesn't find `gog` | Disconnect and reconnect, or run `./setup.sh` |
| "token not found" | Check push daemon: `cat ~/.nemoclaw/gog-push-daemon.log` |
| "token expired" | Daemon will refresh shortly; if persistent, run `./setup.sh` |
| OAuth Error 403 | Add your Gmail as a test user in Google Cloud Console |
| Sheets/Contacts/Tasks fail | Re-run `./install.sh` with option 2 to re-authenticate with all scopes |
| `l7_decision=deny` | Policy not applied. Re-run `./setup.sh` and check `openshell policy get --full` |

## File Structure

```
google-workspace-demo/
+-- install.sh                  # Full bootstrap
+-- setup.sh                    # Re-deploy after reboot
+-- gog-push-daemon.py          # Host-side token push daemon
+-- gmail-oauth-setup.js        # OAuth browser flow helper
+-- google-workspace-guide.md   # This guide
+-- skills/gog/SKILL.md         # OpenClaw skill definition
+-- policy/google-workspace.yaml # Network policy template
```

---

Created by **Tim Klawa** (tklawa@nvidia.com)
