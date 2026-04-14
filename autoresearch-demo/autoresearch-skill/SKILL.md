---
name: ssh-remote
description: "Run commands on a remote GPU server via MCP. Use this skill whenever the user asks to do anything on the remote machine — training jobs, GPU checks, file operations, Slurm jobs."
---

# Remote Server Access

Run shell commands on the remote server using `/sandbox/bin/mcporter`.
This is a bash command — run it in the terminal. Do NOT install any MCP libraries.

## How to run a command

```bash
/sandbox/bin/mcporter call <alias>.run_shell_command command="<your command here>"
```

That's it. Just run that in the terminal. Examples:

```bash
/sandbox/bin/mcporter call <alias>.run_shell_command command="hostname"
/sandbox/bin/mcporter call <alias>.run_shell_command command="nvidia-smi"
/sandbox/bin/mcporter call <alias>.run_shell_command command="ls -la /home/user"
/sandbox/bin/mcporter call <alias>.run_shell_command command="cd /workspace && python train.py --lr 0.001"
```

## Other available tools

All called the same way — `/sandbox/bin/mcporter call <alias>.<tool> <args>`:

| Tool | What it does |
|------|-------------|
| `run_shell_command` | Run any shell command |
| `get_gpu_availability` | Check free GPUs |
| `get_cluster_status` | Slurm partitions and nodes |
| `submit_job` | Submit Slurm batch job |
| `list_jobs` | List running/pending jobs |
| `get_job_details` | Job details by ID |
| `cancel_job` | Cancel a job |
| `list_directory` | List remote directory |
| `read_file` | Read a remote file |
| `write_file` | Write a remote file |
| `find_files` | Search for files |

## Important

- `mcporter` is already installed at `/sandbox/bin/mcporter` — do NOT install anything
- Run it as a bash command in the terminal — it is NOT a Python library
- Timeout: 120s — for long jobs use `submit_job` instead of `run_shell_command`

## MANDATORY: Before Slurm jobs

Before submitting ANY Slurm job, you MUST ask the user:
1. Which partition(s) can I use?
2. How many concurrent jobs am I allowed to launch?
3. What is the maximum time limit per job?
4. What GPU type/count should I request?

Do NOT assume you have unlimited cluster access.
