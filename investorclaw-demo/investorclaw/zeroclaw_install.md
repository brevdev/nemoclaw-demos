# InvestorClaw — zeroclaw Installation & Configuration Guide

> **Platform**: zeropi (Raspberry Pi 4 2GB, aarch64)  
> **Runtime**: zeroclaw v0.6.9  
> **Status**: Validated 2026-04-14  
> **Critical**: InvestorClaw on zeroclaw uses the open-skills SKILL.md model — not SKILL.toml shell tools. The agent reads `zeroclaw/SKILL.md` as a knowledge document and executes commands via its built-in shell tool with an idempotent vendor dep install.

---

## Overview: zeroclaw vs. OpenClaw Differences

InvestorClaw was designed primarily for OpenClaw on clawpi. The zeroclaw runtime on zeropi behaves differently in several critical ways:

| Feature | OpenClaw (clawpi) | zeroclaw (zeropi) |
|---------|------------------|-------------------|
| Skill `prompts` injection | Full injection into system prompt | **NOT injected** — only metadata shown |
| Tool auto-execution | Plugin system handles routing | Requires `autonomy.level = "full"` |
| Security sandbox | None (trusted env) | Docker sandbox enabled by default — must disable |
| Open-skills loading | N/A (plugins, not skills) | 40 open-skills loaded by default → 96K token overflow |
| Command routing | `/portfolio` → plugin dispatch | open-skills SKILL.md → agent reads and executes via built-in shell |
| Skill format | SKILL.toml + `kind = "shell"` tools | SKILL.md knowledge document (open-skills pattern) |
| PYTHONPATH | Inherited from plugin install | Set per-command; vendor dir ships with repo |
| Dep management | requirements.txt global install | `pip install --target vendor/` idempotent per-command |
| Session persistence | `--session-id` (server-side) | `--session-state-file` (file-based JSON) |
| Separate repo? | N/A | No — use `zeroclaw/` subdirectory in InvestorClaw repo |

---

## Required zeroclaw Configuration Changes

Edit `~/.zeroclaw/config.toml` before running any InvestorClaw harness:

```toml
# Prevent 96K token context overflow from open-skills prompts
[skills]
open_skills_enabled = false       # ← REQUIRED (was: true)
prompt_injection_mode = "full"    # Leave as-is — prompts still won't inject (v0.6.9 limitation)

# Allow non-interactive skill/shell tool execution over SSH
[autonomy]
level = "full"                    # ← REQUIRED (was: "supervised")

# Disable Docker sandbox — NOTE: does NOT disable Docker for shell tool in v0.6.9
[security.sandbox]
backend = "none"                  # ← Set but insufficient; see Docker section below

# Set adequate context budget for InvestorClaw workflows
[agent]
max_context_tokens = 131000       # ← REQUIRED (was: 32000)
max_system_prompt_chars = 200000  # ← REQUIRED for SKILL.md injection (was: 0)

# Shell tool Docker image — use custom image with Python 3.13 + deps
[runtime]
kind = "native"                   # ← Set but Docker fallback still occurs in v0.6.9

[runtime.docker]
image = "investorclaw-runtime:latest"  # ← Build from zeroclaw/Dockerfile (was: alpine:3.20)
network = "bridge"                     # ← Allow outbound network for yfinance (was: none)
read_only_rootfs = false               # ← Allow file writes (was: true)
allowed_workspace_roots = ["/home/pi", "/tmp", "/opt/zeroclaw"]
```

Apply with:
```bash
sed -i 's/open_skills_enabled = true/open_skills_enabled = false/' ~/.zeroclaw/config.toml
sed -i 's/max_context_tokens = 32000/max_context_tokens = 131000/' ~/.zeroclaw/config.toml
sed -i 's/backend = "auto"/backend = "none"/' ~/.zeroclaw/config.toml
sed -i 's/level = "supervised"/level = "full"/' ~/.zeroclaw/config.toml
```

**Restart zeroclaw service after config changes:**
```bash
systemctl --user restart zeroclaw.service
```

---

## Why `prompts` Don't Work in zeroclaw

