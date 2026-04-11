# ALFWorld Game Visualizer

## Purpose

Display visual frames from ALFWorld THOR 3D environment game steps.
The MCP server on the host uploads PNG frames into the `assets/` subfolder
of this skill directory after each game step.

## Trigger

Activate this skill when:
- User asks to start/play/continue an ALFWorld game
- User asks to see the current game frame or step image
- User references "alfworld", "game viz", "game visualization", or "game step image"

## Frame Location

Frames are uploaded by the host MCP server to:
```
skills/alfworld-game-viz/assets/step_NNNN.png
```

Where `NNNN` is the zero-padded step number (e.g., `step_0000.png`, `step_0001.png`).

## How to Show Game Step Images

After each game step (or when the user asks to see the current frame):

1. **Find the latest frame:**
   ```bash
   ls -t /sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/step_*.png 2>/dev/null | head -1
   ```

2. **Display it** using the `read` tool on the PNG file — this sends the image
   as an attachment the user can see directly in chat.

3. **Pair with context** — when showing a frame, also mention:
   - The step number
   - The action that was taken (if known)
   - The observation text from that step
   - Goal condition progress if available

## Game History

The sandbox client writes a Markdown game log to:
```
skills/game_history_visual_sandbox.md
```
(Resolved: `/sandbox/.openclaw/workspace/skills/game_history_visual_sandbox.md`)

Read this file to get the full context of the current game session
(task, observations, actions taken, goal conditions).

## Running the Game Client

The MCP client that drives the game lives inside this skill:
```
skills/alfworld-game-viz/scripts/sandbox_client_vis.py
```
(Resolved: `/sandbox/.openclaw/workspace/skills/alfworld-game-viz/scripts/sandbox_client_vis.py`)

- `SANDBOX_NAME` is set to `lasting-gorilla` (this sandbox)
- `VISUAL_MCP_URL` points to the host MCP server at `http://host.openshell.internal:9001/mcp`
- `MAX_STEPS = 1` — one step per invocation

### Initialize (fresh game):
```bash
cd /sandbox/.openclaw/workspace/skills/alfworld-game-viz/scripts && python sandbox_client_vis.py
```
This calls `play_game(reset=True)` — resets the environment, clears old frames from `assets/`, and plays one step.

### Continue (next step without reset):
```bash
cd /sandbox/.openclaw/workspace/skills/alfworld-game-viz/scripts && python -c "import asyncio; from sandbox_client_vis import play_game; asyncio.run(play_game(reset=False))"
```
This calls `play_game(reset=False)` — continues from current server state.

## Cron Job: Auto-Progress

A cron job (`alfworld-game-step`) runs every 30 seconds to progress the game by one step.
The cron job agent should:

1. Run the continue command (reset=False) from the scripts directory
2. Read the game history file to check `done` status and step count
3. **Disable itself** if:
   - `done` is True (game completed), OR
   - Step count exceeds 30

## Heartbeat: On-Demand Monitoring

When heartbeat is triggered:

1. Read `game_history_visual_sandbox.md`
2. Parse all steps into a **markdown table** with columns:
   | Step | Action | Observation (truncated) | GC% | Done |
3. Find and display the **latest frame** PNG from `assets/`
4. Report overall game status (task, current step, win/loss)

## Reset Behavior

On `play_game(reset=True)`:
- History MD file is overwritten (opened with `"w"` mode)
- All `step_*.png` files in `assets/` are deleted
- Fresh game begins from step 0

## Notes

- The host MCP server must be running before the client can connect
- Frames are cumulative — each step adds a new PNG, older ones remain
- Server warmup may take 60+ seconds; retry with delays if you get 502s
- If no frames exist in `assets/`, the host server may not be running or
  the upload step failed — check the client output for errors
