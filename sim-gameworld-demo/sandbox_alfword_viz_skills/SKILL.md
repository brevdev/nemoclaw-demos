---
name: alfworld-game-viz
description: Interact with the ALFWorld THOR 3D visual environment via MCP. Provides direct tool access to reset the game, execute actions, inspect game state, view visual frames, upload frames to the sandbox, and query the game log. You (the agent) decide which tool to call and which action to take — no secondary LLM is involved. Trigger keywords — alfworld, game, thor, household task, game step, game frame, game viz, game visualization, embodied agent, reset game, take action.
---

# ALFWorld Visual Game Skills

## Overview

Direct tool interface to the ALFWorld THOR 3D visual environment running on the **host machine** via MCP. You decide which tool to invoke and which action to take based on the current game state, the visual frame, and the list of admissible actions. The MCP server exposes raw environment operations — call them with the specific parameters that match the intended action.

## IMPORTANT — The environment runs on the host, not in the sandbox

The ALFWorld THOR environment and all frame files are managed by the MCP server on the **host machine**. Frames are pushed into the sandbox `assets/` folder via `upload_frame_to_sandbox`.

- **Never** search the sandbox filesystem for the environment or config files.
- **Always** call tools without extra path arguments — the server uses its configured defaults.
- The server must be running before any tool call will succeed. If you get connection errors, the host server may still be warming up (can take 60+ seconds); retry with delays.

## Invocation

Always use the skill venv's Python (required by the sandbox network policy):

```bash
SKILL_DIR=~/.openclaw/workspace/skills/alfworld-game-viz
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/sandbox_client_vis.py <tool> [args]
```

Do **not** use bare `python3` — the system Python is not permitted to reach the MCP server on port 9001.

## Available Tools

### `reset_env`
Reset the ALFWorld THOR environment and start a fresh game episode. Clears old frames and initialises the game log.
**Use when:** user wants to start a new game, restart, or the previous episode has ended.
```bash
python3 sandbox_client_vis.py reset_env
```
Returns JSON with `task`, `observation`, `admissible_commands`, `frame_path`, `step`.

---

### `step_env`
Execute one action in the THOR environment. Saves the resulting frame and appends an entry to the game log.
**Use when:** you have chosen an action from the admissible list and want to advance the game.
```bash
python3 sandbox_client_vis.py step_env --action ACTION
```
| Argument | Type | Required | Description |
|---|---|---|---|
| `--action` | str | yes | Exact action string from the admissible commands list |

**Example:**
```bash
python3 sandbox_client_vis.py step_env --action "open fridge 1"
```
Returns JSON with `observation`, `goal_condition_success`, `done`, `won`, `admissible_commands`, `frame_path`, `step`, `action_taken`.

---

### `get_admissible_commands`
Return the list of currently valid action strings and the current step number.
**Use when:** you need to know what actions are available before choosing one.
```bash
python3 sandbox_client_vis.py get_admissible_commands
```
Returns JSON with `admissible_commands` (list) and `step`.

---

### `get_current_state`
Return a full snapshot of the current game state including task, observation, frame path, goal progress, and admissible commands.
**Use when:** you want a complete picture of the game at the current step (e.g. after resuming).
```bash
python3 sandbox_client_vis.py get_current_state
```
Returns JSON with `task`, `observation`, `goal_condition_success`, `done`, `step`, `admissible_commands`, `frame_path`, `log_file`.

---

### `get_current_frame_info`
Return metadata about the most recently saved visual frame (path, dimensions, file size).
**Use when:** you need to locate or verify the latest frame before displaying or uploading it.
```bash
python3 sandbox_client_vis.py get_current_frame_info
```
Returns JSON with `frame_path`, `step`, `exists`, `size_bytes`, `width`, `height`.

---

### `upload_frame_to_sandbox`
Upload a saved frame PNG from the host to this sandbox via openshell.
The frame lands at `/sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/`.
**Use when:** you want to display a game frame in the chat or after each `step_env` call.
```bash
python3 sandbox_client_vis.py upload_frame_to_sandbox --sandbox-name NAME [--step N]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--sandbox-name` | str | *(required)* | Name of this sandbox (e.g. `lasting-gorilla`) |
| `--step` | int | *(latest step)* | Step number of the frame to upload |

**Example:**
```bash
python3 sandbox_client_vis.py upload_frame_to_sandbox --sandbox-name lasting-gorilla --step 3
```
After upload, display the frame:
```bash
# Find the uploaded file and read it to show in chat
ls -t ~/.openclaw/workspace/skills/alfworld-game-viz/assets/step_*.png | head -1
```

---

### `get_game_log`
Return the last N step blocks from the host-side `game_log_visual.md`.
**Use when:** you want to review recent game history — actions taken, observations, goal progress.
```bash
python3 sandbox_client_vis.py get_game_log [--last-n N]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--last-n` | int | `10` | Number of recent step blocks to return |

**Example:**
```bash
python3 sandbox_client_vis.py get_game_log --last-n 5
```

---

### `search_game_log`
Search `game_log_visual.md` for lines matching a pattern (case-insensitive).
**Use when:** you want to find specific actions, observations, or keywords in the game history.
```bash
python3 sandbox_client_vis.py search_game_log --pattern PATTERN
```
| Argument | Type | Required | Description |
|---|---|---|---|
| `--pattern` | str | yes | Plain text or regex to match against log lines |

**Example:**
```bash
python3 sandbox_client_vis.py search_game_log --pattern "fridge"
```

---

## How to Play a Game Step

At each step you (the agent) are responsible for:

1. **Read the state** — call `get_current_state` to get the task, observation, and admissible commands.
2. **Inspect the frame** — call `upload_frame_to_sandbox` (or `get_current_frame_info` to locate it), then read the PNG file to see the visual scene.
3. **Choose an action** — based on the task, the observation text, and what you see in the image, pick the single best action from the `admissible_commands` list.
4. **Execute** — call `step_env --action "<chosen action>"`.
5. **Repeat** until `done` is `true`.

### Initialize a fresh game:
```bash
python3 sandbox_client_vis.py reset_env
python3 sandbox_client_vis.py upload_frame_to_sandbox --sandbox-name <your-sandbox>
```

### Continue an in-progress game:
```bash
python3 sandbox_client_vis.py get_current_state
# inspect frame, choose action, then:
python3 sandbox_client_vis.py step_env --action "put apple 1 in fridge 1"
python3 sandbox_client_vis.py upload_frame_to_sandbox --sandbox-name <your-sandbox>
```

## Frame Location (in sandbox)

After upload, frames are at:
```
~/.openclaw/workspace/skills/alfworld-game-viz/assets/step_NNNN.png
```
where `NNNN` is the zero-padded step number (e.g. `step_0000.png`, `step_0003.png`).

## Server URL

The client connects to `http://host.openshell.internal:9001/mcp` by default.
Override with `--server-url URL` or the `MCP_SERVER_URL` environment variable.

## Troubleshooting

If a tool call fails with a connection error:
1. Check the MCP server is running on the host: `curl http://host.openshell.internal:9001/mcp`
2. Confirm the sandbox policy is applied (allows egress to port 9001)
3. The THOR environment can take 60+ seconds to initialise after server start — retry with delays
4. If the venv is missing, recreate it:
   ```bash
   python3 -m venv $SKILL_DIR/venv
   $SKILL_DIR/venv/bin/pip install -q fastmcp
   ```
