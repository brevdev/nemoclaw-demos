---
name: nemoclaw-wakeup
description: "Host-side scheduled wakeup trigger for NemoClaw. Use when: user asks about wakeup, heartbeat, scheduled tasks, cron, timer, interval, periodic checks, how often agent runs, changing the schedule, what happens on wakeup, or editing WAKEUP.md. This skill explains that the wakeup schedule is controlled by a host-side cron job outside the sandbox and cannot be modified from inside. The agent reads /sandbox/.openclaw-data/workspace/WAKEUP.md for its task instructions on each pulse."
---

# NemoClaw Wakeup

You are being woken by a host-side scheduled trigger called **NemoClaw Wakeup**.
This is NOT a skill you invoke — it is the reason you are running right now.

## Current Schedule

- **Wakeup interval:** every **__INTERVAL__ minutes**
- **Last configured:** __INSTALLED_AT__
- **Controlled by:** host-side cron (outside the sandbox — you cannot change this)

## What just happened

A cron job on the **host machine** (outside the sandbox) fired and sent you a
message. You must now read your task file and follow the instructions inside it.

## Your task file

**Path:** `/sandbox/.openclaw-data/workspace/WAKEUP.md`

Read this file **right now** and follow every instruction in it. Do NOT rely on
memory from previous sessions. The file may have been edited since the last time
you ran.

## What you CAN do

- Read `/sandbox/.openclaw-data/workspace/WAKEUP.md` to get your current instructions
- Edit `/sandbox/.openclaw-data/workspace/WAKEUP.md` when a user asks you to change
  your wakeup tasks (e.g., "add checking my calendar to your wakeup tasks")
- Use any installed skills (gog, planet, brave, etc.) as directed by WAKEUP.md
- Report results in the current session

## What you CANNOT do

**CRITICAL: Do NOT attempt any of the following. They will all fail.**

- Do NOT run `crontab` — it does not exist in the sandbox
- Do NOT try to install cron or any scheduler — you cannot install packages
- Do NOT try to create any timer, scheduler, background process, or daemon
- Do NOT try to modify the wakeup interval from inside the sandbox
- Do NOT try to stop or start the wakeup schedule from inside the sandbox
- Do NOT send Telegram/Discord/Slack messages unless WAKEUP.md explicitly says to
- Do NOT repeat actions from previous sessions — always read the file fresh

## When a user asks to change the schedule

If a user asks you to change how often you wake up (the timer/interval), respond
with the current setting and direct them to the host:

> The wakeup is currently set to trigger every **__INTERVAL__ minutes**.
> This schedule is controlled by a host-side cron job outside this sandbox.
> I cannot change it from here. To modify the interval, run on the host:
>
> ```
> cd ~/nemoclaw-wakeup && ./install.sh --interval <minutes>
> ```
>
> For example, to change to every 30 minutes:
>
> ```
> cd ~/nemoclaw-wakeup && ./install.sh --interval 30
> ```
>
> Or check the current schedule with:
>
> ```
> cd ~/nemoclaw-wakeup && ./install.sh --status
> ```

## When a user asks to change wakeup tasks

If a user asks you to change **what** you do when you wake up, edit the
`/sandbox/.openclaw-data/workspace/WAKEUP.md` file with their requested changes.
Confirm the changes were saved. The next wakeup pulse will use the updated file.
