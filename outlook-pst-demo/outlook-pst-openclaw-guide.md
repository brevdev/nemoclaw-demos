# Connecting an Outlook PST Mailbox to OpenClaw via MCP

This guide walks you through connecting an Outlook `.pst` mailbox to an OpenClaw agent running inside an OpenShell sandbox. By the end, your agent will be able to browse folders, search emails by sender, subject, or date range, retrieve the latest messages, count items, and draft new emails — all through natural language.

The connection uses **MCP (Model Context Protocol)**. A lightweight Python server runs on the host, exposes PST operations over HTTP, and requires no secondary LLM of its own. The OpenClaw agent inside the sandbox calls MCP tools directly and uses its configured inference model for all natural-language reasoning. The sandbox talks to the host MCP server through an egress-approved network policy.

> **What is a `.pst` file?**
> A `.pst` (Personal Storage Table) file is an Outlook data file that stores a local copy of your mailbox — emails, contacts, calendar items, and folder structure. You typically encounter one when you export or archive mail from Outlook, your organization archives old mailboxes off Exchange/M365, or you receive a mailbox export from IT or legal for review.
>
> **Limitation:** This demo is designed for **read-only archive search**. The `.pst` file is a static snapshot — not synced with a live Outlook account. The `draft_email` tool writes a draft file locally (`.msg`/`.eml`) but does **not** send it or sync it back to Outlook.

---

## Prerequisites

