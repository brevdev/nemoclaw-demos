"""
alfworld_env_query_visual.py
============================
Runs ALFWorld with the THOR 3D simulator.  At every step the NVIDIA Nemotron
Nano VLM receives both the first-person RGB frame AND the text observation,
together with a rolling history of the last few steps so it can reason about
what has already been tried and what to do next.

Every step is written to a plain-text game log (game_log_visual.md) that is
designed for quick command-line retrieval:

    grep "^## STEP:"   game_log_visual.md        # all step headers
    grep "ACTION:"     game_log_visual.md        # every action taken
    grep "DONE:True"   game_log_visual.md        # check if task completed
    sed -n '/^## STEP:0003/,/^## STEP:0004/p' game_log_visual.md
    awk '/^## STEP:0003/,/^## STEP:0004/' game_log_visual.md

Prerequisites
-------------
* ALFWORLD_DATA env var  -> path to downloaded ALFWorld data
* NVIDIA_API_KEY env var -> NVIDIA API key
* Virtual display: Xvfb :1 -screen 0 1024x768x24 &  then  export DISPLAY=:1

Usage
-----
    DISPLAY=:1 ALFWORLD_DATA=/ephemeral/cache/alfworld python3 alfworld_env_query_visual.py
"""

import argparse
import base64
import os
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import yaml
from PIL import Image
from alfworld.agents.environment import get_environment
from dotenv import load_dotenv

load_dotenv()

_SCRIPT_DIR     = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "configs" / "base_config.yaml"
_FRAMES_DIR     = _SCRIPT_DIR / "visual_frames"
_LOG_FILE       = _SCRIPT_DIR / "game_log_visual.md"

HISTORY_WINDOW  = 5   # how many recent steps to inject into each LLM prompt

print(f"Default config : {_DEFAULT_CONFIG}")
print(f"Game log       : {_LOG_FILE}")


# -- NVIDIA VLM client (from tests/test_vlm_query.py) --------------------------

def img2base64_str(img_file_loc):
    with open(img_file_loc, "rb") as f:
        return base64.b64encode(f.read()).decode()

def is_base64(s):
    if not s or not isinstance(s, str):
        return False
    try:
        decoded = base64.b64decode(s, validate=True)
        return base64.b64encode(decoded).decode("utf-8").rstrip("=") == s.rstrip("=")
    except Exception:
        return False

