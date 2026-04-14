# Memory

## Infrastructure

- **Remote machine:** (configured by setup.sh — alias and IP filled in automatically)
- **Access:** MCP via `/sandbox/bin/mcporter call <alias>.<tool>`
- **Tools:** 34 Slurm/SSH tools (run_shell_command, submit_job, get_gpu_availability, read_file, write_file, etc.)

## How to run commands on the remote machine

```bash
/sandbox/bin/mcporter call <alias>.run_shell_command command="<command>"
```

This is a bash command. Run it in the terminal. Do NOT install any MCP or SSH libraries.

## Autoresearch pattern

Based on Karpathy's autoresearch (https://github.com/karpathy/autoresearch):
- Modify code → run experiment → evaluate metric → keep or discard → repeat
- Fixed time budget per experiment for fair comparison
- Log everything to results.tsv
- Never stop — run autonomously until interrupted

## Paper writing

Use the Hermes research-paper-writing skill for the full pipeline:
- Literature review (arxiv search)
- Experiment design and execution (on remote machine)
- Analysis and visualization
- LaTeX drafting (NeurIPS, ICML, ICLR, ACL, AAAI, COLM templates)
- Self-review and revision
