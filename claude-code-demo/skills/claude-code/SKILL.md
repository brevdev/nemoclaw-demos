---
name: claude-code
description: "ALWAYS use this skill when a user asks to: build an app, create a project, write code, code something, make a website, create an API, scaffold a codebase, generate a CLI tool, fix code, refactor code, write tests, build with Claude Code, use Claude Code, continue a coding project, update a project, check build status, list projects, show my projects, what did you build, push to GitHub, create a PR, deploy code, or ANY software development task. This skill delegates to Claude Code — a professional coding agent. Do NOT attempt to write code yourself. Do NOT create files in your workspace. ALWAYS delegate coding tasks to Claude Code via the runner script."
metadata: { "openclaw": { "emoji": "🔨", "requires": { "bins": ["node", "bash"] } } }
---

# Claude Code — Sandboxed Coding Agent

You have access to **Claude Code**, a professional coding agent that builds
complete applications. It runs via a runner script inside your sandbox.

## RULE 1: NEVER write code yourself — ALWAYS use Claude Code

When a user asks you to build, create, code, or develop ANYTHING:

- **DO NOT** write code files yourself
- **DO NOT** create projects in your workspace (`/sandbox/.openclaw-data/workspace/`)
- **DO NOT** use your own tools to scaffold, write, or generate code
- **ALWAYS** delegate to Claude Code via the runner script below
- Claude Code is a **much better coder** than you — let it do the work

This applies to ALL coding requests including:
- "Build me an app"
- "Create a website"
- "Write a script"
- "Make an API"
- "Code a tool"
- "Create a project"
- Any variation of asking you to produce code

## RULE 2: Start the build, acknowledge, and end your turn

Use `--background` to start the build and **end your turn immediately** so the
user is free to send other messages or talk about other things while it builds.

The runner script automatically notifies the user through the gateway when the
build finishes — you don't need to poll or wait.

**Workflow:**

1. Start Claude Code in **background** mode.
2. Reply with an acknowledgment: "I've kicked off Claude Code to build
   `<project>`. I'll let you know when it's done — you can keep chatting
   in the meantime."
3. **End your turn.** Do NOT poll. Do NOT loop. The runner handles the rest.

The runner's background watcher will automatically send a message through the
gateway when the build completes, routed to the user's current channel.

## RULE 3: Pass the user's request through faithfully

Your job is to relay the user's intent to Claude Code — **not** to invent
the project for them. Claude Code is the coder; let it choose the stack,
the features, and the design based on what the user actually asked for.

**Only add these structural requirements to every prompt** (things any
project should have regardless of what it is):

1. Initialize a git repo with a `.gitignore` appropriate to the stack Claude Code picks.
2. Include a `README.md` with the project name, a short description, how
   to run it, and the tech stack that was used.
3. Use a clean project structure (organized directories, not everything
   in the root).

**Do NOT add** any of the following unless the user explicitly said so:

- Languages, frameworks, or libraries (no "React", "Vite", "Tailwind",
  "FastAPI", etc. — let Claude Code decide)
- Features the user didn't ask for (no "local storage persistence",
  "keyboard shortcuts", "dark mode", "categories", etc.)
- UI/UX opinions ("modern", "responsive", "accessible", "animations")
- Testing, linting, CI, or deployment choices

If the request is ambiguous, Claude Code will pick something reasonable
or ask — don't resolve it on its behalf.

**Example:**

User says: "Build me a todo app"

Your prompt to Claude Code:
> Build a todo app. Initialize a git repo with a `.gitignore`. Include
> a `README.md` with the project name, description, how to run it, and
> the tech stack used. Use a clean project structure.

