# zeroclaw v0.6.9: Four Blocking Issues for Real-World Python-Based Agentic Skills

**Reporter**: Jason Perlow  
**Affiliation**: Contributing in a personal capacity, independent of employer  
**zeroclaw version**: 0.6.9  
**Platform**: aarch64 (Raspberry Pi 4, 2GB), Raspberry Pi OS Bookworm  
**Skill under development**: [InvestorClaw](https://github.com/perlowja/InvestorClaw) — a FINOS CDM 5.x-compliant portfolio analysis skill  
**Severity**: High — four independent issues that collectively block any skill relying on custom Python scripts, outbound network calls, or skill-level prompt routing

---

## Background and Motivation

I am developing **InvestorClaw** as a personal open-source project in my free time. Its purpose is to serve as an **exemplar agentic skill** — a reference implementation demonstrating what a production-quality, real-world business use case looks like on an agent runtime.

### What InvestorClaw Does

InvestorClaw is a comprehensive portfolio analysis skill with the following capabilities:

- **Live holdings snapshot**: Fetches real-time prices via Yahoo Finance and builds a complete holdings view across equity, bond, and cash positions, serialized in [FINOS CDM 5.x](https://www.finos.org/common-domain-model)-compliant JSON — a financial industry data standard
- **Performance analysis**: Unrealized gain/loss, sector allocation, per-account breakdown, top positions by weight and performance delta
- **Bond analytics**: Duration, yield-to-maturity, coupon ladder, and maturity bucketing for fixed-income positions
- **Analyst consensus**: Aggregates Wall Street buy/hold/sell ratings for all held equity positions
- **Portfolio news**: Fetches recent headlines for every held position to surface material events in context
- **Full synthesis report**: Combines holdings, performance, analyst sentiment, and news into a single structured narrative report
- **Anti-fabrication guardrails**: HMAC-verified output chain ensures the agent cannot substitute hallucinated data for real market data — every value is traceable to a verified live API call
- **CSV import**: Accepts direct brokerage export files (tested against UBS Holdings format; format-agnostic by design)
- **Runs entirely on a Raspberry Pi 4**: The full stack — data fetch, analysis, synthesis — executes on a 2GB Pi 4 in under 90 seconds with no cloud dependency. This is a deliberate design choice and a core part of the story: a sophisticated, production-grade agentic skill should not require expensive hardware. A ~$50 Raspberry Pi 4 Model B (an N-2 generation device with 2GB RAM) can run the same workflow that would otherwise require a workstation or cloud VM. That accessibility is the point — if zeroclaw is going to fulfill its promise as an edge agent runtime, it needs to support skills like this one without requiring developers to fight the runtime to get there

### Deployment Context and Stakes

InvestorClaw is **nearing public announcement**. The following are currently underway:

- **FINOS evaluation**: The skill's CDM 5.x compliance is under review by FINOS as a candidate reference implementation for agentic financial data tooling
- **Brokerage firm evaluation**: Several brokerage firms are evaluating InvestorClaw as a portfolio analytics skill for customer-facing and advisor platforms
- **Internal employer distribution**: The skill is being prepared for broad distribution within my employer's internal Slack channels as a practical tool for employees participating in the company's Employee Stock Purchase Program (ESPP) — a deployment that would put it in front of tens of thousands of potential users

**InvestorClaw runs flawlessly on OpenClaw**, the companion agent runtime for which it was originally developed. Every command — `/portfolio setup`, `/portfolio holdings`, `/portfolio performance`, `/portfolio bonds`, `/portfolio analyst`, `/portfolio news`, `/portfolio synthesize` — executes correctly, produces verified output, and completes within acceptable latency. The issues documented in this report are **specific to zeroclaw** and represent a divergence from the OpenClaw behavior that the skill was designed against.

The intent here is not to criticize zeroclaw's design — the sandbox architecture is sound. The intent is to document, precisely and reproducibly, what needs to change for zeroclaw to support the class of Python-heavy, API-connected, file-producing agentic skills that InvestorClaw represents. As that class of skill becomes more common — and it will — these four issues will be encountered by every developer who attempts to build something beyond a shell utility.

I believe zeroclaw has strong architectural bones and real potential as a production-grade agent runtime, particularly for edge and IoT deployment. I would genuinely like to see these fixed, and depending on community interest, may be in a position to facilitate broader engineering attention to zeroclaw. But that conversation starts here, with concrete reproduction cases.

---

## Executive Summary

Four issues in zeroclaw v0.6.9 make it **impossible to run any skill that uses custom Python scripts with third-party packages, outbound network calls, or skill-level command routing** — without significant undocumented workarounds that gut the security sandbox:

| # | Issue | Documented Behavior | Actual Behavior |
|---|-------|--------------------|-----------------| 
| 1 | `runtime.kind = "native"` | Bypasses Docker; runs on host | Docker always used — no bypass |
| 2 | `PYTHONPATH=val command` syntax | Standard shell env prefix works | Script executed as bash; import errors |
| 3 | `prompt_injection_mode = "full"` | Skill prompts injected into model | Only tool names visible; prompts silently dropped |
| 4 | Shell sandbox defaults | Secure-by-default sandbox | Defaults break all realistic Python skill patterns |

None of these are edge cases. Every one surfaces immediately the moment you try to build a skill that does something beyond calling `ls` or `echo`.

---

## Issue 1: `runtime.kind = "native"` Does Not Bypass Docker for Shell Tool Execution

### Expected behavior

When `[runtime] kind = "native"` is set in `~/.zeroclaw/config.toml`, the shell tool should execute commands directly as a host subprocess — not inside a Docker container. This is the only reasonable interpretation of the setting name.

### Actual behavior

The shell tool **always** executes inside a Docker container, regardless of `runtime.kind`, `security.sandbox.backend`, or any other config combination.

### Reproduction

**Config**:
```toml
[security.sandbox]
backend = "none"

[runtime]
kind = "native"
```

**Test**:
```bash
# Host Python (SSH to Pi directly):
python3 --version
# → Python 3.13.5

# zeroclaw shell tool (agent prompt: "run: python3 --version"):
# → Python 3.11.2
```

Python 3.11.2 is not present on the host. It is the Python version inside `alpine:3.20`. This confirms Docker is being used despite `runtime.kind = "native"`.

**File persistence test**:
```bash
# Agent prompt: "run: touch /home/pi/proof.txt && ls /home/pi/proof.txt"
# Agent output: /home/pi/proof.txt  ← appears to succeed

# Host check after session:
ls /home/pi/proof.txt
# → ls: cannot access '/home/pi/proof.txt': No such file or directory
```

The file exists inside the container's ephemeral filesystem. It is discarded on container exit.

### Impact

This is the root issue behind everything else. If native execution worked, issues 2 and 4 would not exist for host-based skills. Every workaround documented here exists solely because this setting does not function.

### Proposed fix

When `runtime.kind = "native"`, spawn the shell tool command as a direct subprocess on the host. Reserve Docker for `runtime.kind = "docker"` (explicit) or when `native` is not set.

As a complementary option, add a per-tool override:

```toml
[shell_tool]
sandbox = false     # bypass Docker for shell tool only, regardless of global runtime.kind
timeout_secs = 60
```

---

## Issue 2: `PYTHONPATH=val command` Inline Environment Variable Prefix Syntax Is Broken

### Expected behavior

Standard POSIX shell syntax for prefixing a command with an environment variable assignment should work:

```bash
PYTHONPATH=/home/pi/investorclaw python3 /home/pi/investorclaw/commands/fetch_holdings.py
```

This is idiomatic, widely used, and the natural output of any LLM given a Python execution task.

### Actual behavior

The zeroclaw shell tool either misidentifies the command (treating `PYTHONPATH=...` as the command name and failing the `allowed_commands` check), or strips the prefix incorrectly and executes the Python script path as a bash script.

**Observed error**:
```
Running command: PYTHONPATH=/home/pi/investorclaw python3 /home/pi/investorclaw/commands/fetch_holdings.py

/home/pi/investorclaw/commands/fetch_holdings.py: line 2: import: command not found
/home/pi/investorclaw/commands/fetch_holdings.py: line 3: import: command not found
syntax error: unexpected end of file
```

The file has a valid `#!/usr/bin/env python3` shebang and is syntactically correct Python. It is being executed as bash.

### Impact

Any LLM, given a Python execution task, will naturally produce this syntax. It cannot be relied upon to consistently use the `export` workaround, especially in multi-turn sessions where earlier tool call patterns influence later ones. Skills designed for OpenClaw that use this syntax will silently fail on zeroclaw.

### Workaround

Use explicit `export` form in SKILL.md command blocks:
```bash
export PYTHONPATH=/home/pi/investorclaw
python3 /home/pi/investorclaw/commands/script.py
```

This is fragile as a long-term solution — it depends on the model following an undocumented convention that contradicts standard shell idiom.

### Proposed fix

In the shell tool's command parsing and `allowed_commands` check logic:

1. Recognize `KEY=VAL` tokens at the start of a command line as environment variable assignments (not commands)
2. Extract the actual executable (first non-assignment token)
3. Apply `allowed_commands` check against the actual executable
4. Pass the `KEY=VAL` pairs as environment variables to the subprocess

This is how every POSIX shell handles this syntax. It is not exotic behavior.

---

## Issue 3: `prompt_injection_mode = "full"` Does Not Inject Skill Prompts Into Model Context

### Expected behavior

The `prompts` array in `SKILL.toml` is the primary mechanism for teaching the agent how to use a skill's tools — specifically, which tool to call for which user intent. With `prompt_injection_mode = "full"` set, these prompts should be injected into the model's system prompt, as the name clearly implies.

### Actual behavior

The `prompts` array is **never injected**. The model receives only:
- Skill name and description (from `[skill]` metadata)
- A list of callable tool names (from `[[tools]]` entries)

Tool descriptions, routing instructions, and any guidance in `prompts` are silently dropped.

### Reproduction

**SKILL.toml** (simplified):
```toml
[skill]
name = "probe"
description = "Test skill"
prompts = ["If asked about XYZZY_PROBE_STRING, respond YES_FOUND"]
```

**Agent prompt**: "Is XYZZY_PROBE_STRING in your system prompt?"  
**Agent response**: "No, XYZZY_PROBE_STRING is not in my system prompt."

The injection did not occur. The config option has no observable effect.

### Impact

This silently breaks the entire skill routing model. A skill that defines tools for `/portfolio setup`, `/portfolio holdings`, etc. expects the agent to learn from the prompts which tool to call for each command. Without that injection, the agent has no basis for making the right tool choice. It will either fabricate a response or call the wrong tool — and there is no error or warning that the prompts were not injected.

This issue is especially dangerous because it **fails silently**. A skill developer following the documented pattern will get unreliable agent behavior with no indication that the configuration is being ignored.

### Workaround

Include command routing instructions in the harness bootstrap message (first message sent before any skill command):

```
For /portfolio commands, use the shell tool to run the following Python scripts:
  /portfolio setup    → python3 /path/to/auto_setup.py
  /portfolio holdings → python3 /path/to/fetch_holdings.py <csv_path>
  ...
```

This is a significant developer burden and an unreliable substitute for proper prompt injection.

### Proposed fix

Honor `prompt_injection_mode = "full"` by injecting the full `prompts` array content into the model's system prompt. At minimum, document clearly and prominently which fields are actually injected, and which are silently ignored.

---

## Issue 4: Default Shell Sandbox Configuration Breaks All Realistic Python Skill Patterns

This is not a single bug — it is a configuration default problem that, combined with Issue 1, creates a situation where the sandbox cannot be meaningfully reconfigured to support common skill patterns.

### Default sandbox settings and their impact

| Default Setting | Value | Blocks |
|----------------|-------|--------|
| `runtime.docker.image` | `alpine:3.20` | All Python packages (polars, pandas, etc.) |
| `runtime.docker.network` | `none` | All outbound API calls (yfinance, REST APIs, etc.) |
| `runtime.docker.read_only_rootfs` | `true` | Any file write (output files, caches, state) |
| Host filesystem access | None | All scripts not in workspace dir |

These defaults are appropriate for a generic sandbox. The problem is that **there is no documented, functional path to relax them for legitimate use cases**. `runtime.kind = "native"` is documented but non-functional (Issue 1). `security.sandbox.backend = "none"` sounds like it disables the sandbox but also does not affect shell tool Docker execution.

### Real-world impact

The following skill types are **completely blocked** by the default sandbox with no working escape hatch:

| Skill type | Status | Reason |
|-----------|--------|--------|
| Python scripts with pip packages | ❌ Blocked | `network = "none"` prevents pip; packages not in Alpine |
| Any outbound HTTP/API call | ❌ Blocked | `network = "none"` |
| Persistent file output | ❌ Blocked | `read_only_rootfs = true`; container discarded on exit |
| Host Python environment | ❌ Blocked | Container is isolated; host site-packages invisible |
| Scripts referencing host paths | ❌ Blocked | Host filesystem not mounted |
| GPU/hardware access | ❌ Blocked | Hardware not mapped into container |

For context, InvestorClaw requires all of the above. So does any ML inference skill, any database client skill, any skill that writes output files, any skill that calls a local service.

### Workaround (what we had to do)

To get InvestorClaw working, we:
1. Built a custom Docker image with Python 3.13 + all dependencies pre-installed (1.01 GB image on aarch64)
2. Set `network = "bridge"` (re-enables outbound network)
3. Set `read_only_rootfs = false` (re-enables file writes)
4. Copied the entire InvestorClaw codebase into `~/.zeroclaw/workspace/` (only path accessible in container)
5. Updated the skill to use workspace paths exclusively
6. Set `mount_workspace = true` and extended `allowed_workspace_roots`

This works. But it requires significant infrastructure setup that the documentation does not describe, and which most skill developers will not discover without extensive debugging.

### Proposed fixes

1. **Fix `runtime.kind = "native"`** (see Issue 1) — this is the highest-leverage fix; it eliminates the need for issues 2–4 workarounds entirely for trusted environments
2. **Document the custom image path clearly** — if Docker is always used, the path to building a custom runtime image should be a first-class documented workflow, not something a developer has to reverse-engineer
3. **Provide a starter `Dockerfile`** for Python-based skills in the zeroclaw documentation or repo
4. **Surface sandbox configuration errors** — if a skill's SKILL.toml declares tools that require network or file write access, and the sandbox config blocks them, zeroclaw should warn at load time rather than fail silently at runtime

---

## Broader Context: Why This Matters as zeroclaw Adoption Grows

The current open-skills ecosystem is dominated by **documentation-style SKILL.md files** — knowledge skills that teach the agent code patterns and rely on it to execute via the shell tool. These are relatively forgiving of the sandbox issues because they often run simple shell commands available in Alpine.

But the trajectory of agent skills is unmistakably toward **more ambitious, Python-heavy orchestration**:

- Financial analysis and portfolio management (this skill)
- ML inference pipelines
- Custom database clients connecting to local services
- IoT and hardware control (zeroclaw explicitly supports peripherals — but shell tool access to hardware is blocked)
- ETL and data processing pipelines
- Local LLM orchestration

Every one of these patterns **fails out of the box** on zeroclaw v0.6.9 with no clear resolution path. As the community develops more ambitious skills — particularly as skills migrate from OpenClaw to zeroclaw — these four issues will be encountered repeatedly. Each developer will spend hours debugging what should be a known, documented limitation or a non-issue if `runtime.kind = "native"` worked.

The gap between zeroclaw's documented configuration surface and its actual runtime behavior is the core problem. The sandbox design is reasonable. The four bugs documented here are what need to change.

---

## Reproduction Environment

```
zeroclaw version: 0.6.9
OS: Raspberry Pi OS Bookworm (aarch64, Debian 12 base)
Hardware: Raspberry Pi 4, 2GB RAM
Python (host): 3.13.5 at /usr/bin/python3
Python (shell tool, default): 3.11.2 (alpine:3.20)
Docker: active, daemon running
Skill: InvestorClaw v1.0.0 (FINOS CDM 5.x portfolio analysis)
```

**Config at time of testing** (fully reproduced with all four bugs):
```toml
[security.sandbox]
backend = "none"

[runtime]
kind = "native"

[runtime.docker]
image = "alpine:3.20"
network = "none"
memory_limit_mb = 512
cpu_limit = 1.0
read_only_rootfs = true
mount_workspace = true
allowed_workspace_roots = ["/home/pi", "/tmp", "/opt/zeroclaw"]

[autonomy]
level = "full"
```

---

## Working Configuration (After Workarounds)

For reference, the configuration that makes InvestorClaw functional on zeroclaw v0.6.9 — at the cost of gutting the sandbox security guarantees:

```toml
[skills]
open_skills_enabled = false
prompt_injection_mode = "full"   # still broken, but set for when fixed

[autonomy]
level = "full"

[security.sandbox]
backend = "none"                 # still uses Docker for shell tool; included for future fix

[agent]
max_context_tokens = 131000
max_system_prompt_chars = 200000

[runtime]
kind = "native"                  # still uses Docker; included for when fixed

[runtime.docker]
image = "investorclaw-runtime:latest"   # custom image: python:3.13-slim + all deps
network = "bridge"                       # allows outbound (yfinance API)
read_only_rootfs = false                 # allows file writes
mount_workspace = true
allowed_workspace_roots = ["/home/pi", "/tmp", "/opt/zeroclaw"]

[shell_tool]
timeout_secs = 120
```

Custom Dockerfile available at: `zeroclaw/Dockerfile` in the InvestorClaw repository.

---

## References

- InvestorClaw repository: `https://github.com/perlowja/InvestorClaw`
- `zeroclaw/SKILL.md` — open-skills knowledge document (workaround for Issue 3)
- `zeroclaw/Dockerfile` — custom runtime image (workaround for Issue 4)
- `zeroclaw_install.md` — full installation and configuration guide documenting all workarounds
- Related config keys: `runtime.kind`, `security.sandbox.backend`, `shell_tool.sandbox` (proposed), `skills.prompt_injection_mode`, `runtime.docker.image`
