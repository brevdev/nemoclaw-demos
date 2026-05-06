#!/usr/bin/env python3
"""
alfworld_env_mcp_server_visual.py
----------------------------------
FastMCP server that exposes the ALFWorld THOR 3D visual environment as MCP tools.
At every step the agent receives both a first-person RGB frame and text feedback.

The sandbox agent (which has its own LLM with tool-calling capability) decides
which tool to call and which action to take.  No secondary LLM or action-picker
runs here — this server is pure environment I/O.

Tools
-----
  reset_env()                              – Start / restart a THOR episode.
  step_env(action)                         – Execute an action, save frame, log step.
  get_admissible_commands()                – Return currently valid action strings.
  get_current_state()                      – Text + visual state snapshot.
  get_current_frame_info()                 – Path / shape of the latest saved frame.
  upload_frame_to_sandbox(sandbox, step)   – Push a frame PNG to a sandbox via openshell.
  get_game_log(last_n)                     – Return last N step blocks from game_log_visual.md.
  search_game_log(pattern)                 – grep game_log_visual.md for a pattern.

Run
---
    DISPLAY=:1 ALFWORLD_DATA=/ephemeral/cache/alfworld \\
        python alfworld_env_mcp_server_visual.py          # listens on 0.0.0.0:9001/mcp
    python alfworld_env_mcp_server_visual.py --port 9002

Default URL: http://0.0.0.0:9001/mcp

Environment
-----------
  ALFWORLD_DATA               – path to downloaded ALFWorld data
  MCP_ALFWORLD_HOST           – bind host  (default 0.0.0.0)
  MCP_ALFWORLD_PORT           – bind port  (default 9001)
  MCP_ALFWORLD_PATH           – URL path   (default /mcp)

Prerequisites
-------------
  * Xvfb running on DISPLAY=:1  (sudo apt-get install xvfb && Xvfb :1 -screen 0 1024x768x24 &)
  * ALFWORLD_DATA env var pointing to downloaded data
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from dotenv import load_dotenv
from colorama import Fore, init as colorama_init
from fastmcp import FastMCP

load_dotenv()
colorama_init(autoreset=True)

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR     = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "configs" / "base_config.yaml"
_FRAMES_DIR     = _SCRIPT_DIR / "visual_frames"
_LOG_FILE       = _SCRIPT_DIR / "game_log_visual.md"

# Destination path inside the sandbox for uploaded frames — change if needed
_SANDBOX_DEST   = "/sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/"


# ── Frame helpers ─────────────────────────────────────────────────────────────

def _save_frame(frame: np.ndarray, step: int) -> str:
    _FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    path = _FRAMES_DIR / f"step_{step:04d}.png"
    Image.fromarray(frame.astype(np.uint8)).save(path)
    return str(path)


# ── Step logger ───────────────────────────────────────────────────────────────
# Each block is grep/sed/awk friendly:
#   ## STEP:0001 | ACTION:open fridge 1 | DONE:False | GC:0.00
#   OBS: You open the fridge 1. ...
#   FRAME: visual_frames/step_0001.png

def _init_log(task: str) -> None:
    with open(_LOG_FILE, "w") as fh:
        fh.write("# ALFWorld Visual Game Log\n")
        fh.write(f"STARTED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"TASK: {task}\n")
        fh.write("ENV: AlfredThorEnv\n\n---\n\n")
        fh.write("## STEP:0000 | ACTION:(initial) | DONE:False | GC:0.00\n")


def _log_step(step: int, action: str, obs: str, done: bool,
              gc_sr: float, frame_path: str) -> None:
    obs_single = obs.replace("\n", " ").strip()
    with open(_LOG_FILE, "a") as fh:
        fh.write(f"\n## STEP:{step:04d} | ACTION:{action} | DONE:{done} | GC:{gc_sr:.2f}\n")
        fh.write(f"OBS: {obs_single}\n")
        fh.write(f"FRAME: {frame_path}\n")


def _clear_frames() -> int:
    """Delete all step_*.png files from the visual_frames folder. Returns count removed."""
    removed = 0
    for f in glob.glob(str(_FRAMES_DIR / "step_*.png")):
        os.remove(f)
        removed += 1
    if removed:
        print(f"[alfworld_mcp] Cleared {removed} frame(s) from {_FRAMES_DIR}/")
    return removed


# ── Global environment state ──────────────────────────────────────────────────

_env                      = None
_current_obs:  str        = ""
_current_done: bool       = False
_current_gc_sr: float     = 0.0
_admissible_commands: list = []
_task_desc:    str        = ""
_step_count:   int        = 0
_current_frame_path: str  = ""


def _init_env() -> None:
    global _env
    if _env is not None:
        return
    from alfworld.agents.environment import get_environment

    if not os.path.isfile(_DEFAULT_CONFIG):
        raise FileNotFoundError(f"ALFWorld config not found: {_DEFAULT_CONFIG}")
    with open(_DEFAULT_CONFIG) as fh:
        config = yaml.safe_load(fh)

    config["env"]["type"]                        = "AlfredThorEnv"
    config["controller"]["type"]                 = "oracle"
    config["env"]["thor"]["save_frames_to_disk"] = False

    raw = get_environment("AlfredThorEnv")(config, train_eval="eval_in_distribution")
    _env = raw.init_env(batch_size=1)
    _clear_frames()
    print("[alfworld_mcp] AlfredThorEnv initialised.")


def _extract_task(obs: str) -> str:
    for line in obs.splitlines():
        if line.strip().lower().startswith("your task is"):
            return line.strip()
    return ""


# ── FastMCP app ───────────────────────────────────────────────────────────────
mcp = FastMCP("AlfWorldVisualEnvMCP")


@mcp.tool()
async def reset_env() -> str:
    """
    Reset the ALFWorld THOR environment and start a new game episode.
    Saves the initial frame and initialises the game log.

    Returns JSON:
        task                (str)
        observation         (str)
        admissible_commands (list[str])
        frame_path          (str)   – path to step_0000.png
        step                (int)   – 0
    """
    global _current_obs, _current_done, _current_gc_sr
    global _admissible_commands, _task_desc, _step_count, _current_frame_path

    _init_env()
    _clear_frames()
    obs, info = _env.reset()
    frames    = _env.get_frames()   # (1, H, W, 3) uint8 RGB

    _current_obs          = obs[0]
    _current_done         = False
    _current_gc_sr        = 0.0
    _admissible_commands  = list(info["admissible_commands"][0])
    _task_desc            = _extract_task(_current_obs)
    _step_count           = 0
    _current_frame_path   = _save_frame(frames[0], step=0)

    _init_log(_task_desc)

    return json.dumps({
        "task":                 _task_desc,
        "observation":          _current_obs,
        "admissible_commands":  _admissible_commands,
        "frame_path":           _current_frame_path,
        "step":                 _step_count,
    })


@mcp.tool()
async def step_env(action: str) -> str:
    """
    Execute an action in the THOR environment.
    Saves the resulting frame and appends a line to game_log_visual.md.

    Args:
        action (str): One of the currently admissible action strings.

    Returns JSON:
        observation             (str)
        goal_condition_success  (float)  – fraction of goal conditions met (0–1)
        done                    (bool)
        won                     (bool)
        admissible_commands     (list[str])
        frame_path              (str)    – path to newly saved frame PNG
        step                    (int)
        action_taken            (str)
    """
    global _current_obs, _current_done, _current_gc_sr
    global _admissible_commands, _step_count, _current_frame_path

    if _env is None:
        return json.dumps({"error": "Environment not initialised. Call reset_env first."})
    if _current_done:
        return json.dumps({"error": "Episode already done. Call reset_env.", "done": True})

    # AlfredThorEnv.step → (obs, None, dones, infos)
    obs, _scores, dones, infos = _env.step([action])
    frames = _env.get_frames()

    _step_count          += 1
    _current_obs          = obs[0]
    _current_done         = bool(dones[0])
    won                   = bool(infos.get("won", [False])[0])
    _current_gc_sr        = float(infos.get("goal_condition_success_rate", [0.0])[0])
    _admissible_commands  = (list(infos["admissible_commands"][0])
                             if not _current_done else [])
    _current_frame_path   = _save_frame(frames[0], step=_step_count)

    _log_step(_step_count, action, _current_obs,
              _current_done, _current_gc_sr, _current_frame_path)

    return json.dumps({
        "observation":              _current_obs,
        "goal_condition_success":   _current_gc_sr,
        "done":                     _current_done,
        "won":                      won,
        "admissible_commands":      _admissible_commands,
        "frame_path":               _current_frame_path,
        "step":                     _step_count,
        "action_taken":             action,
    })


@mcp.tool()
async def get_admissible_commands() -> str:
    """
    Return the list of currently valid action strings.

    Returns JSON:
        admissible_commands (list[str])
        step                (int)
    """
    return json.dumps({
        "admissible_commands": _admissible_commands,
        "step":                _step_count,
    })


@mcp.tool()
async def get_current_state() -> str:
    """
    Return a full snapshot of the current game state (text + frame).

    Returns JSON:
        task                    (str)
        observation             (str)
        goal_condition_success  (float)
        done                    (bool)
        step                    (int)
        admissible_commands     (list[str])
        frame_path              (str)
        log_file                (str)
    """
    return json.dumps({
        "task":                   _task_desc,
        "observation":            _current_obs,
        "goal_condition_success": _current_gc_sr,
        "done":                   _current_done,
        "step":                   _step_count,
        "admissible_commands":    _admissible_commands,
        "frame_path":             _current_frame_path,
        "log_file":               str(_LOG_FILE),
    })


@mcp.tool()
async def get_current_frame_info() -> str:
    """
    Return metadata about the most recently saved visual frame.

    Returns JSON:
        frame_path  (str)
        step        (int)
        exists      (bool)
        size_bytes  (int)
        width       (int)
        height      (int)
    """
    path   = Path(_current_frame_path) if _current_frame_path else None
    exists = path is not None and path.exists()
    w = h = size = 0
    if exists:
        size = path.stat().st_size
        with Image.open(path) as img:
            w, h = img.size
    return json.dumps({
        "frame_path": _current_frame_path,
        "step":       _step_count,
        "exists":     exists,
        "size_bytes": size,
        "width":      w,
        "height":     h,
    })


@mcp.tool()
async def upload_frame_to_sandbox(sandbox_name: str, step: int | None = None) -> str:
    """
    Upload a saved frame PNG to a sandbox via openshell.

    Uses the command:
        openshell sandbox upload <sandbox_name> <frame_path> <dest_path>

    The destination on the sandbox is always:
        /sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/

    Args:
        sandbox_name (str) – Name of the target sandbox (e.g. "my-sandbox").
        step         (int) – Step number to upload (defaults to latest step).

    Returns JSON:
        sandbox_name    (str)
        frame_path      (str)
        dest_path       (str)
        returncode      (int)   – 0 means success
        stdout          (str)
        stderr          (str)
    """
    target_step = step if step is not None else _step_count
    frame_path  = str(_FRAMES_DIR / f"step_{target_step:04d}.png")

    if not Path(frame_path).exists():
        return json.dumps({
            "error": f"Frame not found: {frame_path}. Run reset_env / step_env first."
        })

    cmd = ["openshell", "sandbox", "upload", "--no-git-ignore",
           sandbox_name, frame_path, _SANDBOX_DEST]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.dumps({
            "sandbox_name": sandbox_name,
            "frame_path":   frame_path,
            "dest_path":    _SANDBOX_DEST,
            "returncode":   result.returncode,
            "stdout":       result.stdout.strip(),
            "stderr":       result.stderr.strip(),
        })
    except FileNotFoundError:
        return json.dumps({
            "error": "'openshell' command not found. Is openshell installed and on PATH?"
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "openshell upload timed out after 30s."})


@mcp.tool()
async def get_game_log(last_n: int = 10) -> str:
    """
    Return the last N step blocks from game_log_visual.md.

    Args:
        last_n (int) – Number of recent steps to return (default 10).

    Returns JSON:
        log_file    (str)
        steps_found (int)
        content     (str)  – raw text of the last N step blocks
    """
    if not _LOG_FILE.exists():
        return json.dumps({"error": f"Log file not found: {_LOG_FILE}"})

    text   = _LOG_FILE.read_text()
    blocks = re.split(r"(?=^## STEP:)", text, flags=re.MULTILINE)
    step_blocks = [b.strip() for b in blocks if b.startswith("## STEP:")]
    recent = step_blocks[-last_n:]

    return json.dumps({
        "log_file":    str(_LOG_FILE),
        "steps_found": len(step_blocks),
        "content":     "\n\n".join(recent),
    })


@mcp.tool()
async def search_game_log(pattern: str) -> str:
    """
    Search game_log_visual.md for lines matching a pattern (case-insensitive grep).

    Args:
        pattern (str) – Plain text or regex pattern to search for.

    Returns JSON:
        pattern     (str)
        log_file    (str)
        match_count (int)
        matches     (list[str])  – matching lines with their line numbers
    """
    if not _LOG_FILE.exists():
        return json.dumps({"error": f"Log file not found: {_LOG_FILE}"})

    try:
        result = subprocess.run(
            ["grep", "-in", pattern, str(_LOG_FILE)],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in result.stdout.splitlines() if l]
    except subprocess.TimeoutExpired:
        lines = []

    return json.dumps({
        "pattern":     pattern,
        "log_file":    str(_LOG_FILE),
        "match_count": len(lines),
        "matches":     lines,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ALFWorld Visual Environment MCP Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=os.environ.get("MCP_ALFWORLD_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_ALFWORLD_PORT", "9001")))
    parser.add_argument("--path", default=os.environ.get("MCP_ALFWORLD_PATH", "/mcp"))
    args = parser.parse_args()

    print(
        Fore.GREEN +
        f"[mcp-server] AlfWorldVisualEnvMCP  →  "
        f"http://{args.host}:{args.port}{args.path}"
    )
    print(Fore.CYAN  + f"[mcp-server] Config : {_DEFAULT_CONFIG}")
    print(Fore.CYAN  + f"[mcp-server] Frames : {_FRAMES_DIR}")
    print(Fore.YELLOW + "[mcp-server] Reachable from sandbox via host's LAN/bridge IP on that port.")
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        path=args.path,
        show_banner=False,
    )
