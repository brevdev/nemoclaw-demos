"""
Script subprocess executor for InvestorClaw.

Selects the appropriate Python interpreter (skill venv if present, otherwise
the current executable) and runs the target script with a controlled cwd.
Emits an ic_result verification envelope after each invocation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List


def run_script(
    script_path: Path,
    args: List[str],
    env: Dict[str, str],
    cwd: Path,
) -> int:
    """
    Execute *script_path* as a subprocess and return its exit code.

    Args:
        script_path: Absolute path to the Python script to run.
        args:        Argument list (without the interpreter or script name).
        env:         Full environment dict for the subprocess.
        cwd:         Working directory for the subprocess (the skill directory).
    """
    venv_python = cwd / "venv" / "bin" / "python3"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    started = time.perf_counter()
    original_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        result = subprocess.run(
            [python_exe, str(script_path)] + list(args),
            check=False,
            env=env,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        print(json.dumps({
            "ic_result": {
                "script": script_path.name,
                "exit_code": result.returncode,
                "duration_ms": duration_ms,
            }
        }))
        return result.returncode
    finally:
        os.chdir(original_cwd)
