---
name: healthcare-clinical-triage
description: Rank synthetic referrals by deterministic escalation rules. Use when asked which referrals are critical, high, medium, or routine, and why.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [triage, risk, escalation]
---

# Healthcare Clinical Triage

Run:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py triage
```

The tool reads:

- `/sandbox/.openclaw/workspace/data/referrals.csv`
- `/sandbox/.openclaw/workspace/data/escalation_rules.json`
- `/sandbox/.openclaw/workspace/data/clinical_notes.json`

Priority logic:

- Critical flags outrank high flags.
- High flags outrank medium flags.
- Medium flags outrank the default priority.
- Ties break by requested window, then referral ID.

Clinical note summaries are evidence, not independent scoring rules.

Always include the reminder: synthetic operational support only, not medical advice.
