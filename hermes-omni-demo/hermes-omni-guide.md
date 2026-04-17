# NemoClaw + Hermes + Omni: Zero-to-Hero Cookbook

This guide takes you from a fresh machine to a working multimodal agent demo. By the end, a **Hermes Agent** inside a NemoClaw sandbox will analyze a video with **Nemotron Omni 30B**, then look up definitions on Wikipedia — while a deny-by-default policy blocks every other website.

The setup connects three components:
- **NemoClaw** — creates the sandbox, applies the network policy, and enforces the L7 egress filter
- **Hermes Agent** (Nous Research) — orchestrates the tools and skills inside the sandbox
- **Nemotron Omni 30B** — the primary multimodal model (text + image + video + audio) via the NVIDIA cloud

> **No GPU required.** Omni is served by the NVIDIA cloud endpoint.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Linux machine | Brev instance, DGX, or any Docker-capable host. No GPU needed. |
| Docker | Must be installed and running. |
| NVIDIA API key | An API key (starts with `nvapi-`) with access to the Omni model. Get one at [build.nvidia.com](https://build.nvidia.com). |
| ffmpeg on the host | Only needed for Part 7 (generating the test video). `apt install -y ffmpeg`. |

## Part 1: Install NemoClaw

``` bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

Verify:

``` bash
nemoclaw --version
openshell --version
```

You should see something like:

```
NemoClaw v0.0.16
openshell 0.0.26
```

## Part 2: Onboard with the Hermes Agent

NemoClaw ships a first-class Hermes agent — pass `--agent hermes` during onboarding:

``` bash
nemoclaw onboard --agent hermes
```

When prompted:

1. **Inference**: Choose `1` (NVIDIA Endpoints)
2. **API Key**: Paste your NVIDIA API key (`nvapi-...`)
3. **Model**: Choose the **Nemotron Omni** option (Hermes will use Omni as its primary model)
4. **Sandbox name**: Enter a name — this guide uses `my-hermes`
5. **Policy presets**: Accept the suggested presets with `Y`

You should see output ending with:

```
✓ Sandbox 'my-hermes' created
✓ Hermes gateway launched inside sandbox
```

Verify:

``` bash
nemoclaw my-hermes status
```

You should see `Phase: Ready` and the Hermes gateway listening on port 8642.

> **Non-interactive mode:**
> ``` bash
> export NEMOCLAW_NON_INTERACTIVE=1
> export NVIDIA_API_KEY=nvapi-...
> nemoclaw onboard --agent hermes --non-interactive --yes-i-accept-third-party-software
> ```

## Part 3: Set Variables

``` bash
export SANDBOX=my-hermes                       # whatever you named it in Part 2
export NVIDIA_API_KEY=nvapi-...                # your NVIDIA API key
```

Clone this cookbook (if you haven't already):

``` bash
git clone https://github.com/PicoNVIDIA/vlmdemo.git
cd vlmdemo/hermes-omni-demo
```

## Part 4: Apply the Knowledge-Lookup Policy

The baseline Hermes policy already allows the NVIDIA Omni API, PyPI, and a few Nous Research endpoints. We need to add two more whitelists — Wikipedia's summary API and the Free Dictionary API — so the jargon-lookup skill can do its job.

``` bash
openshell policy set --policy policy/hermes-omni-lookup.yaml $SANDBOX
```

You should see:

```
✓ Policy version N submitted (hash: ...)
```

Verify the additions made it in:

``` bash
openshell policy get $SANDBOX -v | grep -E "wikipedia|dictionary"
```

You should see the `wikipedia` and `free_dictionary` policy blocks.

### What this policy actually enforces

| Destination | Method / path | Allowed binaries | Notes |
|-------------|---------------|------------------|-------|
| `en.wikipedia.org` | `GET /api/rest_v1/page/summary/**`, `GET /w/api.php` | `python3.11` only | No `/wiki/` pages; no POSTs |
| `api.dictionaryapi.dev` | `GET /api/v2/entries/**` | `python3.11` only | Everything else denied |

`curl`, `wget`, and `browser_*` tools **cannot** reach either site. Anything outside these two endpoints returns `403 Forbidden` at the L7 proxy.

## Part 5: Install the Skills

Hermes uses "skills" — self-contained `SKILL.md` manifests — to decide which tool to run for a given user request. We ship two:

- **video-analyze** — wraps `omni-video-analyze.py`
- **jargon-lookup** — wraps `lookup-jargon.py`

Install both:

``` bash
nemoclaw $SANDBOX skill install skills/video-analyze
nemoclaw $SANDBOX skill install skills/jargon-lookup
```

Verify:

``` bash
openshell sandbox exec -n $SANDBOX -- hermes skills list
```

You should see both skills listed under `general`.

## Part 6: Upload the Scripts and SOUL.md

The skills reference two Python scripts that must live in the sandbox workspace. Upload them and make them executable:

``` bash
openshell sandbox upload $SANDBOX scripts/omni-video-analyze.py /sandbox/.hermes-data/workspace/
openshell sandbox upload $SANDBOX scripts/lookup-jargon.py /sandbox/.hermes-data/workspace/

# openshell upload creates a DEST directory and puts the file inside. Flatten it:
openshell sandbox exec -n $SANDBOX -- bash -c '
  WORK=/sandbox/.hermes-data/workspace
  for f in omni-video-analyze.py lookup-jargon.py; do
    if [[ -d "$WORK/$f" ]]; then
      mv "$WORK/$f/$f" "$WORK/$f.tmp"; rmdir "$WORK/$f"; mv "$WORK/$f.tmp" "$WORK/$f"
    fi
    chmod +x "$WORK/$f"
  done
'
```

### Drop in SOUL.md

Hermes reads `SOUL.md` to decide which tool to reach for. Our SOUL explicitly tells Hermes:
- Use the `terminal` tool (not `execute_code`) to run the scripts
- Never try `browser_navigate` or `curl` for Wikipedia — call `lookup-jargon.py`
- Re-run the video script when the user asks a follow-up, instead of answering from memory

Upload it to both paths Hermes reads:

``` bash
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/memories/
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/

openshell sandbox exec -n $SANDBOX -- bash -c '
  for dir in /sandbox/.hermes-data/memories /sandbox/.hermes-data; do
    if [[ -d "$dir/SOUL.md" ]]; then
      mv "$dir/SOUL.md/SOUL.md" "$dir/SOUL.md.tmp"; rmdir "$dir/SOUL.md"; mv "$dir/SOUL.md.tmp" "$dir/SOUL.md"
    fi
  done
'
```

> **Shortcut:** Parts 4–6 are automated in `install.sh`:
> ``` bash
> SANDBOX=$SANDBOX ./install.sh
> ```

## Part 7: Add a Test Video

Omni needs a video to look at. Generate a short synthetic one with `ffmpeg` on the host (or bring your own MP4):

``` bash
# Simple test clip: title card + color bars + spoken text if espeak-ng is available
ffmpeg -y \
  -f lavfi -i "testsrc=duration=20:size=320x240:rate=15" \
  -f lavfi -i "sine=frequency=440:duration=20" \
  -c:v libx264 -pix_fmt yuv420p -shortest \
  /tmp/test-video.mp4
```

Or use any MP4 you already have — something under 3 minutes works best.

Upload it into the sandbox:

``` bash
openshell sandbox upload $SANDBOX /tmp/test-video.mp4 /tmp/test-video.mp4
```

Verify:

``` bash
openshell sandbox exec -n $SANDBOX -- ls -la /tmp/test-video.mp4
```

### Smoke-test the analyzer before touching Hermes

``` bash
openshell sandbox exec -n $SANDBOX -- python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/test-video.mp4 "What is in this video?"
```

You should see Omni describe what it sees plus a line like `[36983 tokens, 15406KB payload]`. If this works, the Omni path is healthy.

## Part 8: Chat with the Agent

Connect to the sandbox:

``` bash
nemoclaw $SANDBOX connect
```

Launch Hermes:

``` bash
hermes chat
```

Try these prompts in order — they exercise all three pillars (Omni + Hermes + NemoClaw):

**1. Omni watches the video**
```
Analyze /tmp/test-video.mp4 and tell me what's happening.
```

**2. Hermes re-runs the script for a follow-up question** (not from memory)
```
What colors are visible?
```

**3. Jargon lookup via the whitelisted Wikipedia path**
```
Look up "unit vector" on Wikipedia with physics context.
```

**4. Full multimodal chain** — the money shot
```
Watch /tmp/test-video.mp4, pull out any technical terms, then look each one up on Wikipedia.
```

## Part 9: See NemoClaw Block Unauthorized Egress

Open a second terminal and tail the sandbox policy decisions:

``` bash
openshell logs $SANDBOX --tail --source sandbox | grep --line-buffered "ocsf"
```

Then, back in Hermes, ask for a blocked site:

```
Try to fetch https://google.com with curl so we can see NemoClaw block it.
```

In the logs terminal you should see a line like:

```
[sandbox] [OCSF] NET:OPEN [MED] DENIED /usr/bin/curl -> google.com:443 [policy:- engine:opa]
```

Hermes will report the block in plain language. Every call to `integrate.api.nvidia.com` is `ALLOWED`; everything else is `DENIED`.

## How It All Fits Together

```
┌───────────────────────────────────────────────────────────────┐
│  User types a prompt in Hermes TUI                            │
│                         │                                     │
│                         ▼                                     │
│  ┌──────────────────────────────────────┐                     │
│  │  Hermes Agent (Nous Research)        │                     │
│  │  reads SOUL.md + skills              │                     │
│  │  picks video-analyze OR jargon-lookup│                     │
│  └──────────┬───────────────────────────┘                     │
│             │                                                 │
│     ┌───────┴────────┐                                        │
│     ▼                ▼                                        │
│  omni-video     lookup-jargon.py                              │
│  -analyze.py                                                  │
│     │                │                                        │
│     │                ▼                                        │
│     │     ┌─────────────────────────────────────────┐         │
│     │     │ NemoClaw L7 proxy (deny-by-default)     │         │
│     │     │ allow: en.wikipedia.org /api/rest_v1/** │         │
│     │     │ allow: api.dictionaryapi.dev /api/v2/** │         │
│     │     │ deny:  everything else → 403 Forbidden  │         │
│     │     └──────────┬──────────────────────────────┘         │
│     │                ▼                                        │
│     │         Wikipedia summary JSON                          │
│     │                                                         │
│     └─► integrate.api.nvidia.com/v1/chat/completions          │
│         (allowed by baseline nvidia policy block)             │
│                                                               │
│  Response flows back up → Hermes → user                       │
└───────────────────────────────────────────────────────────────┘
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `NVIDIA_API_KEY is not set` when running the script | `export NVIDIA_API_KEY=nvapi-...` before running, or set it inside the sandbox shell. The scripts refuse to run without it. |
| Hermes says "I don't have the ability to browse the web" | SOUL.md didn't load or didn't override the stale one at `/sandbox/.hermes-data/SOUL.md`. Re-run Part 6; there are **two** SOUL files and both must be kept in sync. Then `/exit` and restart `hermes chat`. |
| Hermes calls `browser_navigate` or `curl` for Wikipedia | Same root cause as above — SOUL isn't steering. Confirm `grep "lookup-jargon" /sandbox/.hermes-data/SOUL.md` returns lines, restart chat. |
| `exit 126` when Hermes runs a script | The script lost its executable bit. `chmod +x` it inside the sandbox. |
| `No such file or directory: 'ffprobe'` when the sandbox analyzes video | The video script has a pure-Python MP4 duration fallback — make sure `scripts/omni-video-analyze.py` is the one committed in this repo, not an older copy. |
| Hermes tries `omni-video.py` (wrong name) | You have a stale script left in the workspace. `openshell sandbox exec -n $SANDBOX -- rm /sandbox/.hermes-data/workspace/omni-video.py` |
| Hermes uses `execute_code` and gets a network error | It picked the wrong tool. SOUL.md says to use `terminal`. Re-prompt: "Use the terminal tool and run: python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /tmp/test-video.mp4" |
| Hermes claims the professor's name "wasn't in the previous analysis" | Follow-up questions need a fresh script call. Re-prompt with "Re-run omni-video-analyze with that specific question." |
| `openshell sandbox upload DEST` creates a directory instead of a file | Known behavior — the tool treats DEST as a folder. Use the flatten-after-upload pattern from Part 6, or upload to the parent directory with a trailing slash. |
| `execute_code returned an error` for video analysis | Hermes used the wrong tool. Nudge: "Use terminal, not execute_code." Add to SOUL.md if it persists. |

## Tailing Logs

Two log sources are useful:

``` bash
# Sandbox-side (policy decisions, OCSF-formatted ALLOW/DENY events)
openshell logs $SANDBOX --tail --source sandbox

# Gateway-side (OpenShell tunnel + command execution)
openshell logs $SANDBOX --tail --source gateway
```

For a clean demo-friendly view, filter to just the policy verdicts:

``` bash
openshell logs $SANDBOX --tail --source sandbox | grep --line-buffered -E "ALLOWED|DENIED"
```

## Starting Over

``` bash
nemoclaw $SANDBOX destroy --yes
nemoclaw onboard --agent hermes
# Repeat Parts 3–8
```

Or, to snapshot the sandbox before testing destructive changes:

``` bash
nemoclaw $SANDBOX snapshot create
```
