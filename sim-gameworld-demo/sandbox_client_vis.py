"""
sandbox_client_vis.py
---------------------
Sandbox-side MCP client for alfworld_env_mcp_server_visual.py running on the host.

Mirrors host_client_vis.py but targets the host visual MCP server via the
OpenShell internal hostname, and writes history into the sandbox workspace.

At every step the client:
  1. Calls vlm_choose_action  – NVIDIA Nemotron Nano VLM picks the action using
                                the current frame + text + rolling step history.
  2. Calls step_env           – executes the action in the THOR 3D environment.
  3. Optionally calls upload_frame_to_sandbox – tells the HOST server to push the
                                new frame PNG into this sandbox via openshell.
                                Set SANDBOX_NAME below to enable.

Frame upload destination
------------------------
The host server uploads frames to the OpenClaw agent workspace inside the sandbox:
    /sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/step_NNNN.png
This path is owned and used by the OpenClaw agent; it is set on the server side.

Usage
-----
    # Terminal 1 (on the HOST) – start the visual MCP server:
    DISPLAY=:1 ALFWORLD_DATA=/ephemeral/cache/alfworld \\
        python alfworld_env_mcp_server_visual.py

    # Copy this file into the sandbox, then inside the sandbox run:
    python sandbox_client_vis.py

To continue an in-progress episode without resetting:
    history = asyncio.run(play_game(reset=False))
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from colorama import Fore, init
from fastmcp import Client

init(autoreset=True)

# ── Configuration ─────────────────────────────────────────────────────────────
VISUAL_MCP_URL = "http://host.openshell.internal:9001/mcp"

MAX_STEPS    = 1
SANDBOX_NAME = "rousing-pochard"  # sandbox name for frame uploads via openshell
                                  # Frames land at the OpenClaw agent workspace (set by the server):
                                  #   /sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/

open_claw_skill_path = Path("/sandbox/.openclaw/workspace/skills/")
HISTORY_FILE = open_claw_skill_path / "game_history_visual_sandbox.md"


# ── Markdown helpers ───────────────────────────────────────────────────────────

def _md_new_game(f, task: str, obs: str, banner: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write(f"\n---\n\n## {banner} — {ts}\n\n")
    f.write(f"**Task:** {task}\n\n")
    f.write(f"**Initial Observation:**\n> {obs}\n\n")

def _md_resume(f, step: int) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write(f"\n### Resumed at step {step} — {ts}\n\n")

def _md_step(f, step: int, action: str, obs: str,
             gc_sr: float, done: bool, frame_path: str,
             uploaded_to: str = "") -> None:
    f.write(f"### Step {step:02d}\n")
    f.write(f"**Action:** `{action}`\n\n")
    f.write(f"**Observation:** {obs}\n\n")
    f.write(f"**Goal conditions met:** {gc_sr:.0%} | **Done:** {done}\n\n")
    f.write(f"**Frame (host):** `{frame_path}`")
    if uploaded_to:
        f.write(f"\n\n**Frame (sandbox):** `{uploaded_to}`")
    f.write("\n\n")

def _md_summary(f, won: bool, gc_sr: float, total_steps: int) -> None:
    f.write("### Result\n")
    if won:
        f.write(f"**SUCCESS** — task completed in {total_steps} steps. "
                f"Goal conditions: {gc_sr:.0%}\n\n")
    else:
        f.write(f"**Episode ended** at step {total_steps}. "
                f"Goal conditions: {gc_sr:.0%}\n\n")


# ── Main game loop ─────────────────────────────────────────────────────────────

async def play_game(reset: bool = True) -> None:
    """
    Play (or continue) an ALFWorld THOR game via the visual MCP server on the host.

    Args:
        reset (bool): True  → call reset_env and start a fresh episode.
                      False → resume from the server's current state;
                              auto-resets only if no game is active.
    """
    print(Fore.CYAN + f"\nConnecting to visual MCP server at {VISUAL_MCP_URL} ...\n")

    async with Client(VISUAL_MCP_URL) as client:

        # ── Reset or resume ───────────────────────────────────────────────────
        if reset:
            raw    = await client.call_tool("reset_env", {})
            state  = json.loads(raw.content[0].text)
            banner = "GAME START (fresh reset)"
        else:
            raw   = await client.call_tool("get_current_state", {})
            state = json.loads(raw.content[0].text)
            if not state.get("observation"):
                raw    = await client.call_tool("reset_env", {})
                state  = json.loads(raw.content[0].text)
                banner = "GAME START (auto-reset: no active game)"
            else:
                banner = f"RESUMING from step {state['step']}"

        task         = state["task"]
        obs          = state["observation"]
        admissible   = state["admissible_commands"]
        gc_sr        = state.get("goal_condition_success", 0.0)
        done         = state.get("done", False)
        frame_path   = state.get("frame_path", "")
        server_step  = state.get("step", 0)
        current_step = server_step

        print(Fore.GREEN + "=" * 70)
        print(Fore.GREEN + banner)
        print(Fore.GREEN + "=" * 70)
        print(Fore.WHITE + obs)
        print(Fore.YELLOW + f"\nTask       : {task}")
        print(Fore.CYAN  + f"Frame      : {frame_path}")
        print(Fore.CYAN  + f"Actions ({len(admissible)}): {admissible[:4]}"
              f"{'  ...' if len(admissible) > 4 else ''}")
        print()

        if done:
            print(Fore.YELLOW + "Episode already finished. Pass reset=True to start fresh.")
            return

        with open(HISTORY_FILE, "w" if "GAME START" in banner else "a", encoding="utf-8") as md:
            if "GAME START" in banner:
                _md_new_game(md, task, obs, banner)
            else:
                _md_resume(md, server_step)

            for i in range(1, MAX_STEPS + 1):
                display_step = server_step + i

                # ── VLM picks action (image + text + server-side history) ────
                raw = await client.call_tool(
                    "vlm_choose_action",
                    {
                        "task":                task,
                        "observation":         obs,
                        "admissible_commands": admissible,
                        "frame_path":          frame_path,
                        "step":                current_step,
                    },
                )
                vlm_result  = json.loads(raw.content[0].text)

                if "error" in vlm_result:
                    print(Fore.RED + f"[VLM ERROR] {vlm_result['error']}")
                    break

                action  = vlm_result["chosen_action"]
                matched = vlm_result.get("matched", True)
                raw_out = vlm_result.get("vlm_raw_output", "")

                print(Fore.MAGENTA + f"[Step {display_step:02d}] VLM chose: » {action} «"
                      + (Fore.YELLOW + "  (fallback)" if not matched else ""))
                if not matched:
                    print(Fore.YELLOW + f"           raw output: {raw_out[:80]}")

                # ── Execute action ────────────────────────────────────────────
                raw    = await client.call_tool("step_env", {"action": action})
                result = json.loads(raw.content[0].text)

                if "error" in result:
                    print(Fore.RED + f"[STEP ERROR] {result['error']}")
                    md.write(f"> ⚠️ Error: {result['error']}\n\n")
                    break

                obs          = result["observation"]
                gc_sr        = result.get("goal_condition_success", 0.0)
                done         = result["done"]
                won          = result.get("won", False)
                current_step = result.get("step", current_step)
                admissible   = result.get("admissible_commands", [])
                frame_path   = result.get("frame_path", frame_path)

                print(Fore.WHITE + f"         Obs   : {obs[:200]}{'...' if len(obs) > 200 else ''}")
                print(Fore.BLUE  + f"         GC    : {gc_sr:.0%}  |  Done: {done}  |  Won: {won}")
                print(Fore.CYAN  + f"         Frame : {frame_path}")

                # ── Optional frame upload into this sandbox ───────────────────
                uploaded_to = ""
                if SANDBOX_NAME:
                    up_raw    = await client.call_tool(
                        "upload_frame_to_sandbox",
                        {"sandbox_name": SANDBOX_NAME, "step": current_step},
                    )
                    up_result = json.loads(up_raw.content[0].text)
                    if up_result.get("returncode") == 0:
                        uploaded_to = up_result.get("dest_path", "")
                        print(Fore.GREEN + f"         Uploaded → {uploaded_to}")
                    else:
                        err = up_result.get("stderr") or up_result.get("error", "unknown")
                        print(Fore.RED + f"         Upload failed: {err}")

                print()
                _md_step(md, display_step, action, obs, gc_sr, done, frame_path, uploaded_to)

                if done:
                    break

            # ── Summary ───────────────────────────────────────────────────────
            total_steps = server_step + i
            won_final   = won if done else False
            _md_summary(md, won_final, gc_sr, total_steps)

        print(Fore.GREEN + "=" * 70)
        if won_final:
            print(Fore.GREEN + f"SUCCESS! Task completed in {total_steps} steps.")
        elif done:
            print(Fore.RED   + f"Episode ended at step {total_steps}. GC: {gc_sr:.0%}")
        else:
            print(Fore.YELLOW + f"Paused after {MAX_STEPS} steps (global step {total_steps}).")
        print(Fore.GREEN + "=" * 70)
        print(Fore.CYAN + f"History written to : {HISTORY_FILE}")
        if SANDBOX_NAME:
            print(Fore.CYAN + f"Frames uploaded to : "
                  "/sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/")


if __name__ == "__main__":
    asyncio.run(play_game(reset=True))
    # To continue without resetting:
    # asyncio.run(play_game(reset=False))
