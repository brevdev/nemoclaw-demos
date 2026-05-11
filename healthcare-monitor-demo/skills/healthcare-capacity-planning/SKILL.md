---
name: healthcare-capacity-planning
description: Match prioritized synthetic referrals to available synthetic clinic slots. Use when asked about scheduling, capacity, slot assignment, location fit, or capacity gaps.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [capacity, scheduling, appointments]
---

# Healthcare Capacity Planning

Run:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py schedule
```

The tool starts from the priority-ranked triage list and reads clinic capacity from:

```text
/sandbox/.openclaw/workspace/data/clinic_capacity.csv
```

Matching logic:

- Match by service line.
- Prefer the referral's preferred location.
- Choose earliest available slot after location preference.
- Use each slot once.
- If no slot remains, mark `capacity_gap` with slot ID `ESCALATE`.

Return scheduled count, capacity gaps, urgent-slot usage, and any location mismatches.