If the user gave more detail ("build me a CLI todo app in Python," "make
a React shopping list with dark mode"), preserve that detail verbatim and
just append the same structural requirements.

## How to start a build

```bash
/sandbox/.config/claude-code/claude-runner.sh --background \
  --project <name> \
  --prompt '<user request verbatim + structural requirements from RULE 3>'
```

## How to check status (when the user asks)

```bash
/sandbox/.config/claude-code/claude-runner.sh --status <project>
```

Check all builds:

```bash
/sandbox/.config/claude-code/claude-runner.sh --status-all
```

## How to see what was built

```bash
/sandbox/.config/claude-code/claude-runner.sh --result <project>
```

---

## Project management

These commands let the user ask about, update, and manage Claude Code projects.

### List all projects

When the user asks "what projects do I have", "list my projects", "show builds":

```bash
ls -la /sandbox/claude-projects/
```

Report each project name and whether it has a README.

### Show project details

When the user asks "show me the todo-app" or "what's in my project":

```bash
/sandbox/.config/claude-code/claude-runner.sh --result <project>
cat /sandbox/claude-projects/<project>/README.md 2>/dev/null
```

### Update / continue an existing project

When the user asks "update my todo-app" or "add dark mode to the calculator":

```bash
/sandbox/.config/claude-code/claude-runner.sh --background \
  --project <existing-project-name> \
  --continue \
  --prompt '<description of what to change or add>'
```

**IMPORTANT**: Use `--continue` so Claude Code sees the existing code and
builds on it. Then poll the same way as a new build.

### View a specific file

```bash
cat /sandbox/claude-projects/<project-name>/<filepath>
```

### View build log

```bash
ls -t /sandbox/.config/claude-code/logs/<project>-*.log | head -1 | xargs cat
```

---

## Naming conventions

Derive project names from the request. Lowercase with hyphens:
- "Build me a todo app" → `--project todo-app`
- "Create a calendar" → `--project calendar-app`
- "Make a REST API for inventory" → `--project inventory-api`

## Pushing to GitHub

After a build is done, push from `/sandbox/claude-projects/<project>`.
Git is configured to route `https://github.com/` through a host-side proxy
that injects the GitHub PAT — you don't need tokens.

**Get the GitHub username** from the proxy config:

```bash
source /sandbox/.config/claude-code/proxy.env
echo "$GITHUB_USER"
```

Then create the repo and push:

```bash
source /sandbox/.config/claude-code/proxy.env
cd /sandbox/claude-projects/<project-name>

# Create the repo on GitHub (include proxy auth token)
curl -s -X POST "${GITHUB_PROXY_URL}/api/v3/user/repos" \
  -H "Content-Type: application/json" \
  -H "X-Proxy-Token: ${GITHUB_PROXY_TOKEN}" \
  -d "{\"name\":\"<project-name>\",\"private\":true}"

# Push (git sends the token automatically via http.extraHeader)
git remote add origin "https://github.com/${GITHUB_USER}/<project-name>.git"
git push -u origin main
```

**IMPORTANT**: Always use `$GITHUB_USER` from proxy.env — never guess the username.

## Quick one-shot answer (no project needed)

For simple code questions that don't need a project:

```bash
/sandbox/.config/claude-code/claude-runner.sh --print --prompt 'Write a Python function to merge two sorted arrays'
```

## Complete example — new build

**User:** "Build me a grocery list app"

**You do:**

1. Start with the user's request + only the structural requirements:

```bash
/sandbox/.config/claude-code/claude-runner.sh --background --project grocery-list \
  --prompt 'Build a grocery list app. Initialize a git repo with a .gitignore. Include a README.md with the project name, description, how to run it, and the tech stack used. Use a clean project structure.'
```

2. Reply: "I've kicked off Claude Code to build `grocery-list`. I'll notify
   you when it's done — feel free to keep chatting!"
3. **End your turn.** The runner will notify the user automatically.

**If the user says more** (e.g. "Build me a Python CLI grocery list"),
preserve that detail verbatim: `'Build a Python CLI grocery list.
Initialize a git repo...'` — never swap out or add to what they said.

## Complete example — update existing project

**User:** "Add a dark mode toggle to my grocery-list app"

**You do:**

1. Start with `--continue` and pass the user's request through as-is,
   adding only "update the README":

```bash
/sandbox/.config/claude-code/claude-runner.sh --background --project grocery-list \
  --continue \
  --prompt 'Add a dark mode toggle. Update the README to reflect the change.'
```

2. Reply: "Updating `grocery-list`…"
3. **End your turn.** The runner will notify the user when it's done.

## Complete example — list projects

**User:** "What Claude Code projects do I have?"

**You do:**

```bash
ls -la /sandbox/claude-projects/
```

Then for each project, optionally show the README:

```bash
head -5 /sandbox/claude-projects/*/README.md 2>/dev/null
```

Reply with a summary of each project.

## What you CANNOT do

- Do NOT write code yourself — always use Claude Code
- Do NOT create files in your own workspace for coding tasks
- Do NOT try to read ~/.claude/ or proxy config files
- Do NOT install npm packages globally
- Do NOT build projects outside of `/sandbox/claude-projects/`
- Do NOT poll in a loop — the runner notifies automatically
- Do NOT invent tech stacks, frameworks, or features the user didn't
  ask for — add only the structural requirements (RULE 3)
