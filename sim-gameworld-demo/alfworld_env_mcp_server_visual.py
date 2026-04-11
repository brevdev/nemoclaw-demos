"""
alfworld_env_mcp_server_visual.py
----------------------------------
FastMCP server that exposes the ALFWorld THOR 3D visual environment as MCP tools.
At every step the agent receives both a first-person RGB frame and text feedback.

Tools
-----
  reset_env()                              – Start / restart a THOR episode.
  step_env(action)                         – Execute an action, save frame, log step.
  get_admissible_commands()                – Return currently valid action strings.
  get_current_state()                      – Text + visual state snapshot.
  get_current_frame_info()                 – Path / shape of the latest saved frame.
  vlm_choose_action(...)                   – Ask NVIDIA VLM (image + text) to pick action.
  upload_frame_to_sandbox(sandbox, step)   – Push a frame PNG to a sandbox via openshell.
  get_game_log(last_n)                     – Return last N step blocks from game_log_visual.md.
  search_game_log(pattern)                 – grep game_log_visual.md for a pattern.

Run
---
    DISPLAY=:1 ALFWORLD_DATA=/ephemeral/cache/alfworld \\
        python alfworld_env_mcp_server_visual.py   # listens on 0.0.0.0:9001/mcp

Prerequisites
-------------
  * Xvfb running on DISPLAY=:1  (sudo apt-get install xvfb && Xvfb :1 -screen 0 1024x768x24 &)
  * ALFWORLD_DATA env var pointing to downloaded data
  * NVIDIA_API_KEY env var for the NVIDIA VLM
"""

import asyncio
import base64
import glob
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import yaml
from PIL import Image
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR     = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "configs" / "base_config.yaml"
_FRAMES_DIR     = _SCRIPT_DIR / "visual_frames"
_LOG_FILE       = _SCRIPT_DIR / "game_log_visual.md"

# Destination path inside the sandbox for uploaded frames, change path if needed
_SANDBOX_DEST   = "/sandbox/.openclaw/workspace/skills/alfworld-game-viz/assets/"

HISTORY_WINDOW  = 5   # steps of history injected into VLM prompts


# ── NVIDIA VLM helpers ────────────────────────────────────────────────────────

def _img2b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def _query_vlm(query: str, image_path: str | None = None, sys_prompt: str | None = None) -> str:
    invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        raise ValueError("NVIDIA_API_KEY not set.")
    if sys_prompt is None:
        sys_prompt = "You are a helpful AI assistant that can understand text and images."

    user_content = []
    if image_path and os.path.exists(image_path):
        b64  = _img2b64(image_path)
        ext  = image_path.lower().rsplit(".", 1)[-1]
        mime = {"png": "image/png", "gif": "image/gif",
                "webp": "image/webp"}.get(ext, "image/jpeg")
        user_content.append({"type": "image_url",
                              "image_url": {"url": f"data:{mime};base64,{b64}"}})
    user_content.append({"type": "text", "text": query})

    messages = [{"role": "system", "content": sys_prompt},
                {"role": "user",   "content": user_content}]
    payload = {
        "model": "google/gemma-4-31b-it",
        "messages": messages,
        "max_tokens": 16384,
        "temperature": 1.00,
        "top_p": 0.95,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }

    resp = requests.post(invoke_url, headers=headers, json=payload, stream=True, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"VLM error {resp.status_code}: {resp.text[:200]}")

    collected = []
    for line in resp.iter_lines():
        if line:
            text = line.decode("utf-8")
            if text.startswith("data: ") and text != "data: [DONE]":
                try:
                    chunk = json.loads(text[6:])
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        collected.append(delta)
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
    return "".join(collected)


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
        print(f"[visual_mcp] Cleared {removed} frame(s) from {_FRAMES_DIR}/")
    return removed


