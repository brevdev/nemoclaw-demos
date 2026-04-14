---
name: gog
description: "Google Workspace CLI at /sandbox/.config/gogcli/bin/gog. Use when: user asks about email, inbox, send email, reply, drafts, archive, calendar events, schedule meetings, check availability, RSVP, focus time, out of office, Drive files, upload, download, share, Google Docs, read document, write document, edit doc, Google Sheets, read spreadsheet, write cells, contacts, lookup, tasks, to-do list. Covers Gmail, Calendar, Drive, Docs, Sheets, Contacts, Tasks. Run as: /sandbox/.config/gogcli/bin/gog <subcommand>."
---

# gog -- Google Workspace CLI

Access Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets, Google Contacts, and Google Tasks.
All commands output JSON. Binary: `/sandbox/.config/gogcli/bin/gog`.

## Shortcuts

These top-level aliases save typing for the most common actions:

```bash
/sandbox/.config/gogcli/bin/gog send --to a@co.com --subject "Hi" --body-html "<p>Hello</p>"   # gmail send
/sandbox/.config/gogcli/bin/gog ls                            # drive ls
/sandbox/.config/gogcli/bin/gog search "quarterly report"     # drive search
/sandbox/.config/gogcli/bin/gog download <fileId>             # drive download
/sandbox/.config/gogcli/bin/gog upload /tmp/file.pdf          # drive upload
/sandbox/.config/gogcli/bin/gog me                            # show your Google profile
```

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
- "Read the contents of this Google Doc"
- "Create a Google Doc with these notes"
- "Find and replace 'old text' with 'new text' in the doc"
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

# Send email (use --body-html for proper formatting)
/sandbox/.config/gogcli/bin/gog gmail send --to recipient@example.com --subject "Subject" --body-html "<p>Message body here.</p>"

# Send with CC, BCC
/sandbox/.config/gogcli/bin/gog gmail send --to a@co.com --cc b@co.com --bcc c@co.com --subject "Update" --body-html "<p>See below.</p>"

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

# Delete a file
/sandbox/.config/gogcli/bin/gog drive delete <fileId>

# Get a web URL for a file
/sandbox/.config/gogcli/bin/gog drive url <fileId>

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

## Docs

```bash
# Read a Google Doc as plain text
/sandbox/.config/gogcli/bin/gog docs cat <docId>

# Get doc metadata (title, revision, link)
/sandbox/.config/gogcli/bin/gog docs info <docId>

# Show document structure with numbered paragraphs
/sandbox/.config/gogcli/bin/gog docs structure <docId>

# Create a new Google Doc
/sandbox/.config/gogcli/bin/gog docs create "Meeting Notes"

# Create a doc from a markdown file (supports inline images)
/sandbox/.config/gogcli/bin/gog docs create "Report" --file /tmp/report.md

# Write content to a doc (replaces all content)
/sandbox/.config/gogcli/bin/gog docs write <docId> "New content for the document"

# Insert text at a specific position (index)
/sandbox/.config/gogcli/bin/gog docs insert <docId> --index 1 "Text to insert"

# Find and replace text
/sandbox/.config/gogcli/bin/gog docs find-replace <docId> "old text" "new text"

# Regex find and replace (sed-style)
/sandbox/.config/gogcli/bin/gog docs sed <docId> "s/pattern/replacement/g"

# Clear all content from a doc
/sandbox/.config/gogcli/bin/gog docs clear <docId>

# Copy a doc
/sandbox/.config/gogcli/bin/gog docs copy <docId> "Copy of Document"

# Export as PDF, DOCX, TXT, or Markdown
/sandbox/.config/gogcli/bin/gog docs export <docId> --format pdf
/sandbox/.config/gogcli/bin/gog docs export <docId> --format docx
/sandbox/.config/gogcli/bin/gog docs export <docId> --format md

# List tabs in a doc
/sandbox/.config/gogcli/bin/gog docs list-tabs <docId>
```

## Notes

- All output is JSON by default (GOG_JSON=1 is set).
- **Email body formatting**: Always use `--body-html` instead of `--body` for any email longer than one sentence. Plain `--body` text preserves literal newlines, causing ugly mid-sentence line breaks. Never insert line breaks inside a paragraph. Use these HTML patterns:
  - **Paragraphs**: `<p>Text here.</p>`
  - **Bold/italic**: `<strong>bold</strong>`, `<em>italic</em>`
  - **Lists**: `<ul><li>Item one</li><li>Item two</li></ul>` (or `<ol>` for numbered)
  - **Tables**: Always include inline border styles: `<table style="border-collapse:collapse;width:100%"><tr><th style="border:1px solid #ddd;padding:8px;text-align:left;background-color:#f2f2f2">Header</th></tr><tr><td style="border:1px solid #ddd;padding:8px">Value</td></tr></table>`
  - **Headings**: `<h3>Section Title</h3>`
  - **Links**: `<a href="https://example.com">link text</a>`
  - Email clients strip `<style>` blocks, so all styling must be inline via the `style` attribute.
- Gmail send supports --attach for file attachments (PNG, PDF, etc.), repeatable.
- Calendar create sends invites when --attendees is provided.
- Contacts are read-only (search and lookup only).
- Tasks support full CRUD (create, read, update, delete, mark done).
- Sheets support reading, writing, appending, formatting, and exporting.
- Drive supports upload, download, share, mkdir, move, rename, copy, delete, url.
- Docs supports native read (cat), write, insert, find-replace, regex sed, create, copy, export, clear.
- Token is managed automatically by the host-side push daemon.
