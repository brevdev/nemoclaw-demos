#!/usr/bin/env bash
# Configure an existing NemoClaw/OpenClaw sandbox for the Omni vision sub-agent demo.
#
# Usage:
#   export NVIDIA_API_KEY=nvapi-...
#   SANDBOX=hclaw bash scripts/apply-omni-subagent.sh
#
# Optional:
#   SEED_DEMO_IDENTITY=1  Move BOOTSTRAP.md aside and write minimal demo identity files.
set -euo pipefail

SANDBOX="${SANDBOX:-hclaw}"
DOCKER_CTR="${DOCKER_CTR:-openshell-cluster-nemoclaw}"
OMNI_MODEL="${OMNI_MODEL:-nvidia/nemotron-3-nano-omni-30b-a3b-reasoning}"
SUPER_MODEL="${SUPER_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
HERE=$(cd "$(dirname "$0")/.." && pwd)
BACKUP_DIR="${BACKUP_DIR:-$(mktemp -d "/tmp/${SANDBOX}-openclaw-omni.XXXXXX")}"

log() { printf '→ %s\n' "$*"; }
need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing required command: $1" >&2
        exit 1
    fi
}

need docker
need openshell
need python3

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    echo "NVIDIA_API_KEY is required. Export an nvapi key with Omni access before running." >&2
    exit 2
fi
if [[ "$NVIDIA_API_KEY" != nvapi-* ]]; then
    echo "NVIDIA_API_KEY does not look like an nvapi key." >&2
    exit 2
fi
chmod 700 "$BACKUP_DIR"

kexec() {
    docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- "$@"
}

log "sandbox: $SANDBOX"
log "backup dir: $BACKUP_DIR"
openshell sandbox get "$SANDBOX" >/dev/null

# 1. Patch policy so the OpenClaw gateway/node process can call NVIDIA directly.
log "backing up and patching policy"
openshell policy get "$SANDBOX" --full > "$BACKUP_DIR/policy-full-before.txt"
awk '/^---$/{seen=1; next} seen' "$BACKUP_DIR/policy-full-before.txt" > "$BACKUP_DIR/policy-before.yaml"
python3 - "$BACKUP_DIR/policy-before.yaml" "$BACKUP_DIR/policy-updated.yaml" <<'PY'
from pathlib import Path
import sys
src, dst = map(Path, sys.argv[1:3])
lines = src.read_text().splitlines()
start = next((i for i, line in enumerate(lines) if line == "  nvidia:"), None)
if start is None:
    raise SystemExit("could not find network_policies.nvidia block")
end = len(lines)
for i in range(start + 1, len(lines)):
    line = lines[i]
    if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
        end = i
        break
block = lines[start:end]
if any("/usr/local/bin/node" in line for line in block):
    dst.write_text("\n".join(lines) + "\n")
    raise SystemExit(0)
insert_at = None
for offset, line in enumerate(block):
    if line.strip() == "- path: /usr/local/bin/openclaw":
        insert_at = start + offset + 1
if insert_at is None:
    for offset, line in enumerate(block):
        if line.strip() == "binaries:":
            insert_at = start + offset + 1
            break
if insert_at is None:
    raise SystemExit("could not find nvidia.binaries list")
lines.insert(insert_at, "    - path: /usr/local/bin/node")
dst.write_text("\n".join(lines) + "\n")
PY
if ! cmp -s "$BACKUP_DIR/policy-before.yaml" "$BACKUP_DIR/policy-updated.yaml"; then
    openshell policy set --policy "$BACKUP_DIR/policy-updated.yaml" "$SANDBOX"
else
    log "policy already includes /usr/local/bin/node"
fi

# 2. Patch openclaw.json.
log "backing up and patching openclaw.json"
kexec cat /sandbox/.openclaw/openclaw.json > "$BACKUP_DIR/openclaw-before.json"
chmod 600 "$BACKUP_DIR/openclaw-before.json"
python3 - "$BACKUP_DIR/openclaw-before.json" "$BACKUP_DIR/openclaw-updated.json" "$OMNI_MODEL" "$SUPER_MODEL" <<'PY'
import json
import sys
src, dst, omni_model, super_model = sys.argv[1:5]
with open(src) as f:
    config = json.load(f)