def _load_recent_steps(n: int = HISTORY_WINDOW) -> str:
    if not _LOG_FILE.exists():
        return ""
    text   = _LOG_FILE.read_text()
    blocks = re.split(r"(?=^## STEP:)", text, flags=re.MULTILINE)
    recent = [b.strip() for b in blocks if b.startswith("## STEP:")][-n:]
    return "\n".join(recent)


# ── VLM system prompt ─────────────────────────────────────────────────────────

_VLM_SYSTEM_PROMPT = """\
You are an expert agent playing an embodied household task game (ALFWorld / AI2-THOR).

HOW THE ENVIRONMENT WORKS:
- The game proceeds step by step. Each step you take ONE action, the world changes, and
  you receive a new image + text observation reflecting that new state.
- The image always shows the scene AFTER the last action was applied - study it carefully.
- The list of admissible actions changes every step to reflect what is now possible.

HOW TO USE THE HISTORY:
- You receive a summary of the last few steps (action taken -> what the game reported).
- Use this to avoid repeating actions that had no effect, to track objects you found,
  and to maintain a plan toward the task goal.
- If the same action keeps appearing without progress, change strategy.

YOUR DECISION PROCESS AT EACH STEP:
1. Re-read the TASK goal.
2. Review the RECENT STEP HISTORY - what was tried, what changed, what still needs doing.
3. Study the IMAGE to confirm the current scene and spot relevant objects.
4. Read the TEXT OBSERVATION for details invisible in the image (inventory, temperatures,
   receptacle contents, cleanliness status).
5. Pick the single best action from the admissible list that moves you closer to the goal.

Reply with ONLY the exact action text (copied verbatim from the admissible actions list).
Do not add any explanation, punctuation, or extra words."""


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
    print("[visual_mcp] AlfredThorEnv initialised.")


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
async def vlm_choose_action(
    task: str,
    observation: str,
    admissible_commands: list,
    frame_path: str,
    step: int = 0,
) -> str:
    """
    Ask the NVIDIA Nemotron Nano VLM to choose the next action using
    both the visual frame and the text observation, with rolling step history.

    Args:
        task                (str)       – Task description for this episode.
        observation         (str)       – Current text observation.
        admissible_commands (list[str]) – Valid actions at this step.
        frame_path          (str)       – Path to the current frame PNG.
        step                (int)       – Current step number.

    Returns JSON:
        chosen_action   (str)
        vlm_raw_output  (str)   – raw model reply before matching
        matched         (bool)  – True if raw output matched an admissible command
    """
    if not admissible_commands:
        return json.dumps({"error": "No admissible commands provided."})

    numbered = "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(admissible_commands))
    history  = _load_recent_steps(HISTORY_WINDOW)

    query = (
        f"TASK: {task}\n\n"
        f"--- RECENT STEP HISTORY (last {HISTORY_WINDOW} steps) ---\n"
        f"{history if history else '(no history yet)'}\n\n"
        f"--- CURRENT STATE (step {step}) ---\n"
        f"The image above shows the environment AFTER step {step - 1}.\n"
        f"Text observation: {observation.strip()}\n\n"
        f"Admissible actions ({len(admissible_commands)} available):\n{numbered}\n\n"
        "Which single action should I take? Reply with the exact action text only."
    )

    raw = _query_vlm(query=query, image_path=frame_path, sys_prompt=_VLM_SYSTEM_PROMPT)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    matched = True
    chosen  = raw
    if raw not in admissible_commands:
        matched = False
        raw_lower = raw.lower()
        for cmd in admissible_commands:
            if cmd.lower() == raw_lower:
                chosen = cmd; matched = True; break
        if not matched:
            for cmd in admissible_commands:
                if cmd.lower() in raw_lower:
                    chosen = cmd; matched = True; break
        if not matched:
            chosen = admissible_commands[0]

    return json.dumps({
        "chosen_action":  chosen,
        "vlm_raw_output": raw,
        "matched":        matched,
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
    asyncio.run(
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=9001,
            path="/mcp",
            log_level="info",
        )
    )
