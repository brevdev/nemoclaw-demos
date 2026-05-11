#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 workspace/scripts/care_backlog_analyzer.py triage >/tmp/healthcare-monitor-triage.json
python3 workspace/scripts/care_backlog_analyzer.py schedule >/tmp/healthcare-monitor-schedule.json
python3 workspace/scripts/care_backlog_analyzer.py audit >/tmp/healthcare-monitor-audit.json
python3 workspace/scripts/care_backlog_analyzer.py report >/tmp/healthcare-monitor-report.md
python3 workspace/scripts/care_backlog_analyzer.py watch-summary >/tmp/healthcare-monitor-watch.txt
python3 workspace/scripts/care_backlog_analyzer.py agent-topology >/tmp/healthcare-monitor-topology.json

python3 - <<'PY'
import json
from pathlib import Path

triage = json.loads(Path("/tmp/healthcare-monitor-triage.json").read_text())
schedule = json.loads(Path("/tmp/healthcare-monitor-schedule.json").read_text())
audit = json.loads(Path("/tmp/healthcare-monitor-audit.json").read_text())
topology = json.loads(Path("/tmp/healthcare-monitor-topology.json").read_text())
report = Path("/tmp/healthcare-monitor-report.md").read_text()
watch = Path("/tmp/healthcare-monitor-watch.txt").read_text()
cron = json.loads(Path("openclaw-cron/jobs.json").read_text())
config = json.loads(Path("openclaw.json").read_text())
dockerfile = Path("Dockerfile.sandbox").read_text()
installer = Path("docker/install-openclaw-assets.py").read_text()
server = Path("demo-app/server.py").read_text()
env_example = Path(".env.example").read_text()
setup_script = Path("scripts/brev-runtime-setup.sh").read_text()

assert len(triage) == 8, f"expected 8 referrals, got {len(triage)}"
assert triage[0]["priority"] == "critical", "top referral should be critical"
assert len(schedule) == len(triage), "schedule should cover every referral"
assert audit["summary"]["scheduled"] >= 6, "expected most referrals to schedule"
assert "48-Hour Care Backlog Action Plan" in report, "report title missing"
assert "CARE_BACKLOG_WATCH" in watch, "watch summary header missing"
assert "governance_note=" in watch, "watch summary governance note missing"
assert topology["default_agent"] == "main", "main must be default orchestration agent"
assert len(topology["specialists"]) == 5, "expected five specialist agents"
assert cron["version"] == 1, "cron version must be 1"
assert cron["jobs"][0]["agentId"] == "main", "cron should target main"
assert "watch-summary" in cron["jobs"][0]["payload"]["message"], "cron must run watch-summary"
assert config["gateway"]["mode"] == "local", "gateway.mode must be local for NemoClaw probe recovery"
assert "/opt/healthcare-monitor-demo" in dockerfile, "Dockerfile must use the project name as its image workdir"
assert 'Path("/opt/healthcare-monitor-demo")' in installer, "asset installer must read from the image workdir"
old_image_dir = "healthcare-monitor-" + "agentic" + "-claw"
assert old_image_dir not in dockerfile + installer, "old project directory name must not remain"
assert "OPENCLAW_GATEWAY_PORT" in server, "web app agent path must set the sandbox gateway port explicitly"
assert '"openclaw",\n        "agent"' in server, "web app must exercise the OpenClaw main agent"
assert "NEMOCLAW_ALLOW_PROVIDER_OVERRIDE=0" in env_example, "env template must default to release provider lock"
assert "NEMOCLAW_ALLOW_PROVIDER_OVERRIDE" in setup_script, "setup script must support explicit provider overrides"
assert "provider-managed endpoint" in setup_script, "setup script must avoid carrying build endpoint into managed overrides"
assert config["models"]["providers"]["inference"]["api"] == "openai-completions", "inference provider must use chat completions"
assert config["models"]["providers"]["inference"]["models"][0]["id"] == "__MODEL_ID__", "model id placeholder missing"
agents = {agent["id"]: agent for agent in config["agents"]["list"]}
assert "main" in agents, "main agent missing from config"
assert "sessions_spawn" in agents["main"]["tools"]["alsoAllow"], "main must be able to spawn specialists"
assert set(agents["main"].get("subagents", {})) <= {"allowAgents"}, "per-agent subagents config only supports allowAgents on this OpenClaw version"
assert config["agents"]["defaults"]["subagents"]["maxSpawnDepth"] == 1, "spawn depth limit must be defined at defaults level"
assert config["agents"]["defaults"]["subagents"]["maxConcurrent"] == 5, "concurrency limit must be defined at defaults level"
disabled_plugins = {
    key
    for key, value in config.get("plugins", {}).get("entries", {}).items()
    if value.get("enabled") is False
}
for plugin_id in [
    "acpx",
    "amazon-bedrock",
    "amazon-bedrock-mantle",
    "anthropic",
    "anthropic-vertex",
    "bonjour",
    "browser",
    "google",
    "openai",
    "qqbot",
    "web-readability",
]:
    assert plugin_id in disabled_plugins, f"{plugin_id} plugin must be disabled to avoid runtime npm staging"
for agent_id in ["intake", "clinical-triage", "capacity-planner", "payer-audit", "command-writer"]:
    assert agent_id in agents, f"{agent_id} missing from config"
    assert "sessions_spawn" in agents[agent_id]["tools"]["deny"], f"{agent_id} must not spawn"
    workspace = Path("workspaces") / agent_id
    assert (workspace / "AGENTS.md").exists(), f"{agent_id} AGENTS.md missing"
    assert (workspace / "TOOLS.md").exists(), f"{agent_id} TOOLS.md missing"

for skill in Path("skills").glob("*/SKILL.md"):
    text = skill.read_text()
    assert text.startswith("---\n"), f"{skill} must have YAML frontmatter"
    assert "\n---\n" in text[4:], f"{skill} frontmatter not closed"
PY

bash -n scripts/brev-runtime-setup.sh
bash -n scripts/live-demo-ready.sh
bash -n scripts/apply-demo-policy.sh
bash -n scripts/apply-healthcare-demo.sh
bash -n scripts/probe-build-endpoint.sh
bash -n scripts/start-demo-app.sh
bash -n scripts/open-openshell-tui.sh
bash -n scripts/package-demo.sh
bash -n scripts/patch-nemoclaw-build-provider.sh
bash -n scripts/run-agent-plan.sh

python3 -m py_compile \
  workspace/scripts/care_backlog_analyzer.py \
  docker/install-openclaw-assets.py \
  demo-app/server.py

echo "local verification passed"
