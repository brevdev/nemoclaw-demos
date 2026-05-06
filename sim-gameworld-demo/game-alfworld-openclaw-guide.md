# Playing ALFWorld with an OpenClaw Agent via MCP (Visual THOR 3D)

This guide walks you through connecting the [ALFWorld](https://github.com/alfworld/alfworld) 3D household task simulation to an OpenClaw agent running inside an OpenShell sandbox. By the end, your agent will be able to start game episodes, choose actions, display first-person RGB frames, and track goal progress — all through natural language.

The connection uses **MCP (Model Context Protocol)**. A Python server runs on the host, exposes the AI2-THOR environment as tools over HTTP, and does no LLM reasoning of its own. The OpenClaw agent inside the sandbox calls MCP tools directly and uses its configured inference model for all action selection and reasoning. The sandbox talks to the host MCP server through an egress-approved network policy.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| NemoClaw | `nemoclaw` and `openshell` CLIs must be installed. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Inference API key | Required by `nemoclaw onboard` to configure the OpenClaw agent's inference provider. Set `INFERENCE_API_KEY` in `.env` before running `install.sh` (see below). |
| Python 3.10 | Required by `alfworld` / `ai2thor` — `install.sh` pins the venv to 3.10 automatically via `uv`. |
| `uv` | Installed automatically by `install.sh` if missing. |

---

## One-Command Setup

### 1. Configure `.env`

Copy the template and fill in your values:

```bash
cd nemoclaw-demos/sim-gameworld-demo
cp .env.template .env
```

Open `.env` and set your API key, inference configuration, and ALFWorld data path. The block below is **an example only** — replace the provider, base URL, and model with whichever combination suits your setup. See the full list of NemoClaw-compatible inference options at [https://docs.nvidia.com/nemoclaw/latest/inference/inference-options.html](https://docs.nvidia.com/nemoclaw/latest/inference/inference-options.html).

```bash
# Inference API credentials
INFERENCE_API_KEY=nvapi-your-key

# Inference provider configuration — example using NVIDIA Endpoints with Claude Opus 4.6.
# Replace these values with your chosen provider, base URL, and model.
INFERENCE_PROVIDER_TYPE=nvidia
INFERENCE_PROVIDER_NAME=nvidia
INFERENCE_BASE_URL=https://inference-api.nvidia.com/v1
INFERENCE_MODEL=aws/anthropic/bedrock-claude-opus-4-6

# ALFWorld data path — on Brev machines this is pre-downloaded:
ALFWORLD_DATA=/ephemeral/cache/alfworld
# On other machines leave this as-is; install.sh will download the data automatically.
```

`install.sh` loads `.env` automatically — values in `.env` do not override variables already exported in your shell, so you can also override any of them inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b-instruct bash install.sh
```

`INFERENCE_API_KEY` is also cached to `~/.nemoclaw/credentials.json` after the first run, so future re-runs pick it up without needing `.env` in place.

---

### 2. Run the installer

```bash
cd nemoclaw-demos/sim-gameworld-demo
bash install.sh
```

The script will:
1. Clean up any stale MCP server processes and tmux sessions
2. Install system OpenGL/X11 libraries required by AI2-THOR (`xvfb`, `libgl1`, etc.)
3. Load `.env` and resolve `INFERENCE_API_KEY`, provider, base URL, model, and `ALFWORLD_DATA`
4. Validate `ALFWORLD_DATA` — if the directory is missing or incomplete, download the dataset automatically via `alfworld-download`
5. Pre-configure the openshell inference provider and model
6. Run `nemoclaw onboard` if no sandbox exists — provider and model are already set, so you only need to confirm the sandbox name
7. Install all Python dependencies on the host in a Python 3.10 venv (`fastmcp`, `colorama`, `alfworld[vis]`)
8. Start Xvfb on `:1` if not already running (AI2-THOR requires a virtual display)
9. Start the MCP server in a persistent `tmux` session with `DISPLAY=:1` and `ALFWORLD_DATA` in scope
10. Apply the sandbox network policy (`policy/sandbox_policy.yaml`)
11. Upload the `alfworld-game-viz` skill into the sandbox
12. Bootstrap the skill's Python venv inside the sandbox (`fastmcp`, `colorama`)
13. Restart the OpenClaw gateway so it discovers the new skill
14. Verify the installation (MCP server reachable, skill present, venv imports OK)

You can also pass a sandbox name directly to skip the interactive prompt:

```bash
bash install.sh <sandbox-name>
```

> **First-run note:** on first run AI2-THOR downloads its Unity binary (~390 MB). The server may take 60–90 seconds to respond after the tmux session starts. The installer prints a progress indicator and warns you if the timeout is exceeded — the server is usually still starting in the background.

> **After a reboot:** Xvfb does not persist across reboots. Re-run `install.sh` to restart everything, or manually:
> ```bash
> Xvfb :1 -screen 0 1024x768x24 &
> bash install.sh <sandbox-name>
> ```

---

## Trying It Out

Connect to the sandbox and launch the OpenClaw TUI:

```bash
# From your host terminal
nemoclaw <sandbox-name> connect

# Inside the sandbox
openclaw tui
```

Once connected, verify the skill is loaded by asking the agent directly:

```
openclaw tui - ws://127.0.0.1:18789 - agent main - session main

 do you have a skill to play the alfworld game?

 Yes, I have the alfworld-game-viz skill available. It gives me direct access to the
 ALFWorld THOR 3D environment running on the host machine via MCP.

 I can:
 - Start a new game episode and receive the task description
 - Read the current game state (observation text + visual frame)
 - List the admissible actions at each step
 - Execute actions and track goal condition progress
 - Upload first-person RGB frames into this sandbox so you can see them
 - Query and search the game log

 What would you like to do? I can start a fresh game, continue from where we left off,
 or show you the current frame.

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/bedrock-claude-opus-4-6 | tokens 12k/131k (9%)
```

Try these prompts:

- "reset the game and let's play"
- "What task do I need to complete?"
- "What actions can I take right now?"
- "Take the next best action to progress toward the goal."
- "Play 3 more steps and report the goal condition score."
- "Show me the game history."

---

## Automating Game Play with a Cron Job and Heartbeat

Instead of driving the agent manually, ask OpenClaw to set up a cron job and a heartbeat for you in a single prompt inside the TUI.

### Step 1 — Set up the cron job and heartbeat together

```
openclaw tui - ws://127.0.0.1:18789 - agent main - session main

 please set up a cron job for me that progresses the game every 30 seconds by calling
 the alfworld-game-viz skill, remember to also set up a heartbeat for me to check in
 on the game status quo as well as summarize into a markdown table.

 All set! Here's what I've configured:

 1. Cron Job — Auto-Step every 30 seconds
    - Job ID: 07677bdd-24a8-4f4c-8d64-d0c76eb98e5b
    - Runs every 30s in an isolated session
    - Each run reads the current game state, picks the best action from admissible
      commands, executes it, and announces the result
    - First run fires in ~30s

 2. Heartbeat — Game Status Dashboard
    - Updated HEARTBEAT.md to check game state + game log on every heartbeat
    - Outputs a markdown table summarizing all recent steps: step number, action
      taken, observation, goal progress, and done status
    - Also shows the current task, available actions, and overall game status

 Current game state (step 0):
  - Task: Put some handtowel on sinkbasin
  - Location: Middle of a bathroom with bathtub, cabinets, sink, countertops,
    handtowelholder, shelves, toilet, etc.
  - Goal progress: 0% — game just started

 The cron job will start working toward the goal autonomously. The next heartbeat
 will give you the full progress table. Want me to adjust the interval or anything else?

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b | tokens 37k/131k (28%)
```

### Step 2 — Refine the cron job stop conditions

Ask the agent to add a step cap and auto-disable on task completion:

```
openclaw tui - ws://127.0.0.1:18789 - agent main - session main

 modify the cron job to stop/disable when the game goal/task is reached, therefore the
 game is completed. or max 30 steps as upper cap

 Done. Here's what changed:

 Updated cron job (07677bdd):
  - Switched to main session (systemEvent) — this fixes the delivery channel error
    the isolated runs were hitting
  - Stop conditions added:
      🎉 Game won — if done is true or goal_condition_success reaches 1.0
         → auto-disables the cron job
      ⏱️  Step cap — if step count reaches 30 → auto-disables the cron job
  - Still runs every 30 seconds, still picks the best action each turn

 The job will self-terminate when the task is completed or the 30-step limit is hit.
 No infinite loops.

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b | tokens 38k/131k (29%)
```

### Step 3 — Check game status via heartbeat

At any point ask the agent for a full status report:

```
openclaw tui - ws://127.0.0.1:18789 - agent main - session main

 now check the game status for me

 🎉 Game Complete! The task has been won in 14 steps.

 Task: Put some handtowel on sinkbasin

 | Step | Action                                  | Observation                                   | Goal | Done |
 |-----:|-----------------------------------------|-----------------------------------------------|:----:|:----:|
 |    0 | (initial)                               | Spawned in bathroom                           |  0%  |  ❌  |
 |    1 | go to handtowelholder 1                 | Found handtowel 1, tissuebox, spraybottle     |  0%  |  ❌  |
 |    2 | take handtowel 1 from handtowelholder 1 | Picked up handtowel 1                         |  0%  |  ❌  |
 |    3 | go to sinkbasin 1                       | Arrived at sinkbasin — cloth, soapbar, faucet |  0%  |  ❌  |
 |    4 | move handtowel 1 to sinkbasin 1         | Nothing happens (wrong verb)                  |  0%  |  ❌  |
 |    5 | clean handtowel 1 with sinkbasin 1      | Cleaned the handtowel                         |  0%  |  ❌  |
 |    6 | move handtowel 1 to sinkbasin 1         | Nothing happens                               |  0%  |  ❌  |
 |    7 | inventory                               | Carrying: handtowel 1                         |  0%  |  ❌  |
 |    8 | examine sinkbasin 1                     | Inspected sinkbasin contents                  |  0%  |  ❌  |
 |    9 | move handtowel 1 to sinkbasin 1         | Nothing happens                               |  0%  |  ❌  |
 |   10 | inventory                               | Carrying: handtowel 1                         |  0%  |  ❌  |
 |   11 | examine sinkbasin 1                     | Inspected sinkbasin contents                  |  0%  |  ❌  |
 |   12 | go to sink 1                            | Arrived at sink 1 — faucet, cloth, towel      |  0%  |  ❌  |
 |   13 | go to sinkbasin 1                       | Back at sinkbasin                             |  0%  |  ❌  |
 |   14 | put handtowel 1 in/on sinkbasin 1       | Handtowel placed on sinkbasin!                | 100% |  ✅  |

 Summary: The agent found the handtowel on step 1, picked it up on step 2, but then
 struggled with the correct "put" verb for several steps (trying "move" and "clean"
 instead). It finally used the correct put handtowel 1 in/on sinkbasin 1 command on
 step 14 to win.

 I've also disabled the cron job since the game is complete.
 Want me to reset the environment for a new game?

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b | tokens 39k/131k (30%)
```

### What each part does

| Feature | How it works |
|---------|-------------|
| **Cron job** | Fires every 30 seconds. Calls `get_current_state`, selects the best action from `admissible_commands` using the agent's own LLM, calls `step_env`, and uploads the resulting frame. Auto-disables when `done` is `true` or step count reaches 30. |
| **Heartbeat** | Triggered on demand or on a schedule. Reads `get_game_log` and `get_current_state`, renders a markdown table of all steps, and reports overall game status. |

---

## Available MCP Tools

The OpenClaw agent's LLM decides which tool to call and which action to take. The MCP server exposes raw environment operations — it does no LLM reasoning of its own.

| Tool | Arguments | What it does |
|------|-----------|-------------|
| `reset_env` | — | Start a new game episode; returns task, observation, admissible commands, and initial frame path |
| `step_env` | `action` | Execute one admissible action; returns new observation, goal condition score, done flag, and frame path |
| `get_admissible_commands` | — | List currently valid action strings and current step number |
| `get_current_state` | — | Full snapshot: task, observation, score, done, step, admissible commands, frame path, log file |
| `get_current_frame_info` | — | Metadata for the latest saved frame (path, dimensions, file size) |
| `upload_frame_to_sandbox` | `sandbox_name`, `step` | Push a frame PNG into the sandbox `assets/` folder via `openshell sandbox upload` |
| `get_game_log` | `last_n` | Return the last N step blocks from `game_log_visual.md` |
| `search_game_log` | `pattern` | Search the game log for a regex/text pattern |

---

## How the Skill Client Works

Inside the sandbox the agent invokes tools via:

```bash
SKILL_DIR=~/.openclaw/workspace/skills/alfworld-game-viz
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/sandbox_client_vis.py <tool> [args]
```

Each call executes exactly one MCP tool and prints the JSON result to stdout. The agent's LLM reads the result and decides the next tool to call — there is no game loop or action-selection logic inside the client script.

Example calls the agent makes:

```bash
SKILL_DIR=~/.openclaw/workspace/skills/alfworld-game-viz
CLIENT="$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/sandbox_client_vis.py"

# Start a new game
$CLIENT reset_env

# Get the current state after resuming
$CLIENT get_current_state

# Execute a chosen action
$CLIENT step_env --action "open fridge 1"

# Upload the resulting frame so it can be displayed in chat
$CLIENT upload_frame_to_sandbox --sandbox-name my-assistant

# Review recent game history
$CLIENT get_game_log --last-n 5
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `INFERENCE_API_KEY is not set` | Add `INFERENCE_API_KEY=your-key` to `.env`, or run `export INFERENCE_API_KEY=...` before `install.sh`. |
| `502 Bad Gateway` from sandbox | The MCP server isn't running. Check: `tmux ls` and `curl http://127.0.0.1:9001/mcp`. Restart with `bash install.sh <sandbox-name>`. |
| `ast.Str` error from server | The host venv is using Python 3.12+. Recreate with `rm -rf .venv && uv venv --python 3.10 && uv pip install "alfworld[vis]"`, then restart the tmux session. |
| `ALFWORLD_DATA not found` | Set `ALFWORLD_DATA` to a writable path in `.env` and re-run `install.sh` — it will download the data automatically. |
| Server slow / 90s wait on first run | AI2-THOR downloads its Unity binary (~390 MB) on first run. Check progress: `tmux attach -t alfworld-mcp`. |
| No Xvfb after reboot | Xvfb doesn't persist. Run `Xvfb :1 -screen 0 1024x768x24 &` then `bash install.sh <sandbox-name>`. |
| No frames in `assets/` | `upload_frame_to_sandbox` failed. Check that `openshell` is on PATH on the host and the sandbox name is correct. |
| `l7_decision=deny` in OpenShell logs | The sandbox policy wasn't applied or the connecting binary isn't listed. Re-run `openshell policy set` and check `policy/sandbox_policy.yaml`. |
| Agent doesn't know about ALFWorld | Confirm the skill is at `/sandbox/.openclaw/workspace/skills/alfworld-game-viz/SKILL.md` and reconnect. |
| `ModuleNotFoundError: No module named 'fastmcp'` | Run with the skill venv Python, not bare `python3`. See `/sandbox/.openclaw/workspace/skills/alfworld-game-viz/SKILL.md` Troubleshooting section. |
| `NVIDIA Endpoints endpoint validation failed` / `spawnSync curl ETIMEDOUT` during `nemoclaw onboard` | See below. |

### nemoclaw onboard: validation timeout

During `nemoclaw onboard`, step **[3/8] Configuring inference** makes a live inference call to validate the pre-configured model. Thinking/reasoning models can occasionally exceed the 30-second internal timeout, producing:

```
NVIDIA Endpoints endpoint validation failed.
Chat Completions API: curl failed (exit -110): spawnSync curl ETIMEDOUT
```

If this happens, type `retry` at the prompt. If the problem persists, set `INFERENCE_MODEL` in `.env` to a faster model such as `mistralai/mistral-small-3.1-24b-instruct-2503`.

### Restarting after a fresh reset

```bash
# Clean up everything on the host
tmux kill-session -t alfworld-mcp
pkill -f alfworld_env_mcp_server_visual || true
pkill -f "Xvfb :1" || true
rm -rf .venv

# Re-run
bash install.sh
```
