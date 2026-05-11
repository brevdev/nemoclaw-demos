#!/usr/bin/env python3
"""Deterministic synthetic care-backlog analysis for the healthcare monitor example."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections import Counter


SCRIPT = Path(__file__).resolve()
DATA_CANDIDATES = [
    SCRIPT.parents[1] / "data",  # Inside sandbox: /sandbox/.openclaw/workspace/data
    SCRIPT.parents[2] / "data",  # Local kit: <repo>/data
]
DATA = next((path for path in DATA_CANDIDATES if path.exists()), DATA_CANDIDATES[0])


@dataclass
class Referral:
    referral_id: str
    patient_alias: str
    age: int
    service_line: str
    reason: str
    requested_window_hours: int
    risk_flags: list[str]
    preferred_location: str
    payer: str
    received_at: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_referrals() -> list[Referral]:
    referrals: list[Referral] = []
    for row in read_csv(DATA / "referrals.csv"):
        referrals.append(
            Referral(
                referral_id=row["referral_id"],
                patient_alias=row["patient_alias"],
                age=int(row["age"]),
                service_line=row["service_line"],
                reason=row["reason"],
                requested_window_hours=int(row["requested_window_hours"]),
                risk_flags=[flag for flag in row["risk_flags"].split("|") if flag],
                preferred_location=row["preferred_location"],
                payer=row["payer"],
                received_at=row["received_at"],
            )
        )
    return referrals


def priority_for(referral: Referral, rules: dict) -> tuple[str, int, list[str]]:
    flags = set(referral.risk_flags)
    critical = flags.intersection(rules["critical_flags"])
    high = flags.intersection(rules["high_flags"])
    medium = flags.intersection(rules["medium_flags"])
    if critical:
        return "critical", 100, sorted(critical)
    if high:
        return "high", 80, sorted(high)
    if medium:
        return "medium", 50, sorted(medium)
    return rules["default_priority"], 20, []


def ranked_referrals() -> list[dict]:
    rules = load_json(DATA / "escalation_rules.json")
    notes = load_json(DATA / "clinical_notes.json")
    rows = []
    for referral in load_referrals():
        priority, score, drivers = priority_for(referral, rules)
        rows.append(
            {
                "referral_id": referral.referral_id,
                "patient_alias": referral.patient_alias,
                "service_line": referral.service_line,
                "priority": priority,
                "score": score,
                "drivers": drivers,
                "requested_window_hours": referral.requested_window_hours,
                "preferred_location": referral.preferred_location,
                "payer": referral.payer,
                "note_summary": notes.get(referral.referral_id, ""),
            }
        )
    return sorted(
        rows,
        key=lambda item: (-item["score"], item["requested_window_hours"], item["referral_id"]),
    )


def schedule_plan() -> list[dict]:
    capacity = read_csv(DATA / "clinic_capacity.csv")
    used_slots: set[str] = set()
    plan = []
    for referral in ranked_referrals():
        candidates = [
            slot
            for slot in capacity
            if slot["service_line"] == referral["service_line"]
            and slot["slot_id"] not in used_slots
        ]
        candidates.sort(
            key=lambda slot: (
                slot["location"] != referral["preferred_location"],
                datetime.fromisoformat(slot["start_time"]),
            )
        )
        if candidates:
            slot = candidates[0]
            used_slots.add(slot["slot_id"])
            status = "scheduled"
        else:
            slot = {
                "slot_id": "ESCALATE",
                "location": referral["preferred_location"],
                "start_time": "needs_manual_capacity_review",
                "clinician": "capacity command center",
                "visit_type": "manual_review",
            }
            status = "capacity_gap"
        plan.append({**referral, "status": status, "slot": slot})
    return plan


def audit_plan() -> dict:
    payer_rules = load_json(DATA / "payer_rules.json")
    rules = load_json(DATA / "escalation_rules.json")
    actions = schedule_plan()
    audit_rows = []
    for action in actions:
        payer = payer_rules[action["payer"]]
        prior_auth = action["service_line"] in payer["prior_auth_required"]
        audit_rows.append(
            {
                "referral_id": action["referral_id"],
                "priority": action["priority"],
                "status": action["status"],
                "slot_id": action["slot"]["slot_id"],
                "prior_auth_required": prior_auth,
                "audit_required": action["priority"] in rules["audit_required_for"],
                "rationale": f"{action['priority']} priority from {', '.join(action['drivers']) or 'default rules'}; {payer['notes']}",
            }
        )
    return {
        "summary": {
            "total_referrals": len(actions),
            "scheduled": sum(1 for item in actions if item["status"] == "scheduled"),
            "capacity_gaps": sum(1 for item in actions if item["status"] == "capacity_gap"),
            "critical_or_high": sum(1 for item in actions if item["priority"] in {"critical", "high"}),
        },
        "audit": audit_rows,
    }


def intake_summary() -> dict:
    referrals = load_referrals()
    required_fields = [
        "referral_id",
        "patient_alias",
        "age",
        "service_line",
        "reason",
        "requested_window_hours",
        "risk_flags",
        "preferred_location",
        "payer",
        "received_at",
    ]
    raw_rows = read_csv(DATA / "referrals.csv")
    missing = []
    seen: set[str] = set()
    duplicates = []
    for row in raw_rows:
        referral_id = row.get("referral_id", "")
        if referral_id in seen:
            duplicates.append(referral_id)
        seen.add(referral_id)
        empty = [field for field in required_fields if not row.get(field)]
        if empty:
            missing.append({"referral_id": referral_id or "unknown", "fields": empty})

    windows = [referral.requested_window_hours for referral in referrals]
    return {
        "source": str(DATA / "referrals.csv"),
        "total_referrals": len(referrals),
        "service_lines": dict(sorted(Counter(item.service_line for item in referrals).items())),
        "preferred_locations": dict(sorted(Counter(item.preferred_location for item in referrals).items())),
        "payers": dict(sorted(Counter(item.payer for item in referrals).items())),
        "requested_window_hours": {
            "min": min(windows) if windows else None,
            "max": max(windows) if windows else None,
        },
        "duplicates": duplicates,
        "missing_fields": missing,
    }


def agent_topology() -> dict:
    return {
        "default_agent": "main",
        "pattern": "main coordinator delegates to leaf specialist sub-agents with sessions_spawn",
        "config": "/sandbox/.openclaw/openclaw.json",
        "skills_dir": "/sandbox/.openclaw/skills",
        "shared_data": "/sandbox/.openclaw/workspace/data",
        "shared_tools": "/sandbox/.openclaw/workspace/scripts",
        "specialists": [
            {
                "id": "intake",
                "workspace": "/sandbox/.openclaw/workspace-intake",
                "skill": "healthcare-intake-normalization",
                "tool": "care_backlog_analyzer.py intake",
                "can_spawn": False,
            },
            {
                "id": "clinical-triage",
                "workspace": "/sandbox/.openclaw/workspace-clinical-triage",
                "skill": "healthcare-clinical-triage",
                "tool": "care_backlog_analyzer.py triage",
                "can_spawn": False,
            },
            {
                "id": "capacity-planner",
                "workspace": "/sandbox/.openclaw/workspace-capacity-planner",
                "skill": "healthcare-capacity-planning",
                "tool": "care_backlog_analyzer.py schedule",
                "can_spawn": False,
            },
            {
                "id": "payer-audit",
                "workspace": "/sandbox/.openclaw/workspace-payer-audit",
                "skill": "healthcare-payer-audit",
                "tool": "care_backlog_analyzer.py audit",
                "can_spawn": False,
            },
            {
                "id": "command-writer",
                "workspace": "/sandbox/.openclaw/workspace-command-writer",
                "skill": "healthcare-command-summary",
                "tool": "care_backlog_analyzer.py report",
                "can_spawn": False,
            },
        ],
        "least_privilege": {
            "main": ["read", "exec", "process", "agents_list", "sessions_spawn", "sessions_yield", "subagents"],
            "specialists": ["read", "exec", "process", "session_status"],
            "denied_to_specialists": ["sessions_spawn", "sessions_send", "sessions_yield", "subagents", "write", "edit", "apply_patch"],
        },
    }


def emit_markdown_report() -> str:
    audit = audit_plan()
    actions = schedule_plan()
    lines = [
        "# 48-Hour Care Backlog Action Plan",
        "",
        f"- Total referrals: {audit['summary']['total_referrals']}",
        f"- Scheduled from available capacity: {audit['summary']['scheduled']}",
        f"- Capacity gaps: {audit['summary']['capacity_gaps']}",
        f"- Critical/high priority: {audit['summary']['critical_or_high']}",
        "",
        "## Recommended Actions",
        "",
        "| Referral | Priority | Service | Status | Slot | Rationale |",
        "|---|---|---|---|---|---|",
    ]
    audit_by_id = {item["referral_id"]: item for item in audit["audit"]}
    for action in actions:
        audit_row = audit_by_id[action["referral_id"]]
        lines.append(
            f"| {action['referral_id']} | {action['priority']} | {action['service_line']} | "
            f"{action['status']} | {action['slot']['slot_id']} | {audit_row['rationale']} |"
        )
    prior_auth_rows = [row for row in audit["audit"] if row["prior_auth_required"]]
    audit_required_rows = [row for row in audit["audit"] if row["audit_required"]]
    lines.extend(
        [
            "",
            "## Audit And Payer Review",
            "",
            f"- Prior authorization required: {len(prior_auth_rows)}",
            f"- Critical/high audit required: {len(audit_required_rows)}",
        ]
    )
    if prior_auth_rows:
        lines.append("- Prior authorization flags: " + ", ".join(row["referral_id"] for row in prior_auth_rows))
    if audit_required_rows:
        lines.append("- Audit-required referrals: " + ", ".join(row["referral_id"] for row in audit_required_rows))
    lines.extend(
        [
            "",
            "## Operational Notes",
            "",
            "- The workflow uses multiple specialist agents but keeps data and tools inside a governed sandbox.",
            "- OpenShell policy can block unapproved egress and surface operator approval decisions.",
            "- NemoClaw routes inference through the gateway so model credentials are not embedded in agent files.",
            "- The audit output turns agent activity into a reviewable operational artifact.",
        ]
    )
    return "\n".join(lines)


def emit_watch_summary() -> str:
    audit = audit_plan()
    actions = schedule_plan()
    priority_actions = [
        item for item in actions if item["priority"] in {"critical", "high"}
    ]
    capacity_gaps = [item for item in actions if item["status"] == "capacity_gap"]
    auth_flags = [
        row for row in audit["audit"] if row["prior_auth_required"]
    ]
    lines = [
        "CARE_BACKLOG_WATCH",
        f"total_referrals={audit['summary']['total_referrals']}",
        f"critical_or_high={audit['summary']['critical_or_high']}",
        f"scheduled={audit['summary']['scheduled']}",
        f"capacity_gaps={audit['summary']['capacity_gaps']}",
        "",
        "urgent_actions:",
    ]
    for item in priority_actions[:5]:
        lines.append(
            f"- {item['referral_id']} {item['priority']} {item['service_line']} -> "
            f"{item['status']} {item['slot']['slot_id']}"
        )
    lines.append("")
    lines.append("capacity_gaps:")
    if capacity_gaps:
        for item in capacity_gaps:
            lines.append(f"- {item['referral_id']} {item['service_line']} at {item['preferred_location']}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("prior_auth_flags:")
    if auth_flags:
        for row in auth_flags:
            lines.append(f"- {row['referral_id']} slot={row['slot_id']} audit_required={row['audit_required']}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append(
        "governance_note=NemoClaw/OpenShell lets this recurring agent work run inside a sandbox with routed inference, local synthetic data, and policy-visible egress."
    )
    return "\n".join(lines)


def trigger_blocked_lookup() -> int:
    rules = load_json(DATA / "escalation_rules.json")
    url = rules["blocked_lookup_url"]
    print(f"Attempting intentional egress lookup: {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = response.read(200).decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        print("EGRESS_BLOCKED")
        print(f"reason={exc}", file=sys.stderr)
        return 0
    print("EGRESS_UNEXPECTEDLY_ALLOWED")
    print(body)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "intake",
            "triage",
            "schedule",
            "audit",
            "report",
            "watch-summary",
            "agent-topology",
            "blocked-lookup",
        ],
        help="Analysis command to run.",
    )
    args = parser.parse_args()

    if args.command == "intake":
        print(json.dumps(intake_summary(), indent=2))
    elif args.command == "triage":
        print(json.dumps(ranked_referrals(), indent=2))
    elif args.command == "schedule":
        print(json.dumps(schedule_plan(), indent=2))
    elif args.command == "audit":
        print(json.dumps(audit_plan(), indent=2))
    elif args.command == "report":
        print(emit_markdown_report())
    elif args.command == "watch-summary":
        print(emit_watch_summary())
    elif args.command == "agent-topology":
        print(json.dumps(agent_topology(), indent=2))
    elif args.command == "blocked-lookup":
        return trigger_blocked_lookup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