In zeroclaw v0.6.9, the `prompts` array in `SKILL.toml` is **not injected into the model's system prompt** regardless of `prompt_injection_mode = "full"`. The model only receives:
- Skill name and description (from `[skill]` metadata)
- List of callable tool names (from `[[tools]]` entries)

This means `/portfolio` command → tool routing must be provided in the **bootstrap prompt** sent by the harness, not in the skill definition.

### Consequence for Harness Design

The zeroclaw bootstrap prompt (sent as the first message to each session) MUST include:
```
When asked to run /portfolio commands, use the shell tool with PYTHONPATH=/home/pi/investorclaw
to run the corresponding Python script:
  /portfolio setup    → PYTHONPATH=/home/pi/investorclaw python3 /home/pi/investorclaw/commands/auto_setup.py
  /portfolio holdings → PYTHONPATH=/home/pi/investorclaw python3 /home/pi/investorclaw/commands/fetch_holdings.py
  (etc.)
```

---

## Skill Distribution: zeroclaw/ Directory (Not a Separate Repo)

zeroclaw uses the **open-skills SKILL.md model** — not the OpenClaw SKILL.toml plugin model. These are stored in the `zeroclaw/` subdirectory of the InvestorClaw repo so both runtimes share one repo.

| Path | Purpose |
|------|---------|
| `SKILL.toml` | OpenClaw plugin tool definitions (clawpi) |
| `zeroclaw/SKILL.md` | zeroclaw knowledge document (zeropi) |
| `zeroclaw_install.md` | This file |

### Installing the zeroclaw SKILL.md

The SKILL.md must be placed in the open-skills library directory where zeroclaw reads it as agent context:

```bash
# One-time install (idempotent)
mkdir -p ~/open-skills/skills/investorclaw
cp ~/investorclaw/zeroclaw/SKILL.md ~/open-skills/skills/investorclaw/SKILL.md
```

Verify:
```bash
cat ~/open-skills/skills/investorclaw/SKILL.md | head -5
```

The SKILL.md is self-contained and idempotent:
- Detects missing Python deps and installs to `~/investorclaw/vendor/` automatically
- Detects CSV portfolio file dynamically (does not hard-code filenames)
- Does not require global pip installs or pre-configured environment

### Why Not SKILL.toml on zeropi?

The SKILL.toml approach (`kind = "shell"`) is **not used** on zeroclaw because:
1. `prompts` array not injected into model context in v0.6.9 — agent never learns to call the tools
2. zeroclaw's SKILL.toml tools are intended for triggering discrete named tools, not flexible CLI workflows

The SKILL.md approach teaches the agent the exact commands to run, and it uses the built-in `shell` tool — which works correctly with `runtime.kind = "native"`.

### Dependency Bundling

Each command block in `SKILL.md` includes an idempotent dep-check that installs to a local vendor directory:

```bash
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_HOME}/vendor" \
    polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_HOME}/vendor"
```

This means:
- No global pip installs required
- Works on any system with Python 3.10+
- Idempotent: install only runs once; skipped on subsequent calls
- The `vendor/` directory can optionally be pre-populated and committed to the repo for air-gapped installs

---

## API Key Loading

The zeroclaw CLI does **not** automatically load API keys from the systemd service `.env` file. Use `set -a; source ~/.zeroclaw/.env; set +a` before invocations:

```bash
# CORRECT — exports all vars from .env to child processes
set -a; source ~/.zeroclaw/.env; set +a
zeroclaw agent -p xai --model grok-4-1-fast ...

# WRONG — source without set -a does NOT export to child processes
source ~/.zeroclaw/.env && zeroclaw agent ...  # ← keys NOT passed to zeroclaw
```

Or use a wrapper script (recommended for harness):
```bash
cat > /tmp/zc_run.sh << 'EOF'
#!/bin/bash
set -a
source ~/.zeroclaw/.env
set +a
zeroclaw agent -p groq --model openai/gpt-oss-120b \
  --session-state-file ~/.zeroclaw/sessions/ic-pi-bmz1.json \
  -m "$1"
EOF
```

---

## Portfolio Directory

