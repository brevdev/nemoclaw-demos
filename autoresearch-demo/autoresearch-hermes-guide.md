# Connecting a Slurm Cluster to Hermes in a NemoClaw Sandbox

This guide connects a remote Slurm cluster to a Hermes agent running inside a NemoClaw sandbox. By the end, the agent can submit jobs, monitor GPU availability, manage files, and run shell commands on the cluster — all through MCP tools from inside the sandbox.

The connection uses [slurm-mcp](https://github.com/yidong72/slurm_mcp), a Python MCP server that provides 34 tools for Slurm job management, SSH, and file operations. The agent follows Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) pattern: modify code, run experiment, evaluate, keep or discard, repeat.

The SSH key **never enters the sandbox** — it stays on the host where the MCP server runs.

> **Note:** This guide targets Slurm clusters. If your remote machine does not have Slurm (e.g. a single GPU workstation), the `run_shell_command`, `read_file`, `write_file`, and file tools still work — the Slurm-specific tools (`submit_job`, `get_gpu_availability`, etc.) will simply return errors and can be ignored.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Running NemoClaw sandbox | A working Hermes sandbox. See [NemoClaw hello-world setup](https://github.com/NVIDIA/NemoClaw). |
| Slurm cluster with SSH access | A login node you can SSH into (e.g. `login.hpc.example.com`) |
| SSH key or password | Credentials for the cluster login node |
| uv / uvx | `pip install uv` or `brew install uv` — runs slurm-mcp and mcp-proxy (Python) |
| Node.js | `brew install node` — mcporter inside the sandbox needs it |

## What's in this directory

| File | Purpose |
|------|---------|
| `autoresearch-hermes-guide.md` | This guide |
| `setup.sh` | One-command installer: MCP bridge + agent persona + research skills |
| `bootstrap.sh` | Sets up mcp-proxy + slurm-mcp on host, mcporter + policy + skill in sandbox |
| `policy.yaml` | Reference network policy (applied automatically by bootstrap) |
| `autoresearch-skill/SKILL.md` | Teaches the agent how to call mcporter (bash commands, not Python) |
| `autoresearch-skill/SOUL.md` | Agent instructions: autoresearch loop, Slurm safety rules |
| `autoresearch-skill/USER.md` | User profile template (edit for your environment) |
| `autoresearch-skill/MEMORY.md` | Agent memory: cluster info, MCP usage, paper writing reference |

## How it works

The connection follows the same MCP-over-HTTP pattern as the [Blender demo](https://github.com/brevdev/nemoclaw-demos/tree/main/blender-demo):

```
Host (your Mac or Linux box)
│
├── mcp-proxy (HTTP/SSE on port 9878)
│   └── slurm-mcp (Python, asyncssh)
│       ├── Holds your SSH key (never enters sandbox)
│       ├── Connects to Slurm login node via SSH
│       └── Exposes 34 MCP tools (Slurm, shell, files)
│
└── NemoClaw sandbox (Hermes agent)
    ├── mcporter → HTTP/SSE → mcp-proxy (through L7 proxy)
    ├── ssh-remote skill (teaches agent how to call mcporter)
    ├── research skills (arxiv, paper writing — from Hermes upstream)
    ├── mlops skills (training, inference, eval — from Hermes upstream)
    └── SOUL.md (autoresearch loop + Slurm safety rules)
```

The sandbox L7 proxy enforces the network policy — the agent can only reach the mcp-proxy endpoint you approved. All other egress is blocked.

## Part 1: Install NemoClaw (if not already done)

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

Create a Hermes sandbox (note the `--agent hermes` flag — this is required, the default is OpenClaw):

```bash
nemoclaw onboard --agent hermes
```

When prompted, choose your inference provider and name the sandbox (e.g. `research`).

> **Important:** This demo requires the Hermes agent, not OpenClaw. The skill paths, memory locations, and mcporter setup are all Hermes-specific. If you already have a sandbox running OpenClaw, create a new one with `--agent hermes`.

## Part 2: Clone This Repo

```bash
cd <nemoclaw-demos-repo>/autoresearch-demo
```

Edit `autoresearch-skill/USER.md` with your details (name, role, cluster info).

## Part 3: Run Setup

The `setup.sh` script does everything in one command:

1. **Slurm MCP bridge** — starts mcp-proxy + slurm-mcp on the host, installs mcporter in sandbox, applies network policy, uploads the ssh-remote skill
2. **Agent persona** — uploads SOUL.md, USER.md, MEMORY.md into the Hermes agent's memory
3. **Research skills** — fetches the latest research and mlops skills from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/main/skills)

### Slurm cluster with SSH key:

```bash
./setup.sh \
  --sandbox research \
  --alias cluster=login.hpc.example.com \
  --key ~/.ssh/id_ed25519 \
  --user jsmith \
  --user-root /lustre/users/jsmith
```

### Slurm cluster with password:

```bash
./setup.sh \
  --sandbox research \
  --alias cluster=login.hpc.example.com \
  --password "your-password" \
  --user jsmith \
  --user-root /lustre/users/jsmith
```

Replace:
- `research` — your sandbox name
- `cluster=login.hpc.example.com` — a friendly alias and the login node hostname or IP
- `~/.ssh/id_ed25519` — path to your SSH private key
- `jsmith` — your cluster username
- `/lustre/users/jsmith` — your home/root directory on the cluster (used by slurm-mcp for directory tools)

You should see output ending with:

```
=== Slurm/SSH MCP ready ===

  Sandbox:    research
  Target:     cluster (login.hpc.example.com)
  MCP proxy:  localhost:9878 (pid XXXXX)
  Tools:      34 (Slurm + SSH + files)
  SSH key:    ON HOST ONLY
```

## Part 4: Verify

Test the MCP connection from the host:

```bash
openshell sandbox exec -n research -- \
  /sandbox/bin/mcporter call cluster.run_shell_command command="hostname"
```

Expected output:
```json
{
  "result": "login01.hpc.example.com\n"
}
```

Test Slurm access:
```bash
openshell sandbox exec -n research -- \
  /sandbox/bin/mcporter call cluster.get_cluster_status
```

## Part 5: Use It

Open the Hermes chat and try:

- *"What GPUs are available on the cluster?"*
- *"Submit a training job on partition gpu with 4 GPUs, time limit 2 hours"*
- *"List my running jobs"*
- *"Search arxiv for recent papers on mixture of experts"*
- *"Set up an autoresearch loop to optimize train.py on the cluster"*

The agent uses `/sandbox/bin/mcporter call cluster.<tool>` to execute commands remotely. The SOUL.md instructs it to:

1. **Always ask before Slurm jobs** — which partition(s), how many concurrent jobs, max time limit, GPU count
2. **Follow the autoresearch loop** — modify → run → evaluate → keep/discard → repeat
3. **Never stop** — runs autonomously until you interrupt it
4. **Use the paper-writing skill** when you ask for a writeup (NeurIPS, ICML, ICLR, ACL, AAAI, COLM templates)

## Available MCP Tools

The agent has 34 tools for the remote cluster:

| Category | Tools |
|----------|-------|
| **Shell** | `run_shell_command` |
| **Cluster** | `get_cluster_status`, `get_partition_info`, `get_node_info`, `get_gpu_info`, `get_gpu_availability` |
| **Jobs** | `submit_job`, `list_jobs`, `get_job_details`, `cancel_job`, `hold_job`, `release_job`, `get_job_history` |
| **Interactive** | `start_interactive_session`, `exec_in_session`, `list_interactive_sessions`, `end_interactive_session`, `get_interactive_session_info` |
| **Profiles** | `save_interactive_profile`, `list_interactive_profiles`, `start_session_from_profile` |
| **Files** | `list_directory`, `list_datasets`, `list_model_checkpoints`, `list_job_logs`, `read_file`, `write_file`, `find_files`, `delete_file`, `get_disk_usage`, `get_cluster_directories` |
| **Containers** | `list_container_images`, `validate_container_image` |

All called as: `/sandbox/bin/mcporter call cluster.<tool> <args>`

## Re-deploy After Reboot

The mcp-proxy runs as a host process — it stops when you reboot. To restart:

```bash
cd <nemoclaw-demos-repo>/autoresearch-demo
./bootstrap.sh --sandbox research \
  --alias cluster=login.hpc.example.com \
  --key ~/.ssh/id_ed25519 \
  --user jsmith \
  --user-root /lustre/users/jsmith
```

## Stopping the MCP Proxy

```bash
kill $(cat ~/.local/state/nemoclaw-ssh-skill/mcp-proxy.pid)
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `mcporter: command not found` | Use full path: `/sandbox/bin/mcporter` |
| Agent tries to install MCP libraries | The SKILL.md tells it not to. Tell the agent: "Run `/sandbox/bin/mcporter call cluster.run_shell_command command='hostname'`" |
| `l7_decision=deny` in `openshell logs` | Policy doesn't match. Run `openshell policy get --full research` and check the `ssh_mcp` block has the correct host IP and port. |
| `EHOSTUNREACH` from mcp-proxy | On macOS: Node.js may be blocked by the firewall. slurm-mcp uses Python (asyncssh) which is typically allowed. Check: `python3 -c "import socket; s = socket.create_connection(('<HOST>', 22), timeout=5); print('OK'); s.close()"` |
| `SSH connection error` | Verify from host: `ssh -i ~/.ssh/id_ed25519 jsmith@login.hpc.example.com hostname`. If that works, restart mcp-proxy. |
| mcp-proxy died | Check log: `tail ~/.local/state/nemoclaw-ssh-skill/mcp-proxy.log`. Re-run `bootstrap.sh`. |
| Slurm tools return errors | If the remote machine has no Slurm, this is expected. The shell and file tools still work. |

## Security Model

- **SSH key isolation**: The private key stays on the host inside the mcp-proxy process. The agent calls MCP tools over HTTP — it never sees or handles the key.
- **Network policy**: The sandbox can only reach the mcp-proxy's HTTP endpoint (one IP + port). All other egress is denied by default.
- **L7 proxy**: OpenShell's proxy inspects and enforces all traffic. The `access: full` policy grants HTTP forwarding to the mcp-proxy, not raw TCP to arbitrary hosts.
- **Slurm safety**: The SOUL.md instructs the agent to always ask for partition/quota confirmation before submitting jobs. This is an instruction-level guard — the MCP tools themselves do not enforce limits.
