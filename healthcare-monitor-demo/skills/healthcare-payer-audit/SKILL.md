---
name: healthcare-payer-audit
description: Review synthetic payer rules, prior authorization flags, and audit requirements. Use when asked about payer implications, audit review, documentation, prior auth, or compliance-safe rationale.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [payer, audit, prior-authorization, compliance]
---

# Healthcare Payer Audit

Run:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py audit
```

The tool reads:

- `/sandbox/.openclaw/workspace/data/payer_rules.json`
- `/sandbox/.openclaw/workspace/data/escalation_rules.json`
- Scheduled actions from the capacity workflow.

Report:

- Prior authorization flags.
- Audit-required critical/high actions.
- Slot IDs tied to audit rows.
- Rationale from priority drivers plus payer notes.

Use conservative wording. This is synthetic decision support, not medical advice or a real payer determination.
