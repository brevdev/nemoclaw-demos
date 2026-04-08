---
name: gogcli
description: "Control Google Workspace (Gmail, Calendar, Drive, Contacts, Tasks) via the gog CLI. Use when the user asks to read or send email, check or create calendar events, list or upload Drive files, or manage contacts and tasks."
---

# Google Workspace CLI (gogcli)

The `gog` binary is installed at `/sandbox/.config/gogcli/gog` and provides access to Gmail, Calendar, Drive, Contacts, and Tasks via the Google REST APIs.

## Environment setup

No environment setup is needed. The `gog` binary at `/sandbox/.config/gogcli/gog`
is a wrapper that automatically fetches a fresh access token from the host token
server before each call. Just invoke it directly.

## Available commands

Use `-j` for JSON output (best for scripting) and `-a <email>` to specify the account.

### Gmail

- `gog gmail list` — list inbox messages
- `gog gmail search <query>` — search messages (Gmail query syntax)
- `gog gmail read <messageId>` — read a message by ID
- `gog gmail send --to <addr> --subject <subj> --body <text>` — send an email

### Calendar

- `gog calendar list` — list upcoming events
- `gog calendar list --days <n>` — events in the next N days
- `gog calendar create --title <title> --start <datetime> --end <datetime>` — create an event

### Drive

- `gog drive ls` — list Drive files
- `gog drive search <query>` — search Drive files
- `gog drive download <fileId>` — download a file
- `gog drive upload <localPath>` — upload a file

### Contacts & Tasks

- `gog contacts list` — list contacts
- `gog tasks list` — list task lists
- `gog tasks list --tasklist <id>` — list tasks in a task list

## Usage pattern

Always use `-j` when you need to parse output or pass IDs between commands.

```bash
# Search Gmail for unread messages from NVIDIA
gog -j gmail search "from:nvidia is:unread" -a you@gmail.com

# Read a specific message
gog -j gmail read <messageId> -a you@gmail.com

# List today's calendar events
gog -j calendar list --days 1 -a you@gmail.com

# List Drive files
gog -j drive ls -a you@gmail.com
```

## Notes

- The account configured in this sandbox is `you@gmail.com`.
- Gmail access is read-only in the current GCP project (searching and reading work; sending requires the Gmail send scope to be enabled).
- Run `gog --help` or `gog <command> --help` for the full flag reference.
- All Google API calls go through the NemoClaw egress policy — the first call to each service will trigger an approval prompt in the TUI.
- If `gog` reports "could not reach token server", the host-side `gog-token-server.py` is not running. Ask the user to restart it.
