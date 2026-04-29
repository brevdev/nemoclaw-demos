---
name: pst-mail-skills
description: Interact with Outlook PST mailbox files via MCP. Provides direct tool access to extract emails and contacts, search by sender, subject, or date range, browse folder structure, count messages, and draft new emails. You (the agent) decide which tool to call — no secondary LLM is involved. Trigger keywords — email, mail, pst, outlook, inbox, draft, sender, subject, mailbox, folder, unread, extract, search emails.
---

# PST Mail Skills

## Overview

Direct tool interface to an Outlook PST mailbox running on the **host machine** via MCP. You decide which tool to invoke based on the user's request. The MCP server exposes raw PST operations — call them with the specific parameters that match the user's intent.

## IMPORTANT — The PST file is on the host, not in the sandbox

The Outlook `.pst` file is stored on the **host machine** and is accessed directly by the MCP server. **You do not need to locate, upload, or provide a file path.** The server already knows where the PST file is.

- **Never** ask the user to upload or find a PST file.
- **Never** search the sandbox filesystem for a `.pst` file.
- **Always** call tools without `--pst-path` — the server uses its configured default automatically.
- Only pass `--pst-path` if the user explicitly asks to use a *different* PST file and provides its path on the host.

## Invocation

Always use the skill venv's Python (required by the sandbox network policy):

```bash
SKILL_DIR=~/.openclaw/workspace/skills/pst-mail-skills
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/pst_client.py <tool> [args]
```

Do **not** use bare `python3` — the system Python is not permitted to reach the MCP server on port 9003.

## Available Tools

### `list_pst_folders`
Shows the complete folder tree of the PST with item counts (total and unread) per folder.
**Use when:** user wants to browse the mailbox structure, see what folders exist, or check folder sizes.
```bash
python3 pst_client.py list_pst_folders
```

---

### `count_emails`
Counts email items per folder and reports a grand total across the entire mailbox.
**Use when:** user asks how many emails are in the PST, wants a total count, or wants per-folder counts.
```bash
python3 pst_client.py count_emails
```

---

### `get_latest_emails`
Retrieves the N most recent emails sorted by delivery date descending.
**Use when:** user asks for the newest, latest, or most recent emails.
```bash
python3 pst_client.py get_latest_emails [--count N] [--folder NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--count` | int | `10` | Number of recent emails to return |
| `--folder` | str | *(all folders)* | Limit search to this folder (e.g. `Inbox`) |

**Example:**
```bash
python3 pst_client.py get_latest_emails --count 20 --folder Inbox
```

---

### `search_emails_by_sender`
Finds all emails from a specific address or name (case-insensitive).
**Use when:** user asks for emails from a specific person or address.
```bash
python3 pst_client.py search_emails_by_sender --sender ADDR [--max-results N] [--folder NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--sender` | str | *(required)* | Email address or name fragment, e.g. `alice@example.com` or `alice` |
| `--max-results` | int | `50` | Maximum number of matching emails to return |
| `--folder` | str | *(all folders)* | Search only this folder |

**Example:**
```bash
python3 pst_client.py search_emails_by_sender --sender saqib.razzaq@xp.local --max-results 100
```

---

### `search_emails_by_subject`
Finds emails whose subject line contains a keyword (case-insensitive).
**Use when:** user wants emails about a topic or with certain words in the subject.
```bash
python3 pst_client.py search_emails_by_subject --keyword TEXT [--max-results N]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--keyword` | str | *(required)* | Word or phrase to search for in the subject |
| `--max-results` | int | `50` | Maximum number of matching emails to return |

**Example:**
```bash
python3 pst_client.py search_emails_by_subject --keyword "project kickoff"
```

---

### `get_emails_by_date_range`
Fetches emails whose delivery date falls within a specific date range (inclusive on both ends).
**Use when:** user asks for emails within a time window, date range, during a specific month/year, or between two dates.
```bash
python3 pst_client.py get_emails_by_date_range --start-date DATE --end-date DATE [--max-results N] [--folder NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--start-date` | str | *(required)* | Start date, ISO-8601: `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `--end-date` | str | *(required)* | End date, ISO-8601: `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `--max-results` | int | `100` | Maximum number of matching emails to return |
| `--folder` | str | *(all folders)* | Search only this folder |

**Example:**
```bash
python3 pst_client.py get_emails_by_date_range --start-date 2024-01-01 --end-date 2024-03-31
```

---

### `extract_pst`
Full extract of all emails and contacts from the PST. Can be large — prefer targeted searches for large mailboxes.
**Use when:** user wants a complete dump of all emails and contacts.
```bash
python3 pst_client.py extract_pst [--max-emails N] [--max-contacts N]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--max-emails` | int | *(unlimited)* | Stop after this many emails |
| `--max-contacts` | int | *(unlimited)* | Stop after this many contacts |

**Example:**
```bash
python3 pst_client.py extract_pst --max-emails 200
```

---

### `draft_email`
Creates an unsent draft email saved as a .msg or .eml file, optionally appended to the PST's Drafts folder.
**Use when:** user wants to compose, write, or draft an email.
```bash
python3 pst_client.py draft_email --out-path PATH [options]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--out-path` | str | *(required unless --append-to-pst)* | Save draft to this file path on the host (.msg or .eml) |
| `--append-to-pst` | str | *(optional)* | Also append draft to this PST's Drafts folder (host path) |
| `--subject` | str | `""` | Message subject |
| `--body` | str | `""` | Plain-text body (ignored if --body-file is set) |
| `--to-addresses` | str | `""` | Comma-separated To addresses |
| `--cc-addresses` | str | `""` | Comma-separated Cc addresses |
| `--bcc-addresses` | str | `""` | Comma-separated Bcc addresses |
| `--from-address` | str | *(optional)* | From address |
| `--body-file` | str | *(optional)* | Path to a UTF-8 file on the host to use as body |
| `--file-format` | str | `msg` | Output format: `msg` or `eml` |

**Example:**
```bash
python3 pst_client.py draft_email \
  --to-addresses "bob@example.com" \
  --subject "Meeting follow-up" \
  --body "Hi Bob, thanks for the meeting." \
  --out-path /tmp/draft.msg
```

---

## Server URL

The client connects to `http://host.openshell.internal:9003/mcp` by default.
Override with `--server-url URL` or the `MCP_SERVER_URL` environment variable.

## Troubleshooting

If the tool call fails with a connection error:
1. Check the MCP server is running on the host: `curl http://host.openshell.internal:9003/mcp`
2. Confirm the sandbox policy is applied (allows egress to port 9003)
3. If the venv is missing, recreate it:
   ```bash
   python3 -m venv $SKILL_DIR/venv
   $SKILL_DIR/venv/bin/pip install -q fastmcp
   ```
