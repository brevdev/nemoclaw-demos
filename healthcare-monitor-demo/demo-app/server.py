#!/usr/bin/env python3
"""Local frontend/backend for the healthcare monitor example.

The server is intentionally small. It exposes a fixed allowlist of commands so
the UI can run the same repeatable checks from the browser.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import subprocess
import fcntl
import struct
import termios
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = APP_DIR.parent
SANDBOX = "healthcare-monitor"
RELEASE_PROVIDER = "build"
RELEASE_MODEL = "nvidia/nemotron-3-super-120b-a12b"
RELEASE_ENDPOINT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
STATE_DIR = APP_DIR / "state"
DECISIONS_FILE = STATE_DIR / "operator-decisions.json"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MESSAGE_FAILED_RE = re.compile(r"^\s*⚠️\s*✉️\s*Message failed\s*$", re.MULTILINE)
UNDICI_WARNING_RE = re.compile(r"^\(node:\d+\) \[UNDICI-EHPA\].*(?:\n.*trace-warnings.*)?$", re.MULTILINE)
TOPOLOGY_FILES = {
    "openclaw.json": "OpenClaw agent and tool-permission topology",
    "Dockerfile.sandbox": "Sandbox image build and file-baking workflow",
    "policy.yaml": "Local OpenShell egress policy preset",
    "workspaces/main/AGENTS.md": "Main coordinator prompt",
    "workspaces/intake/AGENTS.md": "Intake leaf-agent prompt",
    "workspaces/clinical-triage/AGENTS.md": "Clinical triage leaf-agent prompt",
    "workspaces/capacity-planner/AGENTS.md": "Capacity planner leaf-agent prompt",
    "workspaces/payer-audit/AGENTS.md": "Payer audit leaf-agent prompt",
    "workspaces/command-writer/AGENTS.md": "Command writer leaf-agent prompt",
    "skills/healthcare-monitor-routing/SKILL.md": "Routing skill",
    "skills/healthcare-intake-normalization/SKILL.md": "Intake skill",
    "skills/healthcare-clinical-triage/SKILL.md": "Triage skill",
    "skills/healthcare-capacity-planning/SKILL.md": "Capacity skill",
    "skills/healthcare-payer-audit/SKILL.md": "Payer/audit skill",
    "skills/healthcare-command-summary/SKILL.md": "Command summary skill",
    "workspace/scripts/care_backlog_analyzer.py": "Shared deterministic Python CLI",
}
PROBE_WRAPPER = """
tmp="$(mktemp)"
nemoclaw "$1" connect --probe-only >"$tmp" 2>&1 &
pid="$!"
for _ in $(seq 1 30); do
  if grep -q "Probe complete: OpenClaw gateway is running" "$tmp"; then
    cat "$tmp"
    kill "$pid" >/dev/null 2>&1 || true
    rm -f "$tmp"
    exit 0
  fi
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    cat "$tmp"
    wait "$pid"
    status="$?"
    rm -f "$tmp"
    exit "$status"
  fi
  sleep 1
