---
name: healthcare-command-summary
description: Produce a concise 48-hour command-center plan from intake, triage, capacity, and audit evidence. Use when the user asks for the final plan, executive summary, watch summary, or operational update.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [summary, command-center, operations, executive]
---

# Healthcare Command Summary

Use specialist results first. If direct deterministic evidence is needed, run:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py watch-summary
```

Preferred final sections:

- Situation
- Priority actions
- Capacity plan
- Payer/audit implications
- Governance note

Keep the answer short enough for an operations review. Mention that the data is synthetic and that OpenShell policy keeps egress visible.
