# NemoClaw Wakeup

A host-controlled scheduled trigger that periodically wakes the OpenClaw agent inside an OpenShell sandbox to execute a configurable task list. The agent reads its instructions from `WAKEUP.md` inside the sandbox and can modify its own task list when users interact with it — but the **schedule itself is locked down** and controlled entirely from the host, outside the sandbox.

This architecture leverages OpenShell's security model:

- **The agent cannot schedule itself.** OpenShell sandboxes have no cron, no init system, no background processes, and no self-triggering capability. The agent is purely reactive — it only runs when an external trigger fires.
- **The agent cannot escape the sandbox.** All network egress is policy-enforced. The agent can only reach approved endpoints through the OpenShell gateway.
- **The host controls the timer.** The cron schedule runs outside the sandbox and cannot be modified by the agent. If the agent is compromised or misbehaves, it cannot increase its own execution frequency or persist beyond its session.

---

## Quick Start

```bash
git clone https://github.com/brevdev/nemoclaw-demos.git
cd nemoclaw-demos/wakeup-demo
./install.sh
```

The installer will:
1. Detect your sandbox (or let you choose)
2. Verify SSH connectivity to the sandbox
3. Ask how often to wake the agent (5, 10, 15, 30, 60 min, or custom)
4. Deploy the NemoClaw Wakeup skill into the sandbox
5. Seed a default `WAKEUP.md` if one doesn't exist
6. Create the cron job

---

## How It Works

```
+--- Host (cron) ----------------+     +--- Sandbox (OpenShell) ----------------------+
|                                 |     |                                               |
|  every N minutes:               |     |  /sandbox/.openclaw-data/workspace/WAKEUP.md       |
|    SSH into sandbox (~400ms) ---|---->|    "Check my email and summarize..."          |
|    fire: openclaw agent         |     |                                               |
|    unique session ID            |     |  Agent reads file fresh, follows instructions  |
|    flock prevents overlap       |     |  Uses skills (gog, planet, brave, etc.)       |
|                                 |     |                                               |
+---------------------------------+     +-----------------------------------------------+
```

Each pulse:
1. Acquires an exclusive lock (flock) — if the previous pulse is still running, this one skips
2. Generates a unique session ID (`wakeup-<timestamp>-<pid>`) — no context bleed between pulses
3. SSHs into the sandbox via `openshell ssh-proxy` (~400ms)
4. Sends one message to the agent: **"Read WAKEUP.md and follow the instructions"**
5. The agent reads the file fresh, executes, and the session ends

---

## Changing What the Agent Does

Tell the agent to update its wakeup tasks. You never need to touch the cron job or reinstall.

### Via TUI or Telegram (recommended)

Connect to your sandbox and tell the agent:

```
Update my nemoclaw wakeup to check my email and respond to anything from boss@company.com
```

```
Add an auto-reply rule to my nemoclaw wakeup:
Reply to emails from boss@company.com confirming I received the message
```

```
Show me what my nemoclaw wakeup is currently set to do
```

```
Update my nemoclaw wakeup to also check my Google Calendar and warn me about
conflicts in the next 2 hours
```

### Manual editing (optional)

The install script handles deploying `WAKEUP.md` automatically. If you prefer to edit it manually:

```bash
# SSH into sandbox
openshell sandbox connect <sandbox-name>
nano /sandbox/.openclaw-data/workspace/WAKEUP.md

# Or upload from host
openshell sandbox upload <sandbox-name> ~/my-wakeup.md /sandbox/.openclaw-data/workspace/WAKEUP.md
```

---

## Changing the Schedule

The timer is controlled by the host cron job, not by the agent. The agent knows this and will direct users to run these commands if asked.

```bash
# Change interval
./install.sh --interval 30

# Check current status
./install.sh --status
```

---

## Commands

| Command | Description |
|---|---|
| `./install.sh` | Install (interactive) |
| `./install.sh my-sandbox --interval 15` | Install with flags |
| `./install.sh --status` | Show current status |
| `./install.sh --interval 30` | Change interval |
| `./install.sh --uninstall` | Remove everything |
| `~/.nemoclaw/wakeup/wakeup.sh` | Test manually |
| `tail -f ~/.nemoclaw/wakeup/wakeup.log` | Watch logs |

---

## File Structure

```
~/.nemoclaw/wakeup/
├── wakeup.sh       # Script that cron runs (SSH trigger)
├── config.env      # Settings (sandbox name, interval, openshell path)
├── wakeup.lock     # flock file (prevents overlapping runs)
└── wakeup.log      # Output log (auto-rotated at 1000 lines)

Inside the sandbox:
/sandbox/.openclaw-data/workspace/
└── WAKEUP.md                          # Agent reads this for instructions
/sandbox/.openclaw-data/skills/nemoclaw-wakeup/
└── SKILL.md                           # Agent skill (knows it can't modify timer)
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `openshell: command not found` | Installer auto-detects. Check `which openshell`. |
| SSH test fails | Is the sandbox running? `openshell sandbox list` |
| Agent doesn't do anything | Edit `WAKEUP.md` with clearer instructions. |
| Agent sends Telegram messages | Add "Do NOT send Telegram messages" to WAKEUP.md rules. |
| Log shows SKIP | Previous pulse still running. Increase interval or simplify tasks. |
| Cron not firing (WSL) | Run `sudo service cron start` after opening WSL. |

---

## Compatibility

Works on **WSL**, **Brev**, and any Linux host with SSH. Uses `openshell ssh-proxy` for connectivity.

> **WSL note:** Cron may not start automatically. Run `sudo service cron start` after opening WSL.

---

Created by **Tim Klawa** (tklawa@nvidia.com)