done
cat "$tmp"
kill "$pid" >/dev/null 2>&1 || true
rm -f "$tmp"
exit 124
"""
GATEWAY_PORT_RE = re.compile(r"(?:127\.0\.0\.1|\[::1\]):(?P<port>\d+)")
DEFAULT_OPENCLAW_GATEWAY_PORT = "18789"
OPENCLAW_GATEWAY_PORT_RANGE = range(18789, 18900)


class OpenShellTerminal:
    """Single fixed PTY session for the embedded OpenShell terminal."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pid: int | None = None
        self.fd: int | None = None
        self.started_at: str | None = None
        self.exit_code: int | None = None

    def _close_locked(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.pid = None

    def _resize_locked(self, rows: int, cols: int) -> None:
        if self.fd is None:
            return
        packed = struct.pack("HHHH", max(10, rows), max(40, cols), 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, packed)

    def _running_locked(self) -> bool:
        if self.pid is None:
            return False
        try:
            done_pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self._close_locked()
            return False
        if done_pid == 0:
            return True
        self.exit_code = os.waitstatus_to_exitcode(status)
        self._close_locked()
        return False

    def start(self, rows: int = 28, cols: int = 100) -> dict:
        with self.lock:
            if self._running_locked():
                return self.status_locked()
            self.exit_code = None
            pid, fd = pty.fork()
            if pid == 0:
                try:
                    os.chdir(RUNTIME_ROOT)
                    os.execvpe("openshell", ["openshell", "term"], read_env())
                except Exception as exc:
                    os.write(2, f"failed to start openshell term: {exc}\n".encode("utf-8"))
                    os._exit(127)
            self.pid = pid
            self.fd = fd
            self.started_at = utc_now()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self._resize_locked(rows, cols)
            return self.status_locked()

    def stop(self) -> dict:
        with self.lock:
            if self.pid is not None:
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            self._close_locked()
            return self.status_locked()

    def write(self, data: str) -> dict:
        with self.lock:
            if not self._running_locked() or self.fd is None:
                return self.status_locked()
            os.write(self.fd, data.encode("utf-8", errors="replace"))
            return self.status_locked()

    def read(self) -> dict:
        chunks: list[bytes] = []
        with self.lock:
            if not self._running_locked() or self.fd is None:
                return {**self.status_locked(), "chunk": ""}
            while True:
                ready, _, _ = select.select([self.fd], [], [], 0)
                if not ready:
                    break
                try:
                    chunk = os.read(self.fd, 65536)
                except BlockingIOError:
                    break
                except OSError:
                    self._close_locked()
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8", errors="replace")
            return {**self.status_locked(), "chunk": visible_text(text)}

    def resize(self, rows: int, cols: int) -> dict:
        with self.lock:
            if self._running_locked():
                self._resize_locked(rows, cols)
            return self.status_locked()

    def status(self) -> dict:
        with self.lock:
            return self.status_locked()

    def status_locked(self) -> dict:
        running = self._running_locked() if self.pid is not None else False
        return {
            "running": running,
            "pid": self.pid,
            "startedAt": self.started_at,
            "exitCode": self.exit_code,
            "command": "openshell term",
            "cwd": visible_text(str(RUNTIME_ROOT)),
        }


TERMINAL = OpenShellTerminal()


def read_env() -> dict[str, str]:
    env = os.environ.copy()
    env_file = RUNTIME_ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    if env.get("NEMOCLAW_ALLOW_PROVIDER_OVERRIDE") != "1":
        env["NEMOCLAW_PROVIDER"] = RELEASE_PROVIDER
        env["NEMOCLAW_MODEL"] = RELEASE_MODEL
        env["NEMOCLAW_ENDPOINT_URL"] = RELEASE_ENDPOINT_URL
    if not env.get("NVIDIA_API_KEY") and env.get("NEMOCLAW_PROVIDER_KEY"):
        env["NVIDIA_API_KEY"] = env["NEMOCLAW_PROVIDER_KEY"]
    return env


def run_command(command: list[str], cwd: Path, timeout: int = 120) -> dict:
    env = read_env()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "exitCode": completed.returncode,
            "stdout": clean_output(completed.stdout),
            "stderr": clean_output(completed.stderr),
            "command": visible_text(display_command(command)),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = clean_output(exc.stdout or "")
        stderr = clean_output(exc.stderr or "")
        if is_successful_probe_timeout(command, stdout):
            if stderr:
                stderr += "\n"
            stderr += "Probe reported success before the command timeout."
            return {
                "ok": True,
                "exitCode": 0,
                "stdout": stdout,
                "stderr": clean_output(stderr),
                "command": visible_text(display_command(command)),
            }
        if stderr:
            stderr += "\n"
        stderr += f"Timed out after {timeout}s."
        return {
            "ok": False,
            "exitCode": 124,
            "stdout": stdout,
            "stderr": clean_output(stderr),
            "command": visible_text(display_command(command)),
        }


def is_successful_probe_timeout(command: list[str], stdout: str) -> bool:
    return (
        len(command) >= 4
        and command[0] == "nemoclaw"
        and command[2:] == ["connect", "--probe-only"]
        and "Probe complete: OpenClaw gateway is running" in stdout
    )


def clean_output(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = ANSI_RE.sub("", text)
    text = MESSAGE_FAILED_RE.sub("", text)
    text = UNDICI_WARNING_RE.sub("", text)
    text = visible_text(text)
    return text.rstrip() + ("\n" if text.endswith("\n") else "")


def parse_agent_json(result: dict) -> dict | None:
    for key in ("stdout", "stderr"):
        text = result.get(key, "")
        if not text:
            continue
        for candidate in (text.strip(), extract_json_object(text)):
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def compact_agent_stderr(stderr: str) -> str:
    if not stderr:
        return ""
    lines: list[str] = []
    if "falling back to embedded" in stderr:
        lines.append("Gateway agent fallback used; embedded runner completed.")
    elif extract_json_object(stderr):
        lines.append("OpenClaw emitted agent JSON on stderr; parsed successfully.")
    else:
        return stderr
    return "\n".join(lines) + "\n"


def visible_text(text: str) -> str:
    return text


def run_local_json(command: str) -> object:
    result = run_command(
        ["python3", "workspace/scripts/care_backlog_analyzer.py", command],
        RUNTIME_ROOT,
        90,
    )
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or result["stdout"])
    return json.loads(result["stdout"])


def sandbox_name() -> str:
    return read_env().get("NEMOCLAW_SANDBOX", SANDBOX)


def provider_label(provider: str) -> str:
    if provider == "build":
        return "build.nvidia.com"
    if provider == "custom":
        return "custom"
    return provider


def policy_summary() -> dict:
    policy_text = (RUNTIME_ROOT / "policy.yaml").read_text(encoding="utf-8")
    name = ""
    description = ""
    endpoints: list[dict[str, str]] = []
    binaries: list[str] = []
    current: dict[str, str] = {}
    for raw in policy_text.splitlines():
        line = raw.strip()
        if line.startswith("name:") and not name:
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:") and not description:
            description = line.split(":", 1)[1].strip()
        elif line.startswith("- host:"):
            if current:
                endpoints.append(current)
            current = {"host": line.split(":", 1)[1].strip()}
        elif line.startswith("port:") and current:
            current["port"] = line.split(":", 1)[1].strip()
        elif line.startswith("access:") and current:
            current["access"] = line.split(":", 1)[1].strip()
        elif line.startswith("- { path:"):
            binaries.append(line.split("path:", 1)[1].split("}", 1)[0].strip())
    if current:
        endpoints.append(current)
    app_port = os.environ.get("PORT", "5177")
    app_host = os.environ.get("HOST", "127.0.0.1")
    note = (
        f"The policy opens localhost and 127.0.0.1 on port {endpoints[0]['port']} "
        "so sandboxed tools can reach the host-side demo app and its local API."
        if endpoints
        else "No local endpoint policy found."
    )
    return {
        "name": name,
        "description": description,
        "endpoints": endpoints,
        "binaries": binaries,
        "appPort": app_port,
        "appHost": app_host,
        "note": note,
    }


def shellish(command: list[str]) -> str:
    return " ".join(quote(part) for part in command)


def display_command(command: list[str]) -> str:
    if len(command) >= 4 and command[:2] == ["bash", "-lc"] and command[2] == PROBE_WRAPPER:
        return shellish(["nemoclaw", command[4], "connect", "--probe-only"])
    return shellish(command)


def quote(part: str) -> str:
    if part.replace("-", "").replace("_", "").replace("/", "").replace(".", "").isalnum():
        return part
    return "'" + part.replace("'", "'\"'\"'") + "'"


def extract_agent_text(result: dict) -> str:
    try:
        parsed = parse_agent_json(result)
        if parsed is None:
            return result["stdout"]
        final_text = parsed.get("result", {}).get("meta", {}).get("finalAssistantVisibleText")
        if final_text:
            return final_text
        payloads = parsed["result"]["payloads"]
        return "\n\n".join(item.get("text", "") for item in payloads if item.get("text"))
    except Exception:
        return result["stdout"]


def extract_agent_meta_summary(result: dict) -> str:
    parsed = parse_agent_json(result) or {}
    meta = parsed.get("result", {}).get("meta", {})
    trace = meta.get("executionTrace", {})
    tool_summary = meta.get("toolSummary", {})
    provider = trace.get("winnerProvider") or meta.get("agentMeta", {}).get("provider") or "unknown"
    model = trace.get("winnerModel") or meta.get("agentMeta", {}).get("model") or "unknown"
    calls = tool_summary.get("calls", "unknown")
    failures = tool_summary.get("failures", "unknown")
    tools = ", ".join(tool_summary.get("tools", [])) or "unknown"
    return "\n".join(
        [
            "## Agentic Execution",
            "",
            "- Coordinator: main",
            "- Specialists requested: intake, clinical-triage, capacity-planner, payer-audit",
            f"- Model route: {provider}/{model}",
            f"- Tool calls: {calls}; tools: {tools}; failures: {failures}",
            "- Final evidence source: deployed sandbox report",
        ]
    )


def deployed_report_text() -> str:
    result = run_command(
        [
            "openshell",
            "sandbox",
            "exec",
            "--name",
            sandbox_name(),
            "--",
            "python3",
            "/sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py",
            "report",
        ],
        RUNTIME_ROOT,
        90,
    )
    if result["ok"] and result["stdout"].strip():
        return result["stdout"].strip()
    fallback = run_command(
        ["python3", "workspace/scripts/care_backlog_analyzer.py", "report"],
        RUNTIME_ROOT,
        90,
    )
    if fallback["ok"] and fallback["stdout"].strip():
        return fallback["stdout"].strip()
    return extract_agent_text(result)


def agent_plan_text(result: dict) -> str:
    return f"{extract_agent_meta_summary(result)}\n\n{deployed_report_text()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fresh_session(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


def parse_openclaw_gateway_port(ss_output: str) -> str | None:
    ports: list[int] = []
    for match in GATEWAY_PORT_RE.finditer(ss_output):
        port = int(match.group("port"))
        if port in OPENCLAW_GATEWAY_PORT_RANGE and port not in ports:
            ports.append(port)
    if not ports:
        return None
    return str(sorted(ports)[0])


def discover_openclaw_gateway_port(sandbox: str) -> str:
    result = run_command(
        ["openshell", "sandbox", "exec", "--name", sandbox, "--", "ss", "-ltnH"],
        RUNTIME_ROOT,
        15,
    )
    detected = parse_openclaw_gateway_port(result.get("stdout", ""))
    if detected:
        return detected
    configured = read_env().get("OPENCLAW_GATEWAY_PORT", "").strip()
    if configured.isdigit() and int(configured) > 0:
        return configured
    return DEFAULT_OPENCLAW_GATEWAY_PORT


def multi_agent_plan_prompt() -> str:
    return (
        "You must complete this exact tool checklist before writing any answer. "
        "1 call agents_list. "
        "2 call sessions_spawn once with agentId intake and ask it to run the intake workflow. "
        "3 call sessions_spawn once with agentId clinical-triage and ask it to rank critical/high referrals. "
        "4 call sessions_spawn once with agentId capacity-planner and ask it to schedule the queue. "
        "5 call sessions_spawn once with agentId payer-audit and ask it to identify prior authorization and audit flags. "
        "6 call exec with command python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report. "
        "Do not call sessions_yield. Do not wait after sessions_spawn. Ignore intermediate subagent text until all six checklist items are done. "
        "Use the exec report as the source of truth for the final answer, including payer and audit implications; do not say specialist results are pending. "
        "After item 6, answer directly in this CLI session with sections: Agent execution, Situation, Priority actions, Capacity plan, Audit/payer implications, Governance note. "
        "Synthetic data only; no medical advice. Do not call message, delivery, or channel-send tools. Return the answer directly in this CLI session only."
    )


def openclaw_agent_plan_command(sandbox: str) -> list[str]:
    return [
        "openshell",
        "sandbox",
        "exec",
        "--name",
        sandbox,
        "--",
        "env",
        f"OPENCLAW_GATEWAY_PORT={discover_openclaw_gateway_port(sandbox)}",
        "openclaw",
        "agent",
        "--agent",
        "main",
        "--json",
        "-m",
        multi_agent_plan_prompt(),
        "--session-id",
        fresh_session("healthcare-monitor-plan"),
        "--timeout",
        "420",
    ]


def load_decisions() -> dict:
    if not DECISIONS_FILE.exists():
        return {"updatedAt": None, "items": {}}
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"updatedAt": None, "items": {}}


