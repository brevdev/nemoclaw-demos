# Running Hermes Agent Inside a NemoClaw Sandbox

This guide walks you through installing [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research inside a NemoClaw OpenShell sandbox. By the end, you will have a fully functional Hermes instance running inside the sandbox, connected to your configured inference provider through the sandbox's internal `inference.local` route — with no external API keys exposed to the agent at runtime.

Hermes is a self-improving AI agent with a built-in learning loop: it creates and refines skills from experience, searches its own past conversations, and builds a persistent model of the user across sessions. It also supports delegation to subagents, built-in cron scheduling, and messaging platform gateways (Telegram, Discord, Slack, WhatsApp, Signal).

> **What is `inference.local`?**
> Inside a NemoClaw sandbox, `inference.local` is the internal hostname that routes LLM API calls through the OpenShell proxy to your configured inference provider (NVIDIA NIM, Bedrock, OpenRouter, etc.). Hermes is configured to treat it as an OpenAI-compatible endpoint — the API key value is intentionally set to `unused` because the proxy handles auth transparently.
>
> **Limitation:** This demo installs the Python-only subset of Hermes (`.[all]` extras). The Node/Playwright layer (used for browser automation) is excluded from this install to keep the setup self-contained. Browser tool calls will not be available; all other tools work normally.

---

## Prerequisites

| Requirement | Details |
|---|---|
| NemoClaw | `nemoclaw` and `openshell` CLIs must be installed. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Python 3 | Required on the host to parse credentials and configuration during `install.sh`. |
| `git` | Required on the host to clone `hermes-agent` before uploading it to the sandbox. |
| Inference API key | Required by `nemoclaw onboard` to configure the sandbox's inference provider. Set `INFERENCE_API_KEY` in `.env` before running `install.sh`. |
| `uv` | The installer downloads `uv` on the host and uploads it into the sandbox automatically — no manual installation needed. |

---

## One-Command Setup

### 1. Configure `.env`

Copy the template and fill in your values:

```bash
cd nemoclaw-demos/hermes-addition-demo
cp .env.template .env
```

Open `.env` and set your API key and inference configuration:

```bash
# Required: your NVIDIA Inference API key (or whichever provider you use)
INFERENCE_API_KEY=nvapi-your-key

# Optional: inference provider settings (defaults shown)
INFERENCE_PROVIDER_TYPE=nvidia
INFERENCE_PROVIDER_NAME=nvidia
INFERENCE_BASE_URL=https://inference-api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-opus-4-6
```

> **Choosing a provider or model:** see the NemoClaw docs for the full list of supported providers, base URLs, and models:
> [https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model](https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model)

`INFERENCE_API_KEY` is cached to `~/.nemoclaw/credentials.json` after the first run, so future re-runs pick it up without needing `.env` in place. You can also override any value inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b bash install.sh
```

---

### 2. Run the installer

```bash
cd nemoclaw-demos/hermes-addition-demo
bash install.sh
```

The script will:
1. Clean up any stale `hermes-agent` processes
2. Check prerequisites (`openshell`, `nemoclaw`, `python3`, `git`)
3. Load `.env` and resolve `INFERENCE_API_KEY`, provider, base URL, and model
4. Run `nemoclaw onboard` if no sandbox exists — confirm the sandbox name when prompted
5. Create the inference provider and set the model **after** the gateway is live
6. Apply the sandbox network policy (`policy/sandbox_policy.yaml`) — this opens access to PyPI, GitHub, npm, and `inference.local` before any installs begin
7. Clone `hermes-agent` from GitHub on the host and upload it to `/sandbox/hermes-agent`
8. Download the `uv` binary on the host and upload it to `/sandbox/.local/bin/uv` — this bypasses the proxy restriction on `astral.sh` during install
9. Create a Python 3.11 venv inside the sandbox and run `uv pip install -e '.[all]'`
10. Create the `~/.hermes` config directory tree inside the sandbox
11. Configure Hermes to use `inference.local` with your chosen model — no external key needed at runtime
12. Sync bundled Hermes skills into `~/.hermes/skills/`
13. Link the `hermes` binary to `/sandbox/.local/bin/hermes`
14. Restart the OpenClaw gateway so the sandbox environment is refreshed
15. Verify that `hermes` is on `PATH` inside the sandbox

You can also pass a sandbox name directly to skip the interactive prompt:

```bash
bash install.sh <sandbox-name>
```

> **Note:** The installer is largely automated, but two interactive prompts require user input: accepting the NemoClaw terms during `nemoclaw onboard` and confirming the sandbox name (if multiple sandboxes exist). All other steps run without intervention.

---

## Trying It Out

Connect to the sandbox and start Hermes:

```bash
# From your host terminal
openshell sandbox connect <sandbox-name>

# Inside the sandbox
export PATH="$HOME/.local/bin:$PATH"
hermes
```

Once Hermes starts, you will see its TUI. Try these prompts:

---

**"What can you do?"**

```
I'm Hermes, a self-improving AI agent. Here's what I can do:

- Run terminal commands and write/edit files on this system
- Search the web and extract content from pages
- Remember things across conversations (agent-curated memory)
- Learn new skills and improve them during use
- Delegate complex tasks to isolated subagents
- Run scheduled automations (cron jobs in natural language)
- Search my own past conversations by topic or keyword

What would you like to work on?
```

---

**"What model are you using?"**

```
I'm currently running on aws/anthropic/bedrock-claude-opus-4-6, routed
through inference.local — the NemoClaw sandbox's internal inference proxy.
```

---

**"List the skills you have available."**

```
/skills

Available skills (synced from hermes-agent/skills/):
  • web-research    — structured web research with source citations
  • code-review     — review a file or diff for bugs and style
  • summarize       — summarize a document or paste
  ...

Use /<skill-name> to invoke one, or ask me to use one directly.
```

---

## Key Hermes Commands

| Command | What it does |
|---|---|
| `hermes` | Start the interactive TUI |
| `hermes model` | Switch LLM provider or model |
| `hermes tools` | Enable or disable individual tools |
| `hermes config set` | Set individual configuration values |
| `hermes gateway` | Start the messaging gateway (Telegram, Discord, etc.) |
| `hermes setup` | Run the full interactive setup wizard |
| `hermes doctor` | Diagnose installation issues |
| `hermes update` | Update to the latest version |
| `hermes claw migrate` | Migrate settings from OpenClaw |

Inside a conversation, useful slash commands include:

| Slash command | What it does |
|---|---|
| `/new` or `/reset` | Start a fresh conversation |
| `/model [provider:model]` | Switch model mid-conversation |
| `/skills` | Browse and install skills |
| `/compress` | Compress the context window |
| `/usage` | Show token usage for the current session |
| `/retry` | Retry the last turn |
| `/stop` | Interrupt current work |

---

## How Inference Routing Works

Hermes is configured during install to use `https://inference.local/v1` as its base URL, with the model set to whatever `INFERENCE_MODEL` was in your `.env`. The sandbox policy opens port 443 to `inference.local` only for the Hermes Python process.

```
┌─────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                               │
│                                                             │
│   NVIDIA / Bedrock / OpenRouter inference endpoint          │
│   (selected by INFERENCE_MODEL in .env)                     │
└──────────────────────────────┬──────────────────────────────┘
                               │  TLS to inference provider
                               │  proxied via NemoClaw gateway
┌──────────────────────────────┴──────────────────────────────┐
│  SANDBOX (NemoClaw / OpenShell)                             │
│                                                             │
│   hermes-agent/venv/bin/python3                             │
│   └── calls https://inference.local/v1/chat/completions    │
│       OPENAI_API_KEY=unused  (proxy handles auth)           │
│       model=aws/anthropic/bedrock-claude-opus-4-6           │
└─────────────────────────────────────────────────────────────┘
```

The `inference.local` binding is listed in `policy/sandbox_policy.yaml` under the `hermes_inference` policy block, restricted to the Hermes Python binary paths:

```yaml
hermes_inference:
  name: hermes_inference
  endpoints:
    - { host: inference.local, port: 443 }
  binaries:
    - { path: "/sandbox/hermes-agent/venv/bin/python3" }
    - { path: "/sandbox/hermes-agent/venv/bin/python" }
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `INFERENCE_API_KEY is not set` | Add `INFERENCE_API_KEY=your-key` to `.env`, or run `export INFERENCE_API_KEY=...` before `install.sh` |
| `hermes: command not found` inside sandbox | Run `export PATH="$HOME/.local/bin:$PATH"` — or disconnect and reconnect so `.bashrc` is sourced |
| `uv venv failed` | Check that the sandbox is live: `openshell sandbox list`. Re-run `install.sh` if the sandbox restarted |
| `uv pip install failed` | The `pypi` policy block in `sandbox_policy.yaml` must be applied before the install. Re-run `install.sh` — the policy is applied at Step 5, before any `pip` calls |
| `Connection refused` to `inference.local` | The `hermes_inference` policy block may not be applied. Re-run `openshell policy set <sandbox-name> --policy policy/sandbox_policy.yaml --wait` |
| Wrong model shown inside Hermes | Run `hermes model` inside the sandbox, or edit `~/.hermes/config.yaml` and restart Hermes |
| `NVIDIA Endpoints endpoint validation failed` during `nemoclaw onboard` | Type `retry` at the prompt — the API call usually succeeds on a second attempt. If persistent, set a faster `INFERENCE_MODEL` in `.env` |
| Agent doesn't persist memory across sessions | Hermes memory lives at `~/.hermes/memories/`. Make sure `/sandbox` is read-write in the policy (it is by default) |

### Full environment reset

```bash
# Delete sandbox and re-run
openshell sandbox delete <sandbox-name>
bash install.sh
```

---

## File Structure

```
hermes-addition-demo/
├── install.sh                          # One-command installer
├── .env.template                       # Configuration template
├── hermes-addition-openclaw-guide.md   # This guide
├── policy/
│   └── sandbox_policy.yaml            # Network policy — PyPI, GitHub, npm, inference.local
└── hermes-agent/                       # Cloned by install.sh from NousResearch/hermes-agent
    ├── agent/                          # Core agent internals
    ├── tools/                          # Tool implementations
    ├── gateway/                        # Messaging platform gateway
    ├── skills/                         # Bundled skills (synced to ~/.hermes/skills/)
    └── ...
```

---

Created by **zcharpy**
