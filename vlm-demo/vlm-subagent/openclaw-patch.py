"""
Patch openclaw.json to add the Omni vision sub-agent.

Adds:
- nvidia-omni provider (direct NVIDIA API, bypasses Privacy Router)
- agents.list with main + vision-operator
- Sub-agent timeout/concurrency defaults

Usage:
    cat openclaw.json | python3 openclaw-patch.py <NVIDIA_API_KEY> > patched.json
"""
import json, sys

if len(sys.argv) < 2:
    print("Usage: python3 openclaw-patch.py <NVIDIA_API_KEY> < openclaw.json", file=sys.stderr)
    sys.exit(1)

config = json.load(sys.stdin)
api_key = sys.argv[1]

# Add the nvidia-omni provider (bypasses Privacy Router, calls NVIDIA API directly)
config["models"]["providers"]["nvidia-omni"] = {
    "baseUrl": "https://integrate.api.nvidia.com/v1",
    "apiKey": api_key,
    "api": "openai-completions",
    "models": [
        {
            "id": "private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b",
            "name": "nvidia-omni/private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b",
            "reasoning": True,
            "input": ["text", "image"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 131072,
            "maxTokens": 16384
        }
    ]
}

# Set sub-agent defaults
config["agents"]["defaults"]["subagents"] = {
    "maxConcurrent": 4,
    "maxSpawnDepth": 1
}
config["agents"]["defaults"]["timeoutSeconds"] = 300

# Define the two-agent system
config["agents"]["list"] = [
    {
        "id": "main",
        "model": {"primary": "inference/nvidia/nemotron-3-super-120b-a12b"},
        "subagents": {"allowAgents": ["vision-operator"]},
        "tools": {"profile": "full"}
    },
    {
        "id": "vision-operator",
        "model": {"primary": "nvidia-omni/private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b"},
        "tools": {
            "profile": "full",
            "deny": ["message", "sessions_spawn"]
        }
    }
]

json.dump(config, sys.stdout, indent=2)