def save_decisions(decisions: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DECISIONS_FILE.write_text(json.dumps(decisions, indent=2) + "\n", encoding="utf-8")


def update_decision(payload: dict) -> dict:
    referral_id = str(payload.get("referralId", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not referral_id or not decision:
        raise ValueError("referralId and decision are required")
    decisions = load_decisions()
    item = decisions.setdefault("items", {}).setdefault(referral_id, {})
    item.update(
        {
            "decision": decision,
            "owner": str(payload.get("owner", "Command Center")).strip() or "Command Center",
            "note": str(payload.get("note", "")).strip(),
            "updatedAt": utc_now(),
        }
    )
    decisions["updatedAt"] = utc_now()
    save_decisions(decisions)
    return decisions


def file_watch() -> list[dict]:
    watched_roots = ["data", "workspace", "workspaces", "skills", "openclaw-cron", "policies"]
    rows = []
    for root_name in watched_roots:
        root = RUNTIME_ROOT / root_name
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            rows.append(
                {
                    "path": str(path.relative_to(RUNTIME_ROOT)),
                    "bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    ),
                    "ageSeconds": max(0, int(time.time() - stat.st_mtime)),
                }
            )
    for file_name in ["openclaw.json", "TOOLS.md", "policy.yaml", "Dockerfile.sandbox"]:
        path = RUNTIME_ROOT / file_name
        if not path.exists():
            continue
        stat = path.stat()
        rows.append(
            {
                "path": file_name,
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
                "ageSeconds": max(0, int(time.time() - stat.st_mtime)),
            }
        )
    return rows


def dashboard_payload() -> dict:
    triage = run_local_json("triage")
    schedule = run_local_json("schedule")
    audit = run_local_json("audit")
    decisions = load_decisions()
    schedule_by_id = {item["referral_id"]: item for item in schedule}
    audit_by_id = {item["referral_id"]: item for item in audit["audit"]}
    referrals = []
    for item in triage:
        referral_id = item["referral_id"]
        scheduled = schedule_by_id.get(referral_id, {})
        audit_row = audit_by_id.get(referral_id, {})
        referrals.append(
            {
                **item,
                "status": scheduled.get("status", "unknown"),
                "slot": scheduled.get("slot", {}),
                "priorAuthRequired": audit_row.get("prior_auth_required", False),
                "auditRequired": audit_row.get("audit_required", False),
                "operator": decisions.get("items", {}).get(referral_id, {}),
            }
        )
    return {
        "updatedAt": utc_now(),
        "summary": audit["summary"],
        "referrals": referrals,
        "decisions": decisions,
        "files": file_watch(),
    }


def read_csv_file(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def evidence_payload() -> dict:
    data_dir = RUNTIME_ROOT / "data"
    return {
        "updatedAt": utc_now(),
        "logic": {
            "triage": [
                "Reads referrals.csv risk_flags and escalation_rules.json.",
                "critical_flags outrank high_flags; high_flags outrank medium_flags.",
                "Scores are critical=100, high=80, medium=50, routine=20.",
                "requested_window_hours breaks ties after score, then referral_id.",
                "clinical_notes.json note summaries are attached as evidence, but risk_flags drive the priority score.",
            ],
            "capacity": [
                "Starts from the priority-ranked triage list.",
                "Reads clinic_capacity.csv and filters slots by matching service_line.",
                "Prefers the referral's preferred_location, then the earliest start_time.",
                "Uses each slot once. If no matching slot remains, status becomes capacity_gap with slot_id ESCALATE.",
            ],
            "audit": [
                "Reads scheduled actions from the capacity tool.",
                "For each referral, looks up its payer from referrals.csv in payer_rules.json.",
                "Compares the referral service_line to that payer's prior_auth_required list.",
                "If the service line appears in the payer list, prior_auth_required=True.",
                "Reads escalation_rules.json audit_required_for to flag critical/high actions for review.",
                "Builds a rationale from priority drivers plus payer notes.",
            ],
            "watch": [
                "Summarizes audit and schedule outputs.",
                "Reports total referrals, critical/high count, scheduled count, capacity gaps, urgent actions, and prior-auth flags.",
                "Adds the governance note used in the recurring operations story.",
            ],
        },
        "files": {
            "referrals": read_csv_file(data_dir / "referrals.csv"),
            "capacity": read_csv_file(data_dir / "clinic_capacity.csv"),
            "notes": json.loads((data_dir / "clinical_notes.json").read_text(encoding="utf-8")),
            "escalationRules": json.loads((data_dir / "escalation_rules.json").read_text(encoding="utf-8")),
            "payerRules": json.loads((data_dir / "payer_rules.json").read_text(encoding="utf-8")),
        },
    }


def topology_payload() -> dict:
    return {
        "updatedAt": utc_now(),
        "summary": {
            "pattern": "main coordinator delegates to leaf OpenClaw subagents, which call a shared deterministic Python CLI",
            "mainTools": ["agents_list", "sessions_spawn", "sessions_yield", "read", "exec", "process"],
            "leafTools": ["read", "exec", "process", "session_status"],
            "deniedToLeaves": ["sessions_spawn", "sessions_send", "sessions_yield", "subagents", "write", "edit"],
        },
        "deploymentFlow": [
            {
                "step": "Build image",
                "actor": "host",
                "tool": "nemoclaw onboard --from Dockerfile.sandbox",
                "description": "NemoClaw builds a custom sandbox image from the repo-local Dockerfile.",
            },
            {
                "step": "Bake config",
                "actor": "Dockerfile.sandbox",
                "tool": "COPY openclaw.json /sandbox/.openclaw/openclaw.json",
                "description": "The OpenClaw config is copied before runtime lock-down, so it stays visible but read-only inside the sandbox.",
            },
            {
                "step": "Bake workspaces",
                "actor": "Dockerfile.sandbox",
                "tool": "COPY workspaces skills workspace data openclaw-cron",
                "description": "Per-agent prompts, skills, Python CLI, synthetic data, and cron payloads are copied into the writable data zone used by the sandbox runtime.",
            },
            {
                "step": "Lock runtime",
                "actor": "OpenShell",
                "tool": "Landlock + seccomp + filtered egress",
                "description": "After the image starts, OpenShell enforces the filesystem and network boundaries used by the demo.",
            },
        ],
        "callFlow": [
            {
                "step": "Discover",
                "actor": "main",
                "tool": "agents_list",
                "description": "Confirms the specialist agents that are available in OpenClaw.",
            },
            {
                "step": "Delegate intake",
                "actor": "main -> intake",
                "tool": "sessions_spawn(agentId='intake')",
                "cli": "python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py intake",
            },
            {
                "step": "Delegate triage",
                "actor": "main -> clinical-triage",
                "tool": "sessions_spawn(agentId='clinical-triage')",
                "cli": "python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py triage",
            },
            {
                "step": "Delegate capacity",
                "actor": "main -> capacity-planner",
                "tool": "sessions_spawn(agentId='capacity-planner')",
                "cli": "python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py schedule",
            },
            {
                "step": "Delegate audit",
                "actor": "main -> payer-audit",
                "tool": "sessions_spawn(agentId='payer-audit')",
                "cli": "python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py audit",
            },
            {
                "step": "Finalize",
                "actor": "main or command-writer",
                "tool": "exec",
                "cli": "python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report",
            },
        ],
        "agents": [
            {
                "id": "main",
                "role": "Coordinator",
                "workspace": "workspaces/main",
                "skills": ["healthcare-monitor-routing", "healthcare-command-summary", "healthcare-governance-egress"],
                "cli": "orchestrates specialists; may run report as final evidence source",
                "canSpawn": True,
                "files": ["workspaces/main/AGENTS.md", "openclaw.json", "skills/healthcare-monitor-routing/SKILL.md"],
            },
            {
                "id": "intake",
                "role": "Queue normalization",
                "workspace": "workspaces/intake",
                "skills": ["healthcare-intake-normalization"],
                "cli": "care_backlog_analyzer.py intake",
                "canSpawn": False,
                "files": ["workspaces/intake/AGENTS.md", "skills/healthcare-intake-normalization/SKILL.md"],
            },
            {
                "id": "clinical-triage",
                "role": "Deterministic risk ranking",
                "workspace": "workspaces/clinical-triage",
                "skills": ["healthcare-clinical-triage"],
                "cli": "care_backlog_analyzer.py triage",
                "canSpawn": False,
                "files": ["workspaces/clinical-triage/AGENTS.md", "skills/healthcare-clinical-triage/SKILL.md"],
            },
            {
                "id": "capacity-planner",
                "role": "Slot matching",
                "workspace": "workspaces/capacity-planner",
                "skills": ["healthcare-capacity-planning"],
                "cli": "care_backlog_analyzer.py schedule",
                "canSpawn": False,
                "files": ["workspaces/capacity-planner/AGENTS.md", "skills/healthcare-capacity-planning/SKILL.md"],
            },
            {
                "id": "payer-audit",
                "role": "Prior authorization and audit flags",
                "workspace": "workspaces/payer-audit",
                "skills": ["healthcare-payer-audit", "healthcare-governance-egress"],
                "cli": "care_backlog_analyzer.py audit",
                "canSpawn": False,
                "files": ["workspaces/payer-audit/AGENTS.md", "skills/healthcare-payer-audit/SKILL.md"],
            },
            {
                "id": "command-writer",
                "role": "Command-center summary",
                "workspace": "workspaces/command-writer",
                "skills": ["healthcare-command-summary", "healthcare-governance-egress"],
                "cli": "care_backlog_analyzer.py report",
                "canSpawn": False,
                "files": ["workspaces/command-writer/AGENTS.md", "skills/healthcare-command-summary/SKILL.md"],
            },
        ],
        "files": [
            {"path": path, "label": label}
            for path, label in TOPOLOGY_FILES.items()
            if (RUNTIME_ROOT / path).exists()
        ],
    }


def topology_file_payload(path_text: str) -> dict:
    path_text = path_text.strip()
    if path_text not in TOPOLOGY_FILES:
        raise ValueError("file is not in the topology allowlist")
    path = (RUNTIME_ROOT / path_text).resolve()
    if not path.is_file() or RUNTIME_ROOT.resolve() not in path.parents:
        raise ValueError("file is unavailable")
    return {
        "path": path_text,
        "label": TOPOLOGY_FILES[path_text],
        "content": visible_text(path.read_text(encoding="utf-8")),
    }


def cron_watch_message() -> str:
    jobs = json.loads((RUNTIME_ROOT / "openclaw-cron/jobs.json").read_text(encoding="utf-8"))
    return jobs["jobs"][0]["payload"]["message"]


def one_line_message(message: str) -> str:
    return " ".join(part.strip() for part in message.splitlines() if part.strip())


def compact_operator_evidence() -> str:
    decisions = load_decisions().get("items", {})
    triage = run_local_json("triage")
    schedule = run_local_json("schedule")
    audit = run_local_json("audit")
    watch = run_command(
        ["python3", "workspace/scripts/care_backlog_analyzer.py", "watch-summary"],
        RUNTIME_ROOT,
        90,
    )["stdout"].strip()

    triage_by_id = {item["referral_id"]: item for item in triage}
    schedule_by_id = {item["referral_id"]: item for item in schedule}
    audit_by_id = {item["referral_id"]: item for item in audit["audit"]}
    decision_lines = []
    for referral_id, decision in sorted(decisions.items()):
        triage_row = triage_by_id.get(referral_id, {})
        schedule_row = schedule_by_id.get(referral_id, {})
        audit_row = audit_by_id.get(referral_id, {})
        slot = schedule_row.get("slot", {})
        decision_lines.append(
            f"- {referral_id}: operator={decision.get('decision', 'pending')}; "
            f"priority={triage_row.get('priority', 'unknown')}; "
            f"service={triage_row.get('service_line', 'unknown')}; "
            f"drivers={','.join(triage_row.get('drivers', [])) or 'none'}; "
            f"status={schedule_row.get('status', 'unknown')}; "
            f"slot={slot.get('slot_id', 'none')}; "
            f"prior_auth={audit_row.get('prior_auth_required', False)}; "
            f"audit_required={audit_row.get('audit_required', False)}"
        )
    if not decision_lines:
        decision_lines.append("- none selected")

    return "\n".join(
        [
            "Summary:",
            f"- total={audit['summary']['total_referrals']}; scheduled={audit['summary']['scheduled']}; "
            f"capacity_gaps={audit['summary']['capacity_gaps']}; critical_or_high={audit['summary']['critical_or_high']}",
            "Operator decisions:",
            *decision_lines,
            "Watch signal:",
            watch,
        ]
    )


def deterministic_operator_analysis() -> str:
    decisions = load_decisions().get("items", {})
    triage = run_local_json("triage")
    schedule = run_local_json("schedule")
    audit = run_local_json("audit")

    triage_by_id = {item["referral_id"]: item for item in triage}
    schedule_by_id = {item["referral_id"]: item for item in schedule}
    audit_by_id = {item["referral_id"]: item for item in audit["audit"]}
    selected_ids = sorted(decisions) or [
        item["referral_id"] for item in triage if item["priority"] in {"critical", "high"}
    ][:5]

    risks = []
    actions = []
    audit_notes = []
    for referral_id in selected_ids:
        triage_row = triage_by_id.get(referral_id, {})
        schedule_row = schedule_by_id.get(referral_id, {})
        audit_row = audit_by_id.get(referral_id, {})
        decision = decisions.get(referral_id, {}).get("decision", "pending")
        priority = triage_row.get("priority", "unknown")
        service = triage_row.get("service_line", "unknown")
        drivers = ", ".join(triage_row.get("drivers", [])) or "default rules"
        status = schedule_row.get("status", "unknown")
        slot_id = schedule_row.get("slot", {}).get("slot_id", "none")
        prior_auth = audit_row.get("prior_auth_required", False)
        audit_required = audit_row.get("audit_required", False)

        if priority in {"critical", "high"} and decision in {"manual-review", "hold-for-auth", "pending"}:
            risks.append(
                f"- {referral_id}: {priority} {service} ({drivers}) is {status} in {slot_id}; operator={decision} may delay a high-urgency action."
            )
        elif priority in {"critical", "high"}:
            risks.append(
                f"- {referral_id}: {priority} {service} ({drivers}) remains a monitored urgent action; slot={slot_id}."
            )
        if prior_auth:
            actions.append(f"- {referral_id}: verify prior authorization before the scheduled slot {slot_id}.")
        elif decision == "hold-for-auth":
            actions.append(f"- {referral_id}: remove auth hold or document another blocker; analyzer shows prior_auth=False.")
        elif decision == "manual-review":
            actions.append(f"- {referral_id}: complete manual review quickly, then preserve the scheduled slot {slot_id}.")
        elif decision == "expedite":
            actions.append(f"- {referral_id}: proceed with expedited coordination for slot {slot_id}.")
        else:
            actions.append(f"- {referral_id}: keep current scheduled status and monitor for changes.")
        if audit_required or prior_auth:
            audit_notes.append(
                f"- {referral_id}: audit_required={audit_required}; prior_auth={prior_auth}; rationale={audit_row.get('rationale', 'not available')}"
            )

    if not risks:
        risks.append("- No selected referral creates a capacity gap; continue monitoring critical/high cases.")
    if not audit_notes:
        audit_notes.append("- No selected referral has a new audit or prior-authorization flag.")

    summary = audit["summary"]
    lines = [
        "# Decision Support Analysis",
        "",
        f"Backlog signal: {summary['total_referrals']} referrals, {summary['critical_or_high']} critical/high, "
        f"{summary['scheduled']} scheduled, {summary['capacity_gaps']} capacity gaps.",
        "",
        "## Risks",
        *risks[:5],
        "",
        "## Next Actions",
        *actions[:5],
        "",
        "## Audit/Policy",
        *audit_notes[:5],
        "- NemoClaw/OpenShell keeps this workflow in the sandbox with synthetic data and policy-visible egress.",
        "- Operational decision support only; not medical advice.",
    ]
    return "\n".join(lines)


def compact_agent_plan_evidence() -> str:
    schedule = run_local_json("schedule")
    audit = run_local_json("audit")
    urgent = [
        item for item in schedule if item["priority"] in {"critical", "high"}
    ]
    auth_flags = [
        item for item in audit["audit"] if item["prior_auth_required"]
    ]
    urgent_text = "; ".join(
        f"{item['referral_id']} {item['priority']} {item['service_line']}->{item['slot']['slot_id']}"
        for item in urgent
    )
    auth_text = "; ".join(
        f"{item['referral_id']} prior_auth={item['prior_auth_required']} audit={item['audit_required']}"
        for item in auth_flags
    )
    summary = audit["summary"]
    return one_line_message(
        f"total={summary['total_referrals']}; scheduled={summary['scheduled']}; "
        f"capacity_gaps={summary['capacity_gaps']}; critical_or_high={summary['critical_or_high']}. "
        f"Urgent actions: {urgent_text}. "
        f"Prior-auth flags: {auth_text}. "
        "Governance: synthetic local data, routed inference, OpenShell policy-visible egress."
    )


def compact_egress_evidence() -> str:
    rules = json.loads((RUNTIME_ROOT / "data/escalation_rules.json").read_text(encoding="utf-8"))
    return (
        "Blocked lookup tool attempts "
        f"{rules['blocked_lookup_url']}. Expected OpenShell policy result: "
        "Tunnel connection failed: 403 Forbidden."
    )


def openshell_monitor_payload() -> dict:
    sandbox = sandbox_name()
    logs = run_command(
        ["openshell", "logs", sandbox, "-n", "160", "--source", "gateway", "--source", "sandbox"],
        RUNTIME_ROOT,
        60,
    )
    policy = run_command(["nemoclaw", sandbox, "status"], RUNTIME_ROOT, 90)
    return {
        "updatedAt": utc_now(),
        "logs": logs,
        "policy": policy,
        "policyFile": clean_output(
            (RUNTIME_ROOT / "policy.yaml").read_text(encoding="utf-8")
        ),
        "blockedLookupRule": clean_output(
            (RUNTIME_ROOT / "policies/patch-allow-blocked-lookup.example.yaml").read_text(
                encoding="utf-8"
            )
        ),
    }


def command_for(action: str) -> tuple[list[str], Path, int, bool] | None:
    sandbox = sandbox_name()
    sandbox_exec = ["openshell", "sandbox", "exec", "--name", sandbox, "--"]
    analyzer = ["/sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py"]
    if action == "runtime-status":
        return (["nemoclaw", sandbox, "status"], RUNTIME_ROOT, 90, False)
    if action == "probe":
        return (
            [
                "bash",
                "-lc",
                PROBE_WRAPPER,
                "probe",
                sandbox,
            ],
            RUNTIME_ROOT,
            45,
            False,
        )
    if action == "verify-runtime":
        return (["./scripts/run-local-verification.sh"], RUNTIME_ROOT, 90, False)
    if action == "upload":
        return (["./scripts/show-sandbox-config.sh"], RUNTIME_ROOT, 90, False)
    if action == "policy-list":
        return (["nemoclaw", sandbox, "policy-list"], RUNTIME_ROOT, 90, False)
    if action == "apply-demo-policy":
        return (
            [
                "nemoclaw",
                sandbox,
                "policy-add",
                "--from-file",
                "policy.yaml",
                "--yes",
            ],
            RUNTIME_ROOT,
            180,
            False,
        )
    if action == "watch-summary":
        return (sandbox_exec + ["python3", *analyzer, "watch-summary"], RUNTIME_ROOT, 90, False)
    if action == "agent-topology":
        return (sandbox_exec + ["python3", *analyzer, "agent-topology"], RUNTIME_ROOT, 90, False)
    if action == "intake":
        return (sandbox_exec + ["python3", *analyzer, "intake"], RUNTIME_ROOT, 90, False)
    if action == "triage":
        return (sandbox_exec + ["python3", *analyzer, "triage"], RUNTIME_ROOT, 90, False)
    if action == "schedule":
        return (sandbox_exec + ["python3", *analyzer, "schedule"], RUNTIME_ROOT, 90, False)
    if action == "audit":
        return (sandbox_exec + ["python3", *analyzer, "audit"], RUNTIME_ROOT, 90, False)
    if action == "report":
        return (sandbox_exec + ["python3", *analyzer, "report"], RUNTIME_ROOT, 90, False)
    if action == "cron":
        return (sandbox_exec + ["cat", "/sandbox/.openclaw/cron/jobs.json"], RUNTIME_ROOT, 90, False)
    if action == "manual-watch":
        return (sandbox_exec + ["python3", *analyzer, "watch-summary"], RUNTIME_ROOT, 90, False)
    if action == "blocked-lookup":
        return (sandbox_exec + ["python3", *analyzer, "blocked-lookup"], RUNTIME_ROOT, 90, False)
    if action == "agent-plan":
        return (openclaw_agent_plan_command(sandbox), RUNTIME_ROOT, 480, True)
    if action == "agent-egress":
        return (sandbox_exec + ["python3", *analyzer, "blocked-lookup"], RUNTIME_ROOT, 90, False)
    return None


def command_preview(action: str) -> dict | None:
    if action == "operator-analysis":
        return {
            "action": action,
            "command": "python3 workspace/scripts/care_backlog_analyzer.py triage|schedule|audit + operator decisions",
            "cwd": visible_text(str(RUNTIME_ROOT)),
            "timeout": 0,
            "isAgent": False,
        }
    if action == "agent-plan":
        return {
            "action": action,
            "command": (
                f"openshell sandbox exec --name {quote(sandbox_name())} -- "
                "env OPENCLAW_GATEWAY_PORT=<detected-sandbox-gateway-port> "
                "openclaw agent --agent main --json -m <multi-agent-plan-checklist> "
                "--session-id healthcare-monitor-plan-<timestamp> --timeout 420"
            ),
            "cwd": visible_text(str(RUNTIME_ROOT)),
            "timeout": 480,
            "isAgent": True,
        }
    spec = command_for(action)
    if spec is None:
        return None
    command, cwd, timeout, is_agent = spec
    return {
        "action": action,
        "command": visible_text(display_command(command)),
        "cwd": visible_text(str(cwd)),
        "timeout": timeout,
        "isAgent": is_agent,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR / "public"), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            env = read_env()
            self.send_json(
                {
                    "sandbox": visible_text(env.get("NEMOCLAW_SANDBOX", SANDBOX)),
                    "provider": provider_label(env.get("NEMOCLAW_PROVIDER", RELEASE_PROVIDER)),
                    "model": env.get("NEMOCLAW_MODEL", RELEASE_MODEL),
                    "runtimeRoot": str(RUNTIME_ROOT),
                    "policySummary": policy_summary(),
                }
            )
            return
        if parsed.path == "/api/dashboard":
            self.send_json(dashboard_payload())
            return
        if parsed.path == "/api/evidence":
            self.send_json(evidence_payload())
            return
        if parsed.path == "/api/topology":
            self.send_json(topology_payload())
            return
        if parsed.path == "/api/topology/file":
            try:
                path = parse_qs(parsed.query).get("path", [""])[0]
                self.send_json(topology_file_payload(path))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/terminal/status":
            self.send_json(TERMINAL.status())
            return
        if parsed.path == "/api/terminal/read":
            self.send_json(TERMINAL.read())
            return
        if parsed.path.startswith("/api/preview/"):
            action = parsed.path[len("/api/preview/") :]
            preview = command_preview(action)
            if preview is None:
                self.send_error(404, "Unknown action")
                return
            self.send_json(preview)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/terminal/start":
            payload = self.read_json_body()
            self.send_json(
                TERMINAL.start(
                    rows=int(payload.get("rows", 28)),
                    cols=int(payload.get("cols", 100)),
                )
            )
            return
        if parsed.path == "/api/terminal/stop":
            self.send_json(TERMINAL.stop())
            return
        if parsed.path == "/api/terminal/write":
            payload = self.read_json_body()
            self.send_json(TERMINAL.write(str(payload.get("data", ""))))
            return
        if parsed.path == "/api/terminal/resize":
            payload = self.read_json_body()
            self.send_json(
                TERMINAL.resize(
                    rows=int(payload.get("rows", 28)),
                    cols=int(payload.get("cols", 100)),
                )
            )
            return
        prefix = "/api/run/"
        if not parsed.path.startswith(prefix):
            if parsed.path == "/api/decision":
                try:
                    payload = self.read_json_body()
                    update_decision(payload)
                    self.send_json(dashboard_payload())
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)})
                return
            self.send_error(404)
            return
        action = parsed.path[len(prefix) :]
        if action == "operator-analysis":
            self.send_json(
                {
                    "ok": True,
                    "exitCode": 0,
                    "stdout": deterministic_operator_analysis(),
                    "stderr": "",
                    "command": "python3 workspace/scripts/care_backlog_analyzer.py triage|schedule|audit + operator decisions",
                }
            )
            return
        spec = command_for(action)
        if spec is None:
            self.send_error(404, "Unknown action")
            return
        command, cwd, timeout, is_agent = spec
        result = run_command(command, cwd, timeout)
        if is_agent:
            if action == "agent-plan":
                result["agentText"] = agent_plan_text(result)
            else:
                result["agentText"] = extract_agent_text(result)
            if result["agentText"]:
                result["stdout"] = ""
            result["stderr"] = compact_agent_stderr(result["stderr"])
        self.send_json(result)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    port = int(os.environ.get("PORT", "5177"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Healthcare monitor app running at http://{host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
