#!/usr/bin/env python3
"""Install image-baked OpenClaw assets for the healthcare monitor sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


PROJECT = Path("/opt/healthcare-monitor-demo")
OPENCLAW = Path("/sandbox/.openclaw")
CONFIG = OPENCLAW / "openclaw.json"
CONFIG_HASH = OPENCLAW / ".config-hash"
MODEL_REF = os.environ.get(
    "HEALTHCARE_AGENT_MODEL",
    "inference/nvidia/nemotron-3-super-120b-a12b",
)
MODEL_ID = MODEL_REF.removeprefix("inference/")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def replace_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_placeholders(child) for key, child in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(child) for child in value]
    if value == "__MODEL_REF__":
        return MODEL_REF
    if value == "__MODEL_ID__":
        return MODEL_ID
    return value


def deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return patch


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def ensure_agent_workspace(agent_id: str) -> Path:
    workspace = OPENCLAW / f"workspace-{agent_id}"
    workspace.mkdir(parents=True, exist_ok=True)
    memory = workspace / "memory"
    memory.mkdir(exist_ok=True)
    for name in ["AGENTS.md", "TOOLS.md", "SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md"]:
        path = workspace / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    return workspace


def main() -> int:
    OPENCLAW.mkdir(parents=True, exist_ok=True)

    copy_tree(PROJECT / "skills", OPENCLAW / "skills")
    copy_tree(PROJECT / "data", OPENCLAW / "workspace" / "data")
    copy_tree(PROJECT / "workspace" / "scripts", OPENCLAW / "workspace" / "scripts")
    copy_tree(PROJECT / "openclaw-cron", OPENCLAW / "cron")

    for source in sorted((PROJECT / "workspaces").iterdir()):
        if source.is_dir():
            workspace = ensure_agent_workspace(source.name)
            for path in source.iterdir():
                if path.is_file():
                    shutil.copy2(path, workspace / path.name)

    base = load_json(CONFIG)
    patch = replace_placeholders(load_json(PROJECT / "openclaw.json"))
    merged = deep_merge(base, patch)
    CONFIG.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    digest = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    CONFIG_HASH.write_text(f"{digest}  openclaw.json\n", encoding="utf-8")

    os.system("chown -R sandbox:sandbox /sandbox/.openclaw")
    os.system("chown root:root /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash")
    os.system("chmod 444 /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash")
    os.system("find /sandbox/.openclaw/skills /sandbox/.openclaw/workspace /sandbox/.openclaw/workspace-* /sandbox/.openclaw/cron -type d -exec chmod 755 {} +")
    os.system("find /sandbox/.openclaw/skills /sandbox/.openclaw/workspace /sandbox/.openclaw/workspace-* /sandbox/.openclaw/cron -type f -exec chmod 644 {} +")
    os.system("chmod 755 /sandbox/.openclaw/workspace/scripts/*.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
