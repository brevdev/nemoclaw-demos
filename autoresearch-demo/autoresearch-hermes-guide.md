# Autonomous AI Research Agent for NemoClaw

This guide turns a NemoClaw + Hermes sandbox into an autonomous AI research agent that can run experiments on a remote GPU machine, manage Slurm jobs, and write papers — all from inside the sandbox. The agent follows Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) loop: modify code → run experiment → evaluate → keep or discard → repeat forever.

The remote machine is connected via [slurm-mcp](https://github.com/yidong72/slurm_mcp), a Python MCP server that provides 34 tools for SSH, Slurm job management, and file operations. The SSH key **never enters the sandbox** — it stays on the host where the MCP server runs.

## What's in this directory

| File | Purpose |
|------|---------|
| `setup.sh` | One-command installer: MCP bridge + agent persona + research skills |
| `ssh-skill/bootstrap.sh` | Sets up mcp-proxy → slurm-mcp on host, mcporter + policy + skill in sandbox |
| `ssh-skill/setup.sh` | Re-deploy shortcut after sandbox reset |
| `ssh-skill/policy.yaml` | Reference network policy (applied automatically by bootstrap) |
| `SOUL.md` | Agent instructions: autoresearch loop, MCP commands, Slurm safety rules |
| `USER.md` | User profile (edit for your environment) |
| `MEMORY.md` | Agent memory: builder info, MCP usage, paper writing reference |
| `IDENTITY.md` | Agent identity |
| `AGENTS.md` | Host setup documentation and architecture |

## How it works

The connection follows the same pattern as the [Blender MCP demo](https://github.com/brevdev/nemoclaw-demos/tree/main/blender-demo), adapted for remote SSH/Slurm:

```
Host (your Mac or Linux box)
│
├── mcp-proxy (HTTP/SSE on port 9878)
│   └── slurm-mcp (Python, asyncssh)
│       ├── Holds your SSH key (never enters sandbox)
│       ├── Connects to remote GPU machine
│       └── Exposes 34 MCP tools (shell, Slurm, files)
│
└── NemoClaw sandbox (Hermes agent)
    ├── mcporter → HTTP/SSE → mcp-proxy (through L7 proxy)
    ├── ssh-remote skill (teaches agent how to call mcporter)
    ├── research skills (arxiv, paper writing — from Hermes upstream)
    ├── mlops skills (training, inference, eval — from Hermes upstream)
    └── SOUL.md (autoresearch loop instructions)
```

The sandbox L7 proxy enforces the network policy — the agent can only reach the mcp-proxy endpoint you approved. All other egress is blocked.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running NemoClaw sandbox | A working Hermes sandbox. See [NemoClaw hello-world setup](https://github.com/NVIDIA/NemoClaw). |
| Remote GPU machine | Any Linux machine with SSH access (your GPU server, Slurm cluster, etc.) |
| SSH key | A key pair where the public key is in `~/.ssh/authorized_keys` on the remote machine |
| uv / uvx | `pip install uv` or `brew install uv` — runs slurm-mcp and mcp-proxy (Python) |
| Node.js | `brew install node` — mcporter inside the sandbox needs it |

## Part 1: Install NemoClaw (if not already done)

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

Create a sandbox:

```bash
nemoclaw onboard
```

When prompted, choose your inference provider and name the sandbox (e.g. `research`).

## Part 2: Clone This Repo

```bash
git clone <this-repo-url> ~/Development/autoresearch-agent
cd ~/Development/autoresearch-agent
```

Edit `USER.md` with your details (name, SSH username, remote machine IP).

## Part 3: Run Setup

The `setup.sh` script does everything in one command:

1. **Slurm/SSH MCP bridge** — starts mcp-proxy + slurm-mcp on the host, installs mcporter in sandbox, applies network policy, uploads the ssh-remote skill
2. **Agent persona** — uploads SOUL.md, USER.md, MEMORY.md into the Hermes agent's memory
3. **Research skills** — fetches the latest research and mlops skills from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/main/skills)

```bash
./setup.sh \
  --sandbox research \
  --alias builder=192.168.1.149 \
  --key ~/.ssh/id_ed25519 \
  --user marcelo
```

Replace:
- `research` — your sandbox name
- `builder=192.168.1.149` — a friendly name and the IP of your GPU machine
- `~/.ssh/id_ed25519` — path to your SSH private key
- `marcelo` — your SSH username on the remote machine

If your remote machine uses password authentication instead of a key:

```bash
./setup.sh \
  --sandbox research \
  --alias cluster=login.hpc.example.com \
  --password "your-password" \
  --user jsmith
```

You should see output ending with:

```
=== Slurm/SSH MCP ready ===

  Sandbox:    research
  Target:     builder (192.168.1.149)
  MCP proxy:  localhost:9878 (pid 55744)
  Tools:      34 (Slurm + SSH + files)
  SSH key:    ON HOST ONLY
```

## Part 4: Verify

From inside the sandbox (via `nemoclaw research connect` or the Hermes chat), the agent can now run commands on the remote machine:

```bash
# Test from host (verifies end-to-end)
openshell sandbox exec -n research -- \
  /sandbox/bin/mcporter call builder.run_shell_command command="hostname"
```

Expected output:
```json
{
  "result": "builder\n"
}
```

## Part 5: Use It

Open the Hermes chat and try:

- *"Check GPU availability on builder"*
- *"Run `nvidia-smi` on builder"*
- *"Search arxiv for recent papers on mixture of experts"*
- *"Set up an autoresearch loop on builder to optimize train.py"*

The agent will use `/sandbox/bin/mcporter call builder.<tool>` to execute commands remotely. The SOUL.md instructs it to:

1. **Always ask before Slurm jobs** — which partitions, how many concurrent jobs, max time limit
2. **Follow the autoresearch loop** — modify → run → evaluate → keep/discard → repeat
3. **Never stop** — runs autonomously until you interrupt it
4. **Use the paper-writing skill** when you ask for a writeup (NeurIPS, ICML, ICLR templates)

## Available MCP Tools

The agent has 34 tools for the remote machine:

| Category | Tools |
|----------|-------|
| **Shell** | `run_shell_command` |
| **Cluster** | `get_cluster_status`, `get_partition_info`, `get_node_info`, `get_gpu_info`, `get_gpu_availability` |
| **Jobs** | `submit_job`, `list_jobs`, `get_job_details`, `cancel_job`, `hold_job`, `release_job`, `get_job_history` |
| **Interactive** | `start_interactive_session`, `exec_in_session`, `list_interactive_sessions`, `end_interactive_session`, `get_interactive_session_info` |
| **Profiles** | `save_interactive_profile`, `list_interactive_profiles`, `start_session_from_profile` |
| **Files** | `list_directory`, `list_datasets`, `list_model_checkpoints`, `list_job_logs`, `read_file`, `write_file`, `find_files`, `delete_file`, `get_disk_usage`, `get_cluster_directories` |
| **Containers** | `list_container_images`, `validate_container_image` |

All called as: `/sandbox/bin/mcporter call builder.<tool> <args>`

## Re-deploy After Reboot

The mcp-proxy runs as a host process — it stops when you reboot. To restart:

```bash
cd ~/Development/autoresearch-agent
./ssh-skill/setup.sh research \
  --alias builder=192.168.1.149 \
  --key ~/.ssh/id_ed25519 \
  --user marcelo
```

## Stopping the MCP Proxy

```bash
kill $(cat ~/.local/state/nemoclaw-ssh-skill/mcp-proxy.pid)
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `mcporter: command not found` | Use full path: `/sandbox/bin/mcporter` |
| Agent tries to install MCP libraries | The SOUL.md tells it not to. If it still does, tell it directly: "Run `/sandbox/bin/mcporter call builder.run_shell_command command='hostname'`" |
| `l7_decision=deny` in `openshell logs` | Policy doesn't match. Run `openshell policy get --full research` and check the `ssh_mcp` block has the correct host IP and port. |
| `EHOSTUNREACH` from mcp-proxy | On macOS: Node.js may be blocked by the firewall. slurm-mcp uses Python (asyncssh) which is typically allowed. Check: `python3 -c "import socket; s = socket.create_connection(('YOUR_IP', 22), timeout=5); print('OK'); s.close()"` |
| `SSH connection error` | Verify from host: `ssh -i ~/.ssh/id_ed25519 marcelo@192.168.1.149 hostname`. If that works, restart mcp-proxy. |
| mcp-proxy died | Check log: `tail ~/.local/state/nemoclaw-ssh-skill/mcp-proxy.log`. Restart: `./ssh-skill/setup.sh research --alias builder=192.168.1.149 --key ~/.ssh/id_ed25519 --user marcelo` |
| Agent ignores SOUL.md | Hermes reads from `/sandbox/.hermes-data/memories/SOUL.md`. Re-upload: `openshell sandbox upload research SOUL.md /sandbox/.hermes-data/memories/` |

## Security Model

- **SSH key isolation**: The private key stays on the host inside the mcp-proxy process. The agent in the sandbox calls MCP tools over HTTP — it never sees, reads, or handles the key.
- **Network policy**: The sandbox can only reach the mcp-proxy's HTTP endpoint (one IP + port). All other egress is denied by default.
- **L7 proxy**: OpenShell's proxy inspects and enforces all traffic. The `access: full` policy grants HTTP forwarding to the mcp-proxy, not raw TCP to arbitrary hosts.
- **Slurm safety**: The SOUL.md instructs the agent to always ask for partition/quota confirmation before submitting jobs. This is an instruction-level guard, not a technical one — the MCP tools themselves don't enforce limits.

## How It Compares to the Blender Demo

This setup follows the exact same MCP-over-HTTP pattern as the [NemoClaw Blender demo](https://github.com/brevdev/nemoclaw-demos/tree/main/blender-demo):

| | Blender Demo | This (AI Research) |
|---|---|---|
| MCP server | blender-mcp (3D commands) | slurm-mcp (SSH + Slurm + files) |
| Bridge | mcp-proxy → Blender addon (TCP) | mcp-proxy → asyncssh → remote machine |
| Setup | Manual (8 copy-paste steps) | Automated (`./setup.sh`) |
| Agent | OpenClaw | Hermes |
| Credential | None | SSH key (host-only) |
| Tools | 11 | 34 |
| Autonomy | Interactive | Autonomous loop (autoresearch) |