`auto_setup.py` uses `SKILL_DIR / "portfolios"` which resolves to `~/investorclaw/portfolios/` (relative to the script's parent-of-parent). For zeroclaw, the workspace copy is used.

Place CSVs in BOTH locations:

```bash
# For direct SSH / host execution
mkdir -p ~/investorclaw/portfolios
cp ~/portfolios/UBS_Holdings_07_04_2026.csv ~/investorclaw/portfolios/

# For zeroclaw workspace (Docker container access)
mkdir -p ~/.zeroclaw/workspace/ic_code/portfolios
cp ~/portfolios/UBS_Holdings_07_04_2026.csv ~/.zeroclaw/workspace/ic_code/portfolios/
```

---

## Workspace Sync (Required After InvestorClaw Code Changes)

The zeroclaw shell tool cannot access `/home/pi/investorclaw/` directly — only the workspace is mounted in Docker. Sync after any code changes:

```bash
# Full sync (first time or major changes)
rm -rf ~/.zeroclaw/workspace/ic_code
cp -r ~/investorclaw ~/.zeroclaw/workspace/ic_code
cp ~/portfolios/*.csv ~/.zeroclaw/workspace/ic_code/portfolios/

# Quick sync (code changes only, preserve data)
rsync -av --exclude=data/ --exclude=portfolios/ \
  ~/investorclaw/ ~/.zeroclaw/workspace/ic_code/
```

Output files written by the agent are saved to `~/.zeroclaw/workspace/ic_code/data/` and persist on the host via the workspace mount.

---

## Session Management

```bash
# Clear session between runs (prevents context accumulation)
rm -f ~/.zeroclaw/sessions/ic-pi-bmz<N>.json

# Session state grows with each message — delete between clean runs
# Do NOT reuse sessions across different BMZ runs
```

---

## Context Overflow Root Cause

With `open_skills_enabled = true` (default), zeroclaw loads 40+ open-skills prompts into context, consuming ~96K tokens against a 32K budget → `Preemptive context trim: estimated=96324 budget=32000`. This causes:
- Agent response quality degradation
- Potential hallucination under memory pressure
- Trim of investorclaw skill context

Fix: `open_skills_enabled = false` + `max_context_tokens = 131000`.

---

## Autonomy & Tool Approval

With `autonomy.level = "supervised"` (default), zeroclaw prompts for Y/N before executing any skill tool. Over SSH with no interactive terminal, this always resolves as "Denied by user."

Fix: `autonomy.level = "full"` — all tool calls auto-approved. Appropriate for a trusted LAN Pi environment running harness tests.

---

## Critical Limitation: Docker Shell Sandbox (zeroclaw v0.6.9)

**zeroclaw CLI always executes shell tool commands inside a Docker container (`alpine:3.20`)**, regardless of `security.sandbox.backend`, `runtime.kind`, `allowed_workspace_roots`, or any other config combination. Confirmed via Python version probe:

- SSH to zeropi: `python3 --version` → Python **3.13.5** (host)
- zeroclaw shell tool: `python3 --version` → Python **3.11.2** (alpine:3.20)

| Requirement | Default `alpine:3.20` | With custom image |
|-------------|----------------------|-------------------|
| Python 3.13 + polars/yfinance | ❌ Wrong Python, no packages | ✅ If built into image |
| Network access (yfinance API) | ❌ `network = "none"` | ✅ If `network = "bridge"` |
| File write persistence | ❌ Container fs discarded | ⚠️ Workspace dir only (if mounted) |
| Host Python packages | ❌ Not visible | ❌ Still isolated |

### Option A: Custom Docker Image (Recommended Workaround)

Build a custom runtime image with Python 3.13 + InvestorClaw deps pre-installed:

```bash
# Build from zeroclaw/Dockerfile in InvestorClaw repo
docker build -t investorclaw-runtime:latest \
  -f ~/investorclaw/zeroclaw/Dockerfile ~/investorclaw
```

Update `~/.zeroclaw/config.toml`:
```toml
[runtime]
kind = "native"            # keep this — for when v0.6.10 fixes native transport

[runtime.docker]
image = "investorclaw-runtime:latest"    # ← changed from alpine:3.20
network = "bridge"                        # ← allow outbound (yfinance, APIs)
memory_limit_mb = 512
cpu_limit = 1.0
read_only_rootfs = false                  # ← allow file writes
mount_workspace = true
allowed_workspace_roots = ["/home/pi", "/tmp", "/opt/zeroclaw"]
```

Restart zeroclaw:
```bash
systemctl --user restart zeroclaw.service
```

**Limitation**: File writes still isolated to container unless workspace dir is used (`~/.zeroclaw/workspace/`). InvestorClaw output files must target this path or be read from stdout.

### Option B: Wait for `runtime.kind = "native"` Fix (v0.6.10+)

When zeroclaw fixes native transport, `runtime.kind = "native"` will bypass Docker entirely. No image change needed — host Python 3.13.5 with all packages will be used directly.

PR filed: `zeroclaw/ZEROCLAW_PR.md` in this repo documents the issue and proposed fixes.

### Additional Bug: `PYTHONPATH=val command` Syntax

The zeroclaw shell tool does NOT correctly handle the inline env var prefix syntax:
```bash
PYTHONPATH=/home/pi/investorclaw python3 script.py  # ← BROKEN in zeroclaw shell tool
```

The Python file is executed as bash (`import: command not found`). Use `export` form instead:
```bash
export PYTHONPATH=/home/pi/investorclaw
python3 script.py  # ← WORKS
```

The SKILL.md in `zeroclaw/SKILL.md` uses the export form throughout.

### Open Issue for zeroclaw v0.6.10+

Three bugs documented in `zeroclaw/ZEROCLAW_PR.md`:
1. `runtime.kind = "native"` + `security.sandbox.backend = "none"` don't disable Docker
2. `PYTHONPATH=val command` prefix syntax broken in shell tool
3. `prompt_injection_mode = "full"` doesn't inject skill prompts

**Proposed fixes**: `shell_tool.sandbox = false` option, fix native transport fallback, fix env var prefix parsing, fix prompt injection.

---

## Validated Configuration State (2026-04-14)

### Working Stack (Validated BMZ-4 Run)

- zeroclaw v0.6.9 ✅
- Model: **`openai/gpt-oss-120b` on Groq** ✅ (reliably calls tools)
  - `grok-4-1-fast-non-reasoning` — fabricates code blocks instead of calling tools ❌
  - `grok-4-1-fast-reasoning` — XML tool call format rejected by zeroclaw ❌
- Custom Docker image: `investorclaw-runtime:latest` ✅ (Python 3.12.4 + polars/pandas/yfinance)
- Docker network: `bridge` ✅ (yfinance API calls work)
- InvestorClaw workspace copy: `~/.zeroclaw/workspace/ic_code/` ✅
- holdings.json created in workspace at `02:07:33` ✅ (295KB, CDM 5.x format, real data)
- UBS_Holdings_07_04_2026.csv: `~/.zeroclaw/workspace/ic_code/portfolios/` ✅
- SKILL.md: `/home/pi/open-skills/skills/investorclaw/SKILL.md` ✅ (workspace paths)

### Host System (Not Used by Shell Tool)
- Host Python: 3.13.5 at /usr/bin/python3 (NOT used by zeroclaw shell tool)
- Host polars 1.39.3, yfinance 1.2.2 (NOT accessible in Docker container)
- SKILL.toml: installed in workspace (superseded by SKILL.md approach)

### Required Config (`~/.zeroclaw/config.toml`)
```toml
[skills]
open_skills_enabled = false
prompt_injection_mode = "full"

[autonomy]
level = "full"
shell_timeout_secs = 120

[security.sandbox]
backend = "none"

[agent]
max_context_tokens = 131000
max_system_prompt_chars = 200000

[runtime]
kind = "native"

[runtime.docker]
image = "investorclaw-runtime:latest"
network = "bridge"
read_only_rootfs = false
mount_workspace = true
allowed_workspace_roots = ["/home/pi", "/tmp", "/opt/zeroclaw"]

[shell_tool]
timeout_secs = 120
```
- .env: ~/investorclaw/.env ✅
- Config changes: autonomy=full, sandbox=none, open_skills=false, context=131K ✅