| Requirement | Details |
|---|---|
| NemoClaw | `nemoclaw` and `openshell` CLIs must be installed. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Python 3.10 | Required on the host for Aspose.Email compatibility. The host venv is pinned to Python 3.10 (`uv venv --python 3.10`). Aspose.Email does not ship a native extension for Python 3.11+. |
| `libssl1.1` | Required by Aspose.Email's .NET runtime. Ubuntu 22.04+ ships only OpenSSL 3.x, which causes mid-session crashes. `install.sh` installs `libssl1.1` automatically if missing. |
| `Aspose.Email-for-Python-via-NET` | Python package for reading `.pst` files. Installed automatically by `install.sh` into the host Python 3.10 venv (`uv pip install "Aspose.Email-for-Python-via-NET"`). No manual installation needed. |
| Inference API key | Required by `nemoclaw onboard` to configure the OpenClaw agent's inference provider. Set `INFERENCE_API_KEY` in `.env` before running `install.sh`. |
| `uv` | Installed automatically by `install.sh` if missing. |
| Outlook PST file | Download the sample `Outlook.pst` (see [Data Setup](#data-setup)) or point the server at your own file via `PST_PATH`. |

---

## One-Command Setup

### 1. Configure `.env`

Copy the template and fill in your values:

```bash
cd nemoclaw-demos/outlook-pst-demo
cp .env.template .env
```

Open `.env` and set your API key and inference configuration:

```bash
# Inference API credentials
INFERENCE_API_KEY=nvapi-your-key

# Inference provider configuration
INFERENCE_PROVIDER_TYPE=nvidia
INFERENCE_PROVIDER_NAME=nvidia
INFERENCE_BASE_URL=https://integrate.api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-opus-4-6

# Optional: absolute path to your .pst file (server uses built-in sample if omitted)
PST_PATH=/path/to/your/mailbox.pst

# Optional: path to your Aspose.Email .lic file (evaluation mode if omitted)
ASPOSE_EMAIL_LICENSE_PATH=
```

> **Choosing a provider or model:** see the NemoClaw docs for the full list of supported providers, base URLs, and models:
> [https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model](https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model)

`INFERENCE_API_KEY` is cached to `~/.nemoclaw/credentials.json` after the first run, so future re-runs pick it up without needing `.env` in place. You can also override any value inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b bash install.sh
```

---

### 2. Run the installer

```bash
cd nemoclaw-demos/outlook-pst-demo
bash install.sh
```

The script will:
1. Clean up any stale MCP server processes
2. Load `.env` and resolve `INFERENCE_API_KEY`, provider, base URL, and model
3. Run `nemoclaw onboard` if no sandbox exists — confirm the sandbox name when prompted
4. Create the inference provider and set the model **after** the gateway is live — this always overrides whatever model `nemoclaw onboard` defaulted to
5. Install `libssl1.1` if missing (Aspose.Email's .NET runtime requires it; without it the server crashes mid-session)
6. Install all Python dependencies on the host into a **Python 3.10 venv** (via `uv`): `fastmcp`, `colorama`, `python-dotenv`, `Aspose.Email-for-Python-via-NET`
7. Start the MCP server as a background process with **auto-restart** — if it crashes on an edge-case PST operation it restarts within 2 seconds (PID tracked in `/tmp/pst-mcp.pid`, logs at `/tmp/pst-mcp.log`)
8. Apply the sandbox network policy (`sandbox_policy.yaml`)
9. Upload the `pst-mail-skills` skill into the sandbox at `/sandbox/.openclaw-data/workspace/skills/pst-mail-skills/`
10. Bootstrap the skill's Python venv inside the sandbox at `/sandbox/.openclaw-data/workspace/skills/pst-mail-skills/venv`
11. Verify the installation (MCP server reachable, skill present, venv imports OK)

You can also pass a sandbox name directly to skip the interactive prompt:

```bash
bash install.sh <sandbox-name>
```
> **Note:** The installer is largely automated, but two interactive prompts require user input: accepting the NemoClaw terms during `nemoclaw onboard` and confirming the sandbox name. All other steps — dependency installation, provider configuration, skill deployment, and server startup — run without intervention.
---

## Data Setup

The server defaults to the built-in sample PST at `Data/Outlook.pst`. To use it, download it into that folder:

```bash
mkdir -p Data
# Download Outlook.pst from the Aspose.Email Python example repository
```

> **[Download sample Outlook.pst →](https://github.com/aspose-email/Aspose.Email-Python-Dotnet/blob/master/Examples/Data/Outlook.pst)**

Place the file at:

```
outlook-pst-demo/
└── Data/
    └── Outlook.pst
```

To use your own PST file instead, set `PST_PATH` in `.env`:

```bash
PST_PATH=/absolute/path/to/your/mailbox.pst
```

---

## Trying It Out

Connect to the sandbox and launch the OpenClaw TUI:

```bash
# From your host terminal
nemoclaw <sandbox-name> connect

# Inside the sandbox
openclaw tui
```

Once connected, verify the skill is loaded by asking the agent directly:

```
> do you have a skill to work with PST mailbox files?

  Yes, I have the pst-mail-skills skill available, which provides direct access
  to Outlook PST mailbox operations through an MCP server running on the host.

  This skill allows me to:
  - Browse folder structure with item counts
  - Retrieve the N most recent emails sorted by date
  - Search emails by sender address or name fragment
  - Search emails by subject keyword
  - Filter emails by delivery date range
  - Count email items per folder and in total
  - Draft new emails as .msg or .eml files

  What would you like to do with your mailbox?

  connected | idle
  agent main | session main (openclaw-tui) | inference/nvidia/aws/anthropic/bedrock-claude-opus-4-6 | tokens 18k/131k (14%)
```

Try these prompts. The sample responses below are based on the toy example `Outlook.pst` manually downloaded by user — actual output will vary depending on your PST file, the number of emails, folder structure, and your choice of inference model.

---

**"How many emails are in the mailbox?"**

```
The mailbox has 13 emails total, spread across:

┌───────────────┬───────┐
│ Folder        │ Count │
├───────────────┼───────┤
│ Inbox         │ 6     │
│ Sent Items    │ 5     │
│ Calendar      │ 1     │
│ Contacts      │ 1     │
│ Drafts        │ 0     │
│ Deleted Items │ 0     │
└───────────────┴───────┘
```

---

**"Find all emails from saqib.razzaq@xp.local"**

```
Found 22 emails from saqib.razzaq@xp.local (Saqib Razzaq). All are dated
2011-06-21 and are self-sent. Here are the unique messages:

| # | Subject                              | Folder           | Date (UTC) |
|---|--------------------------------------|------------------|------------|
| 1 | message 1                            | Inbox            | 23:46      |
| 2 | message 2                            | Inbox / Sent     | 23:47      |
| 3 | check sent date of this message      | Inbox / Sent     | 23:47      |
| 4 | this message contains embedded MSG   | Inbox / Sent     | 23:48      |
| 5 | HTML body                            | Inbox / Sent     | 23:49      |
| 6 | Multiple attachments                 | Inbox / Sent     | 23:51      |

Each message appears in both Inbox and Sent Items since they were sent to the
same address. Want me to dig into any specific message?
```

---

**"Search for emails with 'attachment' in the subject."**

```
Found 2 emails with "attachment" in the subject:

| # | Folder     | Subject              | From        | Date                |
|---|------------|----------------------|-------------|---------------------|
| 1 | Inbox      | Multiple attachments | Saqib Razzaq| 2011-06-21 23:51 UTC|
| 2 | Sent Items | Multiple attachments | Saqib Razzaq| 2011-06-21 23:51 UTC|

Both are the same message (one in Inbox, one in Sent Items), with the body:
"This message contains multiple attachments."
```

---

**"Draft a mail to test@example.outlook.com with subject 'follow up', save to /tmp/mydraft.msg"**

```
Done! Your draft has been saved to /tmp/mydraft.msg.

  To:      test@example.outlook.com
  Subject: follow up
  Body:
    Hi,

    I wanted to follow up on our previous conversation. Please let me know
    if there are any updates or if you need anything from my end.

    Looking forward to hearing from you.

    Best regards
```

---

## Available MCP Tools

The OpenClaw agent's LLM decides which tool to call. The MCP server exposes raw PST operations — it is stateless and requires no secondary LLM or API key.

| Tool | Key Arguments | What it does |
|---|---|---|
| `list_pst_folders` | `pst_path` | Shows folder hierarchy with total and unread counts |
| `count_emails` | `pst_path` | Counts email items per folder plus a grand total |
| `get_latest_emails` | `count`, `pst_path`, `folder_name` | Returns N most recent emails sorted by date descending |
| `search_emails_by_sender` | `sender`, `pst_path`, `max_results`, `folder_name` | Finds emails from a specific address or name (case-insensitive) |
| `search_emails_by_subject` | `keyword`, `pst_path`, `max_results` | Finds emails whose subject contains a keyword (case-insensitive) |
| `get_emails_by_date_range` | `start_date`, `end_date`, `pst_path`, `max_results`, `folder_name` | Fetches emails within an ISO-8601 date range (inclusive) |
| `extract_pst` | `pst_path`, `max_emails`, `max_contacts` | Full dump of all emails and contacts — use targeted searches for large mailboxes |
| `draft_email` | `out_path` or `append_to_pst`, plus address/body fields | Creates an unsent draft as a .msg or .eml file |

All tools accept an optional `pst_path` argument. If omitted, the server falls back to its configured default (`PST_PATH` env var → built-in `Data/Outlook.pst`).

---

## How the Skill Calls Tools

The `pst-mail-skills` client (`scripts/pst_client.py`) uses an `argparse` subcommand interface. OpenClaw invokes it via the skill's venv Python:

```bash
SKILL_DIR=~/.openclaw/workspace/skills/pst-mail-skills
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/pst_client.py <tool> [args]
```

> **Note:** Inside the sandbox, `~/.openclaw` is a symlink to `~/.openclaw-data`. The skill and its venv are physically located at `/sandbox/.openclaw-data/workspace/skills/pst-mail-skills/`. The network policy includes both path forms so the proxy allows connections from either resolved path.

Examples:

```bash
# List folders
python3 pst_client.py list_pst_folders

# Get 20 latest emails from Inbox
python3 pst_client.py get_latest_emails --count 20 --folder Inbox

# Search by sender
python3 pst_client.py search_emails_by_sender --sender alice@example.com

# Search by subject
python3 pst_client.py search_emails_by_subject --keyword "project kickoff"

# Date range
python3 pst_client.py get_emails_by_date_range --start-date 2024-01-01 --end-date 2024-03-31

# Draft an email
python3 pst_client.py draft_email \
  --to-addresses "bob@example.com" \
  --subject "Follow-up" \
  --body "Hi Bob, thanks for your time." \
  --out-path /tmp/draft.msg
```

See `pst-mail-skills/SKILL.md` for the full argument reference for each tool.

---

## Access Control Overview

Access to PST data is governed by two independent controls. Both must be satisfied for the sandbox to reach the host.

### Control 1 — Tool surface (`extract_pst_mcp_server.py`)

The server process has full access to the host: filesystem, environment variables, and the Aspose library. None of that is directly reachable from the sandbox. The sandbox can only call the 8 decorated `@mcp.tool()` functions over HTTP — all internal helpers are invisible to the network.

```python
# Only these are callable from the network — everything else is private
@mcp.tool()
async def search_emails_by_sender(sender: str, ...) -> str: ...

@mcp.tool()
async def get_latest_emails(count: int, ...) -> str: ...

# internal helpers are never exposed
def _search_by_sender_sync(...): ...   # internal only
def _get_latest_emails_sync(...): ...  # internal only
```

### Control 2 — `sandbox_policy.yaml` (network-level)

Even with a minimal tool surface, the sandbox cannot reach the host unless the policy explicitly allows it. The relevant block opens outbound HTTP from the sandbox to port 9003 only, and only from specific trusted binaries:

```yaml
network_policies:
  mcp_server_host:
    name: mcp_server_host
    endpoints:
      - host: host.openshell.internal
        port: 9003
        allowed_ips: [172.17.0.1]
      - host: 127.0.0.1
        port: 9003
    binaries:
      - { path: /usr/local/bin/claude }
      - { path: /usr/local/bin/node }
      - { path: /usr/bin/node }
      - { path: /usr/bin/curl }
      - { path: /usr/bin/python3 }
      - { path: /usr/bin/python3.11 }
      - { path: "/sandbox/.openclaw/workspace/skills/*/venv/bin/python3" }
      - { path: "/sandbox/.openclaw-data/workspace/skills/*/venv/bin/python3" }
```

Both `/.openclaw/` and `/.openclaw-data/` path patterns are listed because the OpenShell proxy resolves symlinks when checking binary paths — `~/.openclaw` is a symlink to `~/.openclaw-data` inside the sandbox, so the resolved path must also be permitted.

Nothing outside those hosts, ports, and binaries can initiate a connection to the host.

### Combined architecture

```
┌─────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                               │
│                                                             │
│   extract_pst_mcp_server.py  (port 9003, Python 3.10)      │
│   ├── @mcp.tool() list_pst_folders     ← reachable         │
│   ├── @mcp.tool() search_emails_*      ← reachable         │
│   ├── @mcp.tool() get_latest_emails    ← reachable         │
│   ├── _search_by_sender_sync()         ← NOT reachable     │
│   └── os / filesystem / Aspose API    ← NOT reachable      │
└──────────────────────────────┬──────────────────────────────┘
                               │  HTTP only to port 9003
                               │  policy: sandbox_policy.yaml
┌──────────────────────────────┴──────────────────────────────┐
│  SANDBOX (OpenClaw / OpenShell)                             │
│                                                             │
│   pst-mail-skills/scripts/pst_client.py                    │
│   └── calls specific tools directly (e.g. get_latest_emails│
│       --count 10)  ← agent's LLM picks the tool + args     │
└─────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `INFERENCE_API_KEY is not set` | Add `INFERENCE_API_KEY=your-key` to `.env`, or run `export INFERENCE_API_KEY=...` before `install.sh` |
| `No usable version of libssl was found` / server crashes mid-session | Aspose.Email's .NET runtime needs `libssl.so.1.1`. `install.sh` installs it automatically. To fix manually: `curl -fsSL http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_amd64.deb -o /tmp/libssl1.1.deb && sudo dpkg -i /tmp/libssl1.1.deb` |
| `ModuleNotFoundError: aspose.email` on host | The host venv must use Python 3.10 — Aspose.Email does not ship a native extension for Python 3.11+. Re-run `install.sh` (it pins to `--python 3.10`), or manually: `rm -rf .venv && uv venv --python 3.10 && uv pip install "Aspose.Email-for-Python-via-NET"` |
| `ModuleNotFoundError: fastmcp` in sandbox | Run with the skill venv Python, not bare `python3`: `~/.openclaw/workspace/skills/pst-mail-skills/venv/bin/python3 ~/.openclaw/workspace/skills/pst-mail-skills/scripts/pst_client.py <tool> [args]` |
| `FileNotFoundError` on PST path | Check that `Data/Outlook.pst` exists, or set `PST_PATH=/absolute/path/to/file.pst` in `.env` |
| `Connection refused` from sandbox | Confirm the server is running: `curl http://127.0.0.1:9003/mcp` from the host. Check logs: `cat /tmp/pst-mcp.log` |
| `l7_decision=deny` / 403 in OpenShell logs | Policy not applied or the connecting binary isn't listed — re-run `openshell policy set` and verify `sandbox_policy.yaml` includes both `.openclaw` and `.openclaw-data` path patterns in `mcp_server_host` |
| Wrong inference model shown in TUI | `nemoclaw onboard` sets its own default model. `install.sh` always overrides it with your `.env` model **after** the gateway is live (Step 3b). If the wrong model appeared on an existing sandbox, run: `openshell inference set --provider nvidia --model aws/anthropic/bedrock-claude-opus-4-6` then reconnect. |
| Agent doesn't find the skill | Disconnect and reconnect to the sandbox, or verify the skill is at `/sandbox/.openclaw-data/workspace/skills/pst-mail-skills/` |
| Wrong `host.openshell.internal` resolution | Set `MCP_SERVER_URL` explicitly to the host's LAN IP instead of relying on the DNS alias |
| `NVIDIA Endpoints endpoint validation failed` during `nemoclaw onboard` | Type `retry` at the prompt — the API call usually succeeds on a second attempt. If persistent, set a faster `INFERENCE_MODEL` in `.env` |

### Restarting the MCP server

The MCP server runs as a background process tracked by `/tmp/pst-mcp.pid`. To restart it without a full reinstall:

```bash
kill $(cat /tmp/pst-mcp.pid) 2>/dev/null || true
bash install.sh <sandbox-name>
```

### Full environment reset

```bash
# Stop MCP server
kill $(cat /tmp/pst-mcp.pid) 2>/dev/null || true

# Delete sandbox and host venv
openshell sandbox delete <sandbox-name>
rm -rf outlook-pst-demo/.venv

# Re-run
bash install.sh
```

---

## File Structure

```
outlook-pst-demo/
├── extract_pst_mcp_server.py    # Host-side MCP server (8 tools, no LLM, Python 3.10)
├── sandbox_policy.yaml          # Network policy — opens port 9003 to the sandbox
├── install.sh                   # One-command installer
├── .env.template                # Configuration template
├── outlook-pst-openclaw-guide.md  # This guide
├── Data/
│   └── Outlook.pst              # Sample PST file (empty by default, manual download needed, see Prerequisites)
└── pst-mail-skills/
    ├── SKILL.md                 # OpenClaw skill definition and usage examples
    └── scripts/
        └── pst_client.py        # MCP client — argparse subcommands for each tool
```

---

Created by **zcharpy**
