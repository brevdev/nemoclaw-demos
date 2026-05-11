---
name: healthcare-intake-normalization
description: Normalize and summarize the synthetic referral intake queue. Use when asked about referral counts, service lines, requested windows, preferred locations, missing fields, or intake data quality.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [intake, referrals, data-quality]
---

# Healthcare Intake Normalization

Run the intake analyzer:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py intake
```

Use `/sandbox/.openclaw/workspace/data/referrals.csv` as the source of truth.

Return:

- Total referral count.
- Service-line distribution.
- Preferred-location distribution.
- Requested-window range.
- Missing-field or duplicate-ID concerns.

Do not infer clinical priority here; that belongs to `clinical-triage`.
