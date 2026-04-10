---
name: gog
description: "Google Workspace CLI at /sandbox/.config/gogcli/bin/gog. Use when: user asks about email, inbox, send email, reply, drafts, archive, calendar events, schedule meetings, check availability, RSVP, focus time, out of office, Drive files, upload, download, share, Google Sheets, read spreadsheet, write cells, contacts, lookup, tasks, to-do list. Covers Gmail, Calendar, Drive, Sheets, Contacts, Tasks. Run as: /sandbox/.config/gogcli/bin/gog <subcommand>."
---

# gog -- Google Workspace CLI

Access Gmail, Google Calendar, Google Drive, Google Sheets, Google Contacts, and Google Tasks.
All commands output JSON. Binary: `/sandbox/.config/gogcli/bin/gog`.

## When to Use

- "Check my email" / "Do I have unread messages?"
- "Search my email for messages from X"
- "Send an email to X about Y" / "Reply to that email"
- "Draft an email to X" / "Archive that message"
- "What's on my calendar today?"
- "Schedule a meeting with X on Friday at 2pm"
- "Am I free tomorrow between 2-4pm?"
- "Set focus time Thursday afternoon"
- "Upload this file to Drive" / "Share it with X"
- "Read cells A1:D10 from the budget spreadsheet"
- "Add a row to the sales tracker sheet"
- "Look up Sarah's email in my contacts"
- "Create a task to follow up with the client"

## Gmail

```bash
# Search inbox (full Gmail query syntax)
/sandbox/.config/gogcli/bin/gog gmail search 'is:unread'
/sandbox/.config/gogcli/bin/gog gmail search 'from:boss@company.com newer_than:7d'
/sandbox/.config/gogcli/bin/gog gmail search 'subject:"invoice" has:attachment' --max 10

# Read a specific message
/sandbox/.config/gogcli/bin/gog gmail get <messageId>

# Read a full thread (all messages)
/sandbox/.config/gogcli/bin/gog gmail thread get <threadId>

# Send email
/sandbox/.config/gogcli/bin/gog gmail send --to recipient@example.com --subject "Subject" --body "Message body"

# Send with CC, BCC
/sandbox/.config/gogcli/bin/gog gmail send --to a@co.com --cc b@co.com --bcc c@co.com --subject "Update" --body "See below"

# Send with attachment
/sandbox/.config/gogcli/bin/gog gmail send --to user@example.com --subject "Report" --body "See attached" --attach /tmp/file.pdf

# Reply to a message (preserves thread)
/sandbox/.config/gogcli/bin/gog gmail send --reply-to-message-id <messageId> --subject "Re: Topic" --body "Thanks!"

# Reply all
/sandbox/.config/gogcli/bin/gog gmail send --thread-id <threadId> --reply-all --subject "Re: Topic" --body "Agreed"

# Send HTML email
/sandbox/.config/gogcli/bin/gog gmail send --to a@co.com --subject "Styled" --body-html "<h1>Hello</h1><p>Rich content</p>"

# Drafts
/sandbox/.config/gogcli/bin/gog gmail drafts list
/sandbox/.config/gogcli/bin/gog gmail drafts create --to a@co.com --subject "Draft" --body "WIP"
/sandbox/.config/gogcli/bin/gog gmail drafts send <draftId>

# Organize
/sandbox/.config/gogcli/bin/gog gmail archive <messageId>
/sandbox/.config/gogcli/bin/gog gmail mark-read <messageId>
/sandbox/.config/gogcli/bin/gog gmail unread <messageId>
/sandbox/.config/gogcli/bin/gog gmail trash <messageId>

# Labels
/sandbox/.config/gogcli/bin/gog gmail labels list

# Download attachment
/sandbox/.config/gogcli/bin/gog gmail attachment <messageId> <attachmentId>

# List attachments in a thread
/sandbox/.config/gogcli/bin/gog gmail thread attachments <threadId>
```

## Calendar

```bash
# List upcoming events (all calendars)
/sandbox/.config/gogcli/bin/gog calendar events list
/sandbox/.config/gogcli/bin/gog calendar events list --max 5

# List calendars
/sandbox/.config/gogcli/bin/gog calendar calendars

# Search events by keyword
/sandbox/.config/gogcli/bin/gog calendar search "standup"

# Create event with attendees
/sandbox/.config/gogcli/bin/gog calendar create primary \
  --title "Team standup" \
  --start "2026-04-10T09:00:00" \
  --duration 30m \
  --attendees "alice@co.com,bob@co.com"

# Update an event
/sandbox/.config/gogcli/bin/gog calendar update primary <eventId> --title "New title"

# Delete an event
/sandbox/.config/gogcli/bin/gog calendar delete primary <eventId>

# Check availability (free/busy)
/sandbox/.config/gogcli/bin/gog calendar freebusy colleague@company.com

# Find scheduling conflicts
/sandbox/.config/gogcli/bin/gog calendar conflicts

# RSVP to an invitation
/sandbox/.config/gogcli/bin/gog calendar respond primary <eventId> --status accepted

# Create focus time block
/sandbox/.config/gogcli/bin/gog calendar focus-time --from "2026-04-10T14:00:00" --to "2026-04-10T17:00:00"

# Set out of office
/sandbox/.config/gogcli/bin/gog calendar out-of-office --from "2026-04-14" --to "2026-04-18"

# Set working location
/sandbox/.config/gogcli/bin/gog calendar working-location --from "2026-04-10" --to "2026-04-10" --type home
```

