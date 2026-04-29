# Google Workspace Integration for NemoClaw

> **Alpha / Demo Template** -- This integration is a working example of how to connect a third-party service to NemoClaw using Tier 1 (host-side push daemon) security. It is intended for hackathons, demos, and prototyping -- not production use. Use it as a template to understand the architecture and customize for your own services.

> **Recommended:** Create a **new Gmail account** specifically for testing this integration. Do not use your primary personal or work Gmail. The agent will have full read/write access to email, calendar, drive, and other services on whatever account you authenticate with.

Add full Google Workspace capabilities to your NemoClaw agent using the [gog CLI](https://github.com/steipete/gogcli). The agent can read/send email, manage calendar events, read and edit Google Docs, read and write spreadsheets, upload/share Drive files, look up contacts, manage tasks, and more -- all through natural language.

---

## Services

| Service | Capabilities |
|---|---|
| **Gmail** | Search (full query syntax), read messages/threads, send with CC/BCC/attachments, reply/reply-all, drafts, archive, mark read/unread, trash, labels, attachment download |
| **Google Calendar** | List/search events, create/update/delete with invites, free/busy queries, conflict detection, RSVP, focus time, out of office, working location |
| **Google Drive** | List, search, upload, download, delete, mkdir, copy, move, rename, share, permissions, shared drives |
| **Google Docs** | Read (plain text), create, write, insert, find-replace, regex sed, copy, export (PDF/DOCX/MD/TXT), clear, structure view |
| **Google Sheets** | Read/write ranges, append rows, clear, format cells, find-replace, create spreadsheets, export CSV/XLSX/PDF, manage tabs |
| **Google Contacts** | Search by name/email/phone, list contacts, get details (read-only) |
| **Google Tasks** | List task lists, add/update/delete tasks, mark done/undo |

---

## Prerequisites

1. **NemoClaw** installed and a sandbox running (`nemoclaw onboard` completed)
2. **Google Cloud project** with OAuth credentials configured (see [Google Cloud Setup](#google-cloud-setup-one-time) below)
3. **A dedicated test Gmail account** -- create a new Gmail for testing; do not use your primary email

### Host Dependencies

The install script will attempt to install Go automatically, but the following must be available on the host:

| Dependency | Required for | Check | Install (Ubuntu/WSL) |
|---|---|---|---|
| **Node.js** 18+ | OAuth browser flow (option 2) | `node --version` | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo bash - && sudo apt install -y nodejs` |
| **Go** 1.21+ | Building the gog CLI | `go version` | Installed automatically by `install.sh`, or manually: download from [go.dev/dl](https://go.dev/dl/) |
| **make** | Building the gog CLI | `make --version` | `sudo apt install -y make build-essential` |
| **git** | Cloning the gog CLI source | `git --version` | `sudo apt install -y git` |

> **WSL users:** Always clone and run from the Linux filesystem (`~/`, i.e., `/home/username/`), **not** from `/mnt/c/Users/...`. The Windows mount has slow I/O and permission issues that cause Go build failures.

---

## Quick Install

**Single command, no sandbox recreation needed:**

```bash
cd google-workspace-demo
./install.sh
```

The script handles everything automatically:
1. Prompts for Google credentials (paste directly or run OAuth browser flow)
2. Installs Go and builds the gog CLI (if not already present)
3. Starts a host-side push daemon (refresh token never enters the sandbox)
4. Uploads the gog CLI binary, wrapper, config, and SKILL.md into your sandbox
5. Applies the network policy for all 7 Google services
6. Clears agent sessions so the agent picks up the new skill

### If you already have credentials

```bash
./install.sh
# Choose option 1 (paste credentials)
# Paste the three values when prompted
```

### Target a specific sandbox

```bash
./install.sh my-sandbox-name
```

### Re-deploy after a reboot

```bash
./setup.sh my-sandbox-name
```

---

## Google Cloud Setup (One-Time)

If you don't have Google OAuth credentials yet:

### 1. Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown, select **New Project**, name it, and click **Create**
3. Select the new project

### 2. Enable APIs

Go to **APIs & Services > Library** and enable all of the following:

- **Gmail API**
- **Google Calendar API**
- **Google Drive API**
- **Google Docs API**
- **Google Sheets API**
- **People API** (for Contacts)
- **Tasks API**

### 3. Configure OAuth Consent Screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External** and click **Create**
3. Fill in App name, support email, developer email
4. **Scopes** page: add these scopes:
   - `https://mail.google.com/`
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/spreadsheets`
   - `https://www.googleapis.com/auth/contacts.readonly`
   - `https://www.googleapis.com/auth/tasks`
5. **Test users** page: add your Gmail address

### 4. Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Select the application type (see below) and click **Create**
4. Copy the **Client ID** and **Client Secret**

#### Which credential type to use?

| Type | When to use | Redirect URI setup |
|---|---|---|
| **Desktop app** (recommended) | Running the install script locally or in WSL/Brev. The script handles OAuth via a local server on `localhost:3000`. | No redirect URI configuration needed -- Desktop app credentials allow `localhost` automatically. |
| **Web application** | Only if you cannot use `localhost` (e.g., remote server with no browser). You'd use Google's OAuth Playground instead. | You **must** add `https://developers.google.com/oauthplayground` as an authorized redirect URI (no trailing slash). |

> **Most users should choose Desktop app.** If you get a `redirect_uri_mismatch` error, it almost always means you created Web Application credentials but didn't add the redirect URI. Switch to Desktop app to avoid this entirely.

### 5. Get a Refresh Token

**Recommended approach (Desktop app credentials):**

Run `./install.sh` and choose option 2 (OAuth browser flow). The script opens a local web server, redirects you to Google sign-in, and captures the refresh token automatically. This is the simplest path.

**Alternative approach (Web Application credentials + OAuth Playground):**

If you can't use the local browser flow (e.g., headless server), you can generate a refresh token manually via [Google's OAuth Playground](https://developers.google.com/oauthplayground):

1. Go to OAuth Playground, click the gear icon, check "Use your own OAuth credentials"
2. Enter your Client ID and Client Secret
3. In the scope list on the left, select the 7 scopes listed above (or paste them manually)
4. Click **Authorize APIs**, sign in with your test Gmail account
5. Click **Exchange authorization code for tokens**
6. Copy the **Refresh Token**
7. Run `./install.sh`, choose option 1 (paste credentials), and paste your Client ID, Client Secret, and Refresh Token

> **Important:** If using OAuth Playground, make sure your redirect URI is `https://developers.google.com/oauthplayground` (no trailing slash). A trailing slash will cause a mismatch error.

---

## Testing Mode vs Production

Google Cloud apps have two publishing states that affect how long your credentials last:

| Mode | Token Lifetime | Who Can Authenticate | When to Use |
|---|---|---|---|
| **Testing** (default) | Refresh tokens expire after **7 days**. You'll need to re-run the OAuth flow (option 2 in `install.sh`) weekly. | Only users listed in "Test users" on the consent screen. | Hackathons, demos, short-term prototyping. |
| **Published (In Production)** | Refresh tokens **do not expire** (as long as the user doesn't revoke access). | Anyone with a Google account (or only your org if Internal). | Long-running deployments where you don't want to re-authenticate weekly. |

### For hackathons and demos

Leave the app in **Testing** mode. If the token expires after 7 days, just rerun:

```bash
./install.sh
# Choose option 2 (OAuth browser flow) to get a fresh refresh token
```

### For longer-term use

To avoid the 7-day expiry, publish the app:

1. Go to **APIs & Services > OAuth consent screen**
2. Click **Publish App**
3. For sensitive scopes (like `mail.google.com`), Google may require a verification review -- this can take days to weeks
4. Alternatively, if you have a Google Workspace organization, set the app to **Internal** (skips verification, available to your org only)

> **Note:** Publishing the app does not make it public or visible to anyone. It just changes the token lifetime. Users still need your Client ID to authenticate.

---

## Security: Tier 1 (Push Daemon)

The integration uses a host-side push daemon that delivers short-lived access tokens to the sandbox via `openshell sandbox upload`. No network port is exposed.

- **Refresh token stays on the host** in `~/.nemoclaw/credentials.json`
- **No network socket** -- tokens are pushed as files, not served over HTTP
- **Short-lived tokens** (~60 min) are the only credential the sandbox ever sees
- **Network policy** restricts the sandbox to specific Google API endpoints only
- **L7 proxy** (OpenShell) inspects all outbound traffic from the `gog-bin` binary
- **Binary pinning** -- only the `gog-bin` binary can reach Google APIs; no other process in the sandbox can
- Credentials can be updated by re-running `./install.sh` with no Docker rebuild

### How it works

```
+----- Host ----------------------------+     +----- Sandbox -----------------------+
|                                       |     |                                    |
|  credentials.json                     |     |  /sandbox/.openclaw-data/gogcli/   |
|    +-- GOOGLE_CLIENT_ID               |     |    +-- access_token  (pushed)      |
|    +-- GOOGLE_CLIENT_SECRET           |     |    +-- token_expiry  (pushed)      |
|    +-- GOOGLE_REFRESH_TOKEN           |     |              |                     |
|         |                             |     |  gog wrapper reads token from file |
|  gog-push-daemon.py                   |     |         |                          |
|    +-- POST oauth2.googleapis.com     |     |  gog-bin --> gmail.googleapis.com  |
|       (refreshes access token)        |     |         +-> calendar.googleapis.com|
|    +-- openshell sandbox upload ------+---->|         +-> drive.googleapis.com   |
|       (pushes token to sandbox)       |     |         +-> docs.googleapis.com    |
|                                       |     |         +-> sheets.googleapis.com  |
|  No network port opened              |     |         +-> people.googleapis.com  |
|                                       |     |         +-> tasks.googleapis.com   |
+---------------------------------------+     +------------------------------------+
```

### Network Policy

| Endpoint | Purpose | Methods |
|---|---|---|
| `gmail.googleapis.com:443` | Gmail API | GET, POST, PATCH, DELETE |
| `www.googleapis.com:443` | Calendar API | GET, POST, PATCH, DELETE |
| `calendar.googleapis.com:443` | Calendar API (alt) | GET, POST, PATCH, DELETE |
| `drive.googleapis.com:443` | Drive API | GET, POST, PUT, PATCH, DELETE |
| `docs.googleapis.com:443` | Docs API | GET, POST, PATCH |
| `sheets.googleapis.com:443` | Sheets API | GET, POST, PUT, PATCH |
| `people.googleapis.com:443` | Contacts API | GET (read-only) |
| `tasks.googleapis.com:443` | Tasks API | GET, POST, PATCH, DELETE |

All traffic passes through OpenShell's L7 proxy. Only the `gog-bin` binary is authorized to make requests.

---

## Usage Examples

```bash
nemoclaw <sandbox> connect
```

### Gmail

| Prompt | What happens |
|---|---|
| "Check my email" | Lists recent inbox messages |
| "Search for emails from boss@company.com" | Filters by sender |
| "Send an email to tim@example.com about the hackathon" | Composes and sends |
| "Reply to that email and CC alice@co.com" | Replies in thread with CC |
| "Send that satellite image to my email" | Sends with file attachment |
| "Draft an email to the team about the deadline" | Creates a draft |
| "Archive all read messages from last week" | Bulk archive |

### Calendar

| Prompt | What happens |
|---|---|
| "What's on my calendar today?" | Lists today's events |
| "Schedule a meeting with alice@co.com Friday at 2pm" | Creates event with invite |
| "Am I free tomorrow between 2-4pm?" | Checks availability |
| "Find scheduling conflicts this week" | Detects overlapping events |
| "RSVP yes to the team lunch invite" | Responds to invitation |
| "Block focus time Thursday 2-5pm" | Creates focus time event |
| "Set out of office next Monday" | Creates OOO event |

### Drive

| Prompt | What happens |
|---|---|
| "List my recent Drive files" | Shows recent files |
| "Upload this report to Drive" | Uploads a local file |
| "Share the Q1 report with bob@co.com" | Grants access |
| "Create a folder called Project Files" | Creates folder |
| "Download the Q1 presentation as PDF" | Exports Google Slides as PDF |

### Docs

| Prompt | What happens |
|---|---|
| "Read my meeting notes doc" | Prints the doc as plain text |
| "Create a Google Doc called Project Plan" | Creates a new empty doc |
| "Create a doc from /tmp/report.md" | Creates doc from markdown with images |
| "Replace 'Q1' with 'Q2' in the planning doc" | Find-and-replace in the doc |
| "Export the proposal doc as PDF" | Downloads as PDF |
| "Show me the structure of that doc" | Lists paragraphs with indices |

### Sheets

| Prompt | What happens |
|---|---|
| "Read cells A1 through D10 from the budget spreadsheet" | Reads range |
| "Add a row to the sales tracker: Acme Corp, $50000, Q2" | Appends data |
| "What spreadsheets do I have?" | Lists via Drive search |
| "Create a new spreadsheet called Expense Report" | Creates sheet |
| "Export the budget as CSV" | Downloads as CSV |

### Contacts

| Prompt | What happens |
|---|---|
| "Look up Sarah's email in my contacts" | Searches contacts |
| "Who do I have in my contacts at nvidia.com?" | Filters by domain |

### Tasks

| Prompt | What happens |
|---|---|
| "Show my tasks" | Lists task lists and tasks |
| "Create a task to follow up with the client by Friday" | Adds task with due date |
| "Mark the follow-up task as done" | Completes task |

### Multi-Step Workflows

Works through Telegram if the Telegram bridge is configured:

- "Pull the sales numbers from the Q1 spreadsheet, summarize them, and email the summary to the team"
- "Find the latest satellite image over DC, download the thumbnail, upload it to Drive, and share it with john@co.com"
- "Look up everyone at nvidia.com in my contacts, check calendars for availability Tuesday, and schedule a standup"
- "Read my latest unread email, draft a reply, and create a task to follow up Friday"

---

## File Structure

```
google-workspace-demo/
+-- install.sh              # Full bootstrap (build gog, start daemon, deploy)
+-- setup.sh                # Re-deploy (restart daemon, re-upload binary, re-apply policy)
+-- gog-push-daemon.py      # Host-side OAuth2 token push daemon
+-- gmail-oauth-setup.js    # OAuth2 browser flow helper
+-- skills/gog/SKILL.md     # OpenClaw skill definition
+-- policy/
|   +-- google-workspace.yaml  # Network policy template
+-- google-workspace-guide.md  # This guide
```

---

## Troubleshooting

### Build Issues

| Issue | Fix |
|---|---|
| `gog CLI build failed` | Run `cd ~/.nemoclaw/gogcli && make 2>&1` to see the real error. Common causes below. |
| `make: command not found` | Install make: `sudo apt install -y make build-essential` |
| `go: command not found` | Install Go 1.21+: download from [go.dev/dl](https://go.dev/dl/) or let `install.sh` handle it |
| Build fails on WSL with timeout/hang | You're probably running from `/mnt/c/`. Move to `~/`: `cd ~ && git clone <repo> && cd google-workspace-demo` |
| Build fails with memory errors | WSL memory may be limited. Add `[wsl2]\nmemory=8GB` to `C:\Users\<you>\.wslconfig`, then `wsl --shutdown` |

### OAuth Issues

| Issue | Fix |
|---|---|
| `redirect_uri_mismatch` | You likely created **Web Application** credentials instead of **Desktop app**. Either switch to Desktop app, or add `http://localhost:3000/callback` as an authorized redirect URI on the Web Application credential. |
| OAuth Error 403: access_denied | Add your Gmail as a test user: Google Cloud Console > APIs & Services > OAuth consent screen > Test users |
| Port 3000 in use during OAuth | `lsof -i :3000` then `kill <PID>` |
| Refresh token expired after 7 days | App is in Testing mode. Re-run `./install.sh` option 2 to get a fresh token. See [Testing Mode vs Production](#testing-mode-vs-production) to avoid this. |
| "scope error" or "insufficient permissions" | The token was issued with old scopes; re-run OAuth flow (option 2 in install.sh) |

### Runtime Issues

| Issue | Fix |
|---|---|
| Agent doesn't find gog | Disconnect and reconnect, or run `./setup.sh <sandbox>` |
| "token not found" in sandbox | Check push daemon: `cat ~/.nemoclaw/gog-push-daemon.log` |
| "token expired" | Push daemon will refresh shortly; if persistent, run `./setup.sh` |
| Docs/Sheets/Contacts/Tasks fail | Re-run `./install.sh` option 2 to re-authenticate with all scopes |
| Push daemon died after reboot | Run `./setup.sh <sandbox-name>` |
| Agent responds but can't reach Google | Check policy: `openshell policy get <sandbox> --full` -- look for `google_gmail`, `google_calendar`, etc. If missing, rerun `./setup.sh` or `./install.sh`. |
| Stale sessions after reinstall | Disconnect, then reconnect: `nemoclaw <sandbox> connect`. Or via Telegram, send any new message to start a fresh session. |

### Verification Commands

After installation, you can verify each component:

```bash
# Check push daemon is running
cat ~/.nemoclaw/gog-push-daemon.log | tail -5

# Check token is present in sandbox
openshell sandbox exec <sandbox> -- cat /sandbox/.openclaw-data/gogcli/access_token | head -c 20
echo "..."

# Check gog CLI works in sandbox
openshell sandbox exec <sandbox> -- /sandbox/.config/gogcli/bin/gog gmail list --max-results 1

# Check network policy
openshell policy get <sandbox> --full | grep google_gmail
```

---

## Updating Credentials

Re-run `./install.sh`. No sandbox rebuild needed. The push daemon restarts with the updated credentials from `~/.nemoclaw/credentials.json`.

## Adding New Scopes Later

If Google adds new APIs you want to use:
1. Enable the API in Google Cloud Console
2. Add the scope to `gmail-oauth-setup.js`
3. Add the endpoint to the policy in `install.sh`
4. Add examples to `skills/gog/SKILL.md`
5. Re-run `./install.sh` (choose option 2 to re-authenticate)

## Compatibility

Works on **WSL**, **Brev**, and any Linux host. The push daemon uses `openshell sandbox upload` for token delivery, so no host IP detection or network routing is needed.

> **WSL reminder:** Always work from the Linux filesystem (`~/`), not `/mnt/c/`. The Go build and file permissions require a native Linux filesystem.

---

## Disclaimer

This integration is an **alpha-stage demo template** showing how to connect third-party services to NemoClaw with Tier 1 security. It is not a production-ready Google Workspace integration.

- Use a **dedicated test Gmail account**, not your primary email
- The agent has **full read/write access** to the authenticated Google account
- Token management relies on a host-side daemon that must be running
- The `gog` CLI is a third-party open-source tool ([steipete/gogcli](https://github.com/steipete/gogcli))
- No warranty is provided; use at your own risk

Use this as a reference architecture for building your own secure integrations with NemoClaw and OpenShell.

---

Created by **Tim Klawa** (tklawa@nvidia.com)