def query_nvidia_vlm(query, image_file_loc=None, sys_prompt=None):
    url     = "https://inference-api.nvidia.com/v1/chat/completions"
    model   = "nvidia/nvidia/nemotron-nano-12b-v2-vl"
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        raise ValueError("NVIDIA_API_KEY not set.")
    if sys_prompt is None:
        sys_prompt = "You are a helpful AI assistant that can understand text and images."

    image_base64, image_mime = None, "image/jpeg"
    if image_file_loc:
        if is_base64(image_file_loc):
            image_base64 = image_file_loc
        elif os.path.exists(image_file_loc):
            image_base64 = img2base64_str(image_file_loc)
            ext = image_file_loc.lower().rsplit(".", 1)[-1]
            image_mime = {"png": "image/png", "gif": "image/gif",
                          "webp": "image/webp"}.get(ext, "image/jpeg")

    user_content = []
    if image_base64:
        user_content.append({"type": "image_url",
                              "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})
    user_content.append({"type": "text", "text": query})

    messages = [{"role": "system", "content": sys_prompt},
                {"role": "user",   "content": user_content}]
    payload  = {"model": model, "messages": messages,
                "temperature": 0.2, "top_p": 0.7, "max_tokens": 256, "stream": False}
    headers  = {"Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"}

    print(f"VLM image={image_base64 is not None}  model={model}")
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"VLM error {resp.status_code}: {resp.text[:200]}")
    output = resp.json()["choices"][0]["message"]["content"]
    print(f"VLM response ({len(output)} chars): {output[:120]}")
    return output


# -- Config loading ------------------------------------------------------------

def load_alfworld_config():
    parser = argparse.ArgumentParser(description="ALFWorld THOR visual+text VLM agent.")
    parser.add_argument("config_file", nargs="?", default=str(_DEFAULT_CONFIG))
    parser.add_argument("-p", "--params", nargs="+", metavar="key=value", default=[])
    args = parser.parse_args()
    if not os.path.isfile(args.config_file):
        raise SystemExit(f"Config not found: {args.config_file}")
    with open(args.config_file) as fh:
        config = yaml.safe_load(fh)
    for param in args.params:
        fqn_key, value = param.split("=", 1)
        node, keys = config, fqn_key.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return config


# -- Frame helpers -------------------------------------------------------------

def save_frame(frame: np.ndarray, step: int) -> str:
    _FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    path = _FRAMES_DIR / f"step_{step:04d}.png"
    Image.fromarray(frame.astype(np.uint8)).save(path)
    return str(path)


# -- Step logger ---------------------------------------------------------------
#
# Log format - each block starts with "## STEP:" for easy grep/awk splitting:
#
#   ## STEP:0001 | ACTION:go to fridge 1 | DONE:False
#   OBS: You arrive at loc 14. The fridge 1 is closed.
#   FRAME: visual_frames/step_0001.png
#
# Retrieval cheatsheet (run from alfworld-game/):
#   grep "^## STEP:"                  game_log_visual.md   -> step index
#   grep "ACTION:"                    game_log_visual.md   -> all actions
#   grep "DONE:True"                  game_log_visual.md   -> completion line
#   grep -i "egg"                     game_log_visual.md   -> steps mentioning egg
#   sed -n '/^## STEP:0003/,/^## STEP:0004/p' game_log_visual.md
#   awk '/^## STEP:0003/,/^## STEP:0004/' game_log_visual.md

def init_log(task: str, env_type: str) -> None:
    with open(_LOG_FILE, "w") as fh:
        fh.write("# ALFWorld Visual Game Log\n")
        fh.write(f"STARTED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        fh.write(f"TASK: {task}\n")
        fh.write(f"ENV: {env_type}\n\n")
        fh.write("---\n\n")
        fh.write("## STEP:0000 | ACTION:(initial) | DONE:False\n")

def log_step(step: int, action: str, obs: str, done: bool, frame_path: str) -> None:
    obs_single = obs.replace("\n", " ").strip()
    with open(_LOG_FILE, "a") as fh:
        fh.write(f"\n## STEP:{step:04d} | ACTION:{action} | DONE:{done}\n")
        fh.write(f"OBS: {obs_single}\n")
        fh.write(f"FRAME: {frame_path}\n")

def load_recent_steps(n: int = HISTORY_WINDOW) -> str:
    """Read the last n completed step blocks from the log file."""
    if not _LOG_FILE.exists():
        return ""
    text   = _LOG_FILE.read_text()
    blocks = re.split(r"(?=^## STEP:)", text, flags=re.MULTILINE)
    recent = [b.strip() for b in blocks if b.startswith("## STEP:")][-n:]
    return "\n".join(recent)


# -- System prompt -------------------------------------------------------------

SYSTEM_PROMPT = """\
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


# -- LLM action selection ------------------------------------------------------

def llm_choose_action(task: str, observation: str, admissible_commands: list,
                      frame_path: str, step: int) -> str:
    numbered = "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(admissible_commands))
    history  = load_recent_steps(HISTORY_WINDOW)

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

    raw = query_nvidia_vlm(query=query, image_file_loc=frame_path, sys_prompt=SYSTEM_PROMPT)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    if raw in admissible_commands:
        return raw
    raw_lower = raw.lower()
    for cmd in admissible_commands:
        if cmd.lower() == raw_lower:
            return cmd
    for cmd in admissible_commands:
        if cmd.lower() in raw_lower:
            return cmd
    print(f"[WARN] VLM output '{raw}' not matched; defaulting to first option.")
    return admissible_commands[0]


# -- ALFWorld environment setup ------------------------------------------------

config = load_alfworld_config()
config["env"]["type"]                        = "AlfredThorEnv"
config["controller"]["type"]                 = "oracle"
config["env"]["thor"]["save_frames_to_disk"] = False

env_type = config["env"]["type"]
print(f"\nEnvironment : {env_type}  |  Controller: {config['controller']['type']}")
print(f"THOR screen : {config['env']['thor']['screen_width']}x{config['env']['thor']['screen_height']}")

env = get_environment(env_type)(config, train_eval="eval_in_distribution")
env = env.init_env(batch_size=1)

# -- Reset ---------------------------------------------------------------------

obs, info = env.reset()
frames = env.get_frames()   # (1, H, W, 3) uint8 RGB

print("\n" + "=" * 72)
print("ALFWORLD THOR  -  VISUAL + TEXT + HISTORY AGENT")
print("=" * 72)
print(f"\nInitial observation:\n{obs[0]}")

task_desc = next(
    (line.strip() for line in obs[0].splitlines()
     if line.strip().lower().startswith("your task is")),
    "unknown task"
)
print(f"\nTask: {task_desc}")

current_frame_path = save_frame(frames[0], step=0)
print(f"Step-0 frame -> {current_frame_path}")

init_log(task_desc, env_type)

# -- Main loop -----------------------------------------------------------------

MAX_STEPS = 20

for step in range(1, MAX_STEPS + 1):
    admissible_commands = list(info["admissible_commands"][0])

    print(f"\n{'─' * 72}")
    print(f"Step {step:02d}  |  frame: {current_frame_path}")
    print(f"  Actions ({len(admissible_commands)}): {admissible_commands[:4]}"
          f"{'  ...' if len(admissible_commands) > 4 else ''}")

    chosen_action = llm_choose_action(
        task_desc, obs[0], admissible_commands, current_frame_path, step
    )
    print(f"  -> {chosen_action}")

    # AlfredThorEnv.step returns (obs, None, dones, infos)
    obs, _scores, dones, infos = env.step([chosen_action])
    info = infos

    frames = env.get_frames()
    current_frame_path = save_frame(frames[0], step=step)

    obs_preview = obs[0][:200] + ("..." if len(obs[0]) > 200 else "")
    print(f"  Obs  : {obs_preview}")
    print(f"  Done : {dones[0]}")

    log_step(step, chosen_action, obs[0], dones[0], current_frame_path)

    if dones[0]:
        won   = info.get("won", [False])[0]
        gc_sr = info.get("goal_condition_success_rate", [0.0])[0]
        print(f"\n{'=' * 72}")
        msg = f"Task COMPLETED in {step} steps!" if won else f"Episode ended after {step} steps."
        print(f"{msg}  Goal conditions: {gc_sr:.0%}")
        break

print(f"\nFrames saved : {_FRAMES_DIR}/")
print(f"Game log     : {_LOG_FILE}")
print(f"\nLog query examples:")
print(f"  grep 'ACTION:'   {_LOG_FILE.name}")
print(f"  grep 'DONE:True' {_LOG_FILE.name}")
print(f"  awk '/^## STEP:0003/,/^## STEP:0004/' {_LOG_FILE.name}")
env.close()