## Drive

```bash
# List files
/sandbox/.config/gogcli/bin/gog drive ls
/sandbox/.config/gogcli/bin/gog drive ls <folderId>

# Search files
/sandbox/.config/gogcli/bin/gog drive search "Q1 report"

# Get file metadata
/sandbox/.config/gogcli/bin/gog drive get <fileId>

# Download a file
/sandbox/.config/gogcli/bin/gog drive download <fileId>

# Upload a file
/sandbox/.config/gogcli/bin/gog drive upload /tmp/report.pdf
/sandbox/.config/gogcli/bin/gog drive upload /tmp/image.png --parent <folderId>

# Create a folder
/sandbox/.config/gogcli/bin/gog drive mkdir "Project Files"

# Share a file
/sandbox/.config/gogcli/bin/gog drive share <fileId> --email user@company.com --role writer

# Copy a file
/sandbox/.config/gogcli/bin/gog drive copy <fileId> "Copy of Report"

# Move a file
/sandbox/.config/gogcli/bin/gog drive move <fileId> --to <folderId>

# Rename a file
/sandbox/.config/gogcli/bin/gog drive rename <fileId> "New Name"

# List permissions
/sandbox/.config/gogcli/bin/gog drive permissions <fileId>

# List shared drives
/sandbox/.config/gogcli/bin/gog drive drives
```

## Sheets

```bash
# Read a range
/sandbox/.config/gogcli/bin/gog sheets get <spreadsheetId> "Sheet1!A1:D10"

# Write values to a range
/sandbox/.config/gogcli/bin/gog sheets update <spreadsheetId> "Sheet1!A1" "value1" "value2" "value3"

# Append a row
/sandbox/.config/gogcli/bin/gog sheets append <spreadsheetId> "Sheet1!A:D" "col1" "col2" "col3" "col4"

# Clear a range
/sandbox/.config/gogcli/bin/gog sheets clear <spreadsheetId> "Sheet1!A1:D10"

# Get spreadsheet metadata (list tabs)
/sandbox/.config/gogcli/bin/gog sheets metadata <spreadsheetId>

# Create a new spreadsheet
/sandbox/.config/gogcli/bin/gog sheets create "My New Sheet"

# Export as CSV/XLSX/PDF
/sandbox/.config/gogcli/bin/gog sheets export <spreadsheetId> --format csv

# Find and replace
/sandbox/.config/gogcli/bin/gog sheets find-replace <spreadsheetId> "old text" "new text"

# Add a new tab
/sandbox/.config/gogcli/bin/gog sheets add-tab <spreadsheetId> "New Tab"

# Format cells
/sandbox/.config/gogcli/bin/gog sheets format <spreadsheetId> "Sheet1!A1:D1" --bold --background-color "#4285f4"
```

## Contacts (read-only)

```bash
# Search contacts by name/email
/sandbox/.config/gogcli/bin/gog contacts search "Sarah"

# List all contacts
/sandbox/.config/gogcli/bin/gog contacts list

# Get contact details
/sandbox/.config/gogcli/bin/gog contacts get <resourceName>
```

## Tasks

```bash
# List task lists
/sandbox/.config/gogcli/bin/gog tasks lists list

# List tasks in a list
/sandbox/.config/gogcli/bin/gog tasks list <tasklistId>

# Add a task
/sandbox/.config/gogcli/bin/gog tasks add <tasklistId> --title "Follow up with client" --due "2026-04-12"

# Mark task as done
/sandbox/.config/gogcli/bin/gog tasks done <tasklistId> <taskId>

# Update a task
/sandbox/.config/gogcli/bin/gog tasks update <tasklistId> <taskId> --title "Updated title"

# Delete a task
/sandbox/.config/gogcli/bin/gog tasks delete <tasklistId> <taskId>
```

## Docs / Slides (export via Drive)

```bash
# Download a Google Doc as PDF
/sandbox/.config/gogcli/bin/gog drive download <docId> --format pdf

# Download as DOCX
/sandbox/.config/gogcli/bin/gog drive download <docId> --format docx
```

## Notes

- All output is JSON by default (GOG_JSON=1 is set).
- Gmail send supports --attach for file attachments (PNG, PDF, etc.), repeatable.
- Calendar create sends invites when --attendees is provided.
- Contacts are read-only (search and lookup only).
- Tasks support full CRUD (create, read, update, delete, mark done).
- Sheets support reading, writing, appending, formatting, and exporting.
- Drive supports upload, download, share, mkdir, move, rename, copy, delete.
- Token is managed automatically by the host-side push daemon.