models = config.setdefault("models", {})
models.setdefault("mode", "merge")
providers = models.setdefault("providers", {})
providers["nvidia-omni"] = {
    "baseUrl": "https://integrate.api.nvidia.com/v1",
    # Keep the real key out of openclaw.json; auth-profiles.json carries it.
    "apiKey": "unused",
    "api": "openai-completions",
    "models": [{
        "id": omni_model,
        "name": f"nvidia-omni/{omni_model}",
        "reasoning": True,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 131072,
        "maxTokens": 16384,
    }],
}
agents = config.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
defaults["model"] = {"primary": f"inference/{super_model}"}
defaults["timeoutSeconds"] = max(int(defaults.get("timeoutSeconds", 300) or 300), 300)
defaults["subagents"] = {"maxConcurrent": 4, "maxSpawnDepth": 1}
agents["list"] = [
    {
        "id": "main",
        "model": {"primary": f"inference/{super_model}"},
        "subagents": {"allowAgents": ["vision-operator"]},
        "tools": {"profile": "full"},
    },
    {
        "id": "vision-operator",
        "workspace": "/sandbox/.openclaw-data/workspace",
        "model": {"primary": f"nvidia-omni/{omni_model}"},
        "tools": {"profile": "full", "deny": ["message", "sessions_spawn"]},
    },
]
# Bonjour/mDNS is not needed for the demo and can fail inside restricted netns.
config.setdefault("plugins", {}).setdefault("entries", {}).setdefault("bonjour", {})["enabled"] = False
with open(dst, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PY
chmod 600 "$BACKUP_DIR/openclaw-updated.json"
kexec chmod 644 /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash
cat "$BACKUP_DIR/openclaw-updated.json" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw/openclaw.json >/dev/null
kexec /bin/bash -c 'cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash && chmod 444 openclaw.json .config-hash'

# 3. Write the per-agent auth profile in the OpenClaw 2026.4 auth-profile format.
log "writing vision-operator auth profile"
auth_profile=$(python3 - <<'PY'
import json
import os
key = os.environ["NVIDIA_API_KEY"]
print(json.dumps({
    "version": 1,
    "profiles": {
        "nvidia-omni:default": {
            "type": "api_key",
            "provider": "nvidia-omni",
            "key": key,
            "displayName": "NVIDIA Omni",
        }
    },
    "order": {"nvidia-omni": ["nvidia-omni:default"]},
}, indent=2))
PY
)
kexec bash -c 'mkdir -p /sandbox/.openclaw-data/agents/vision-operator/agent && chown -R sandbox:sandbox /sandbox/.openclaw-data/agents/vision-operator'
printf '%s\n' "$auth_profile" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json >/dev/null
kexec chmod 600 /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json
kexec chown sandbox:sandbox /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json

# 4. Copy demo instructions into the shared workspace.
log "copying TOOLS.md into workspace"
cat "$HERE/TOOLS.md" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw-data/workspace/TOOLS.md >/dev/null

# 5. Optional: seed identity so scripted smoke tests do not get intercepted by BOOTSTRAP.md.
if [[ "${SEED_DEMO_IDENTITY:-0}" == "1" ]]; then
    log "seeding demo identity and moving BOOTSTRAP.md aside"
    kexec bash -c 'cd /sandbox/.openclaw-data/workspace && tar cf /tmp/openclaw-demo-identity-before.tar BOOTSTRAP.md IDENTITY.md USER.md SOUL.md 2>/dev/null || true'
    kexec cat /tmp/openclaw-demo-identity-before.tar > "$BACKUP_DIR/openclaw-demo-identity-before.tar" 2>/dev/null || true
    kexec bash -c 'cd /sandbox/.openclaw-data/workspace && [ ! -f BOOTSTRAP.md ] || mv BOOTSTRAP.md BOOTSTRAP.md.disabled-for-omni-demo'
    cat <<'IDENTITY' | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw-data/workspace/IDENTITY.md >/dev/null
# IDENTITY.md - Who Am I?

- **Name:** Claw Demo
- **Creature:** Sandboxed OpenClaw assistant
- **Vibe:** Concise, practical, and demo-focused
- **Emoji:** 🦞

This identity was pre-seeded for the NemoClaw Omni vision sub-agent demo.
IDENTITY
    cat <<'USER' | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw-data/workspace/USER.md >/dev/null
# USER.md - Human Context

- **Name:** Demo operator
- **Preference:** Keep answers concise and focus on verifying the OpenClaw Omni sub-agent recipe.
USER
fi

# 6. Make the task registry path writable when the current OpenClaw build expects it.
log "ensuring writable task registry path"
kexec bash -c 'mkdir -p /sandbox/.openclaw-data/tasks && chown -R sandbox:sandbox /sandbox/.openclaw-data/tasks && rm -rf /sandbox/.openclaw/tasks && ln -s /sandbox/.openclaw-data/tasks /sandbox/.openclaw/tasks'

log "verifying patched config"
kexec /bin/bash -lc 'python3 - <<"PY"
import json
import os
cfg = json.load(open("/sandbox/.openclaw/openclaw.json"))
print("providers:", ", ".join(cfg["models"]["providers"].keys()))
print("agents:", ", ".join(agent["id"] for agent in cfg["agents"]["list"]))
print("vision model:", cfg["agents"]["list"][1]["model"]["primary"])
print("tools:", os.path.exists("/sandbox/.openclaw-data/workspace/TOOLS.md"))
print("auth:", os.path.exists("/sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json"))
PY'

cat > "$BACKUP_DIR/UNDO.txt" <<UNDO
To undo this demo patch for sandbox $SANDBOX:

  openshell policy set --policy "$BACKUP_DIR/policy-before.yaml" "$SANDBOX"
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- chmod 644 /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash
  docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw/openclaw.json < "$BACKUP_DIR/openclaw-before.json" > /dev/null
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- /bin/bash -c 'cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash && chmod 444 openclaw.json .config-hash'
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- rm -f /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json /sandbox/.openclaw-data/workspace/TOOLS.md

If you used SEED_DEMO_IDENTITY=1, restore identity files from:
  "$BACKUP_DIR/openclaw-demo-identity-before.tar"
UNDO

log "done"
echo "Backup and undo instructions: $BACKUP_DIR"
