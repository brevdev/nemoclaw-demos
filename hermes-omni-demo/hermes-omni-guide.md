# Hermes + Omni on NemoClaw

Build a local multimodal agent on a single Linux host. By the end you'll have a browser-based demo at `http://localhost:8765` where you can drop in a video, audio file, image, or PDF and ask questions about it. The agent runs inside a sandbox with a deny-by-default network policy.

Three pieces:

- **Nemotron 3 Nano Omni** — multimodal model (video, audio, image, text, reasoning), served by NVIDIA's hosted endpoint
- **Hermes Agent** (Nous Research) — picks the right skill for each question, holds context across turns
- **NemoClaw + OpenShell** — the sandbox runtime that wraps Hermes and enforces a declarative network policy

No GPU required. The model runs in NVIDIA's cloud; everything you run locally is the agent and the sandbox.

## What the demo does

| Modality | Try this |
|---|---|
| Short video | Drop in any clip ≤ 2 min and ask "what's happening?" |
| Long video | Use `chunk-upload.sh` for anything over 2 min, then ask "give me three takeaways" |
| Audio | Drop an MP3 — Omni hears it as audio, not transcribed text |
| PDF | Drop a PDF — pages render, all go to Omni in one call |
| Image | Drop a PNG — Omni describes what it sees |
| Jargon | "Look up FP8 per-tensor scaling on Wikipedia" — hits the proxy whitelist |
| Policy | "Try to fetch google.com" — sandbox returns 403 |

All five modalities run through one skill. The agent picks the tool. The sandbox checks every outbound call.

## Prerequisites

| Requirement | Details |
|---|---|
| Linux host | Brev instance, DGX, or any Docker-capable Linux. No GPU needed. |
| Docker | Installed and running. |
| NVIDIA API key | Starts with `nvapi-`, with Omni access. Get one at [build.nvidia.com](https://build.nvidia.com) → API Keys. |
| `ffmpeg` | `apt install -y ffmpeg`. Needed for the synthetic test clip and for chunking long videos. |
| `poppler-utils` | `apt install -y poppler-utils`. Needed for PDF rendering (`pdftoppm`). |
| Node 20+ and `npm` | Needed to build the web UI. |
| Python 3.10+ | For the FastAPI backend. |

---

## Quickstart (5 commands, ~5 min)

If you've already got NemoClaw installed, this is the short version. The longer walkthrough below explains each step.

```bash
# 1. install the NemoClaw + OpenShell CLIs
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash && source ~/.bashrc

# 2. clone this cookbook
git clone https://github.com/PicoNVIDIA/vlmdemo.git
cd vlmdemo/hermes-omni-demo

# 3. onboard a sandbox (interactive — pick name "my-hermes", model "1", accept presets)
nemoclaw onboard --agent hermes

# 4. configure the sandbox: switch to Omni, apply policy, install skills
openshell inference set --provider nvidia-prod \
    --model private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b
SANDBOX=my-hermes bash scripts/setup.sh

# 5. build the UI and start the server
SANDBOX=my-hermes bash scripts/start.sh
```

Open `http://localhost:8765`. Drop a video into the chat. Ask a question.

---

## The walkthrough

Same flow as the Quickstart, broken into parts with the manual commands and what you should see at each step. The wrapper scripts are pointed out where they apply — they're shortcuts, not requirements.

### Part 1 — Install NemoClaw

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

Verify:

```bash
nemoclaw --version
openshell --version
```

Expected:

```
nemoclaw v0.0.16
openshell 0.0.26
```

### Part 2 — Onboard a sandbox

This step is interactive. You answer the prompts. **Do this manually — there is no script for it.** The choices below match the rest of the guide.

```bash
nemoclaw onboard --agent hermes
```

When prompted:

| Prompt | Answer |
|---|---|
| Inference provider | `1` (NVIDIA Endpoints) |
| API key | Paste your `nvapi-...` key |
| Model | `1` (Nemotron 3 Super 120B — you'll swap this to Omni in Part 3) |
| Sandbox name | `my-hermes` |
| Policy presets | `Y` (accept npm, pypi, huggingface, brew, brave) |

The wizard takes ~1 min. At the end you'll see:

```
✓ Sandbox 'my-hermes' created
✓ Hermes Agent gateway launched inside sandbox
```

Verify the sandbox is running:

```bash
nemoclaw my-hermes status
```

Expected (truncated):

```
Sandbox: my-hermes
  Model:    nvidia/nemotron-3-super-120b-a12b
  Phase:    Ready
  Agent:    Hermes Agent v2026.4.8
```

### Part 3 — Switch the gateway to Omni

The onboarding wizard only offers Super 120B. We need Omni so Hermes can handle video, audio, and images. Three things to update:

```bash
# 1. The gateway route — this is what actually executes calls
openshell inference set \
    --provider nvidia-prod \
    --model private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b

# 2. Hermes's in-sandbox config — controls the TUI banner display
openshell sandbox exec -n my-hermes -- bash -c \
    "sed -i 's|nvidia/nemotron-3-super-120b-a12b|nvidia/nemotron-3-nano-omni-reasoning-30b-a3b|' \
     /sandbox/.hermes-data/config.yaml"

# 3. Host-side metadata — controls `nemoclaw list` output
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.nemoclaw' / 'sandboxes.json'
d = json.load(open(p))
d['sandboxes']['my-hermes']['model'] = 'nvidia/nemotron-3-nano-omni-reasoning-30b-a3b'
json.dump(d, open(p, 'w'), indent=4)
"
```

Verify:

```bash
openshell inference get
```

Expected:

```
Gateway inference:
  Provider: nvidia-prod
  Model:    private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b
```

```bash
nemoclaw list
```

Expected:

```
my-hermes
  model: nvidia/nemotron-3-nano-omni-reasoning-30b-a3b  provider: nvidia-prod
```

If you skip step 2 or 3, the model name in `nemoclaw list` and the Hermes TUI banner will lie about what's actually running. The gateway route (step 1) is what determines real behavior; steps 2 and 3 are display-only.

### Part 4 — Clone the cookbook, set the SANDBOX env var

```bash
git clone https://github.com/PicoNVIDIA/vlmdemo.git
cd vlmdemo/hermes-omni-demo
export SANDBOX=my-hermes
```

The NVIDIA API key only needs to exist on the host where you ran `nemoclaw onboard`. It lives in the OpenShell gateway's credential store. Scripts inside the sandbox reach Omni through the gateway and never see the key.

### Part 5 — Configure the sandbox

This part has a one-shot wrapper. Both paths produce the same end state.

**Shortcut:**

```bash
bash scripts/setup.sh
```

**Or do it by hand**, which is what the script does, in order:

1. Apply the Wikipedia + Dictionary policy blocks (so the jargon-lookup skill can do its job):

```bash
openshell policy get $SANDBOX --full > /tmp/raw-policy.txt
awk '/^---$/{seen=1; next} seen' /tmp/raw-policy.txt > /tmp/current-policy.yaml
cat policy/hermes-omni-lookup.yaml >> /tmp/current-policy.yaml
openshell policy set --policy /tmp/current-policy.yaml $SANDBOX
```

Expected:

```
✓ Policy version 7 submitted (hash: ...)
✓ Policy version 7 loaded (active version: 7)
```

2. Install the two skills:

```bash
nemoclaw $SANDBOX skill install skills/video-analyze
nemoclaw $SANDBOX skill install skills/jargon-lookup
```

Expected:

```
✓ Skill 'video-analyze' installed
✓ Skill 'jargon-lookup' installed
```

3. Upload the scripts and the agent's identity file:

```bash
openshell sandbox upload $SANDBOX scripts/omni-video-analyze.py /sandbox/.hermes-data/workspace/
openshell sandbox upload $SANDBOX scripts/lookup-jargon.py /sandbox/.hermes-data/workspace/
openshell sandbox exec -n $SANDBOX -- chmod +x \
    /sandbox/.hermes-data/workspace/omni-video-analyze.py \
    /sandbox/.hermes-data/workspace/lookup-jargon.py

# SOUL.md goes in two places — Hermes reads from both
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/memories/
openshell sandbox upload $SANDBOX memories/SOUL.md /sandbox/.hermes-data/
```

Verify the skills:

```bash
openshell sandbox exec -n $SANDBOX -- hermes skills list
```

Expected:

```
              Installed Skills
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┓
┃ Name          ┃ Category ┃ Source ┃ Trust ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━┩
│ jargon-lookup │          │ local  │ local │
│ video-analyze │          │ local  │ local │
└───────────────┴──────────┴────────┴───────┘
```

### Part 6 — Smoke test

Make sure Omni is reachable from inside the sandbox before you bring up the UI.

```bash
ffmpeg -y -f lavfi -i "testsrc=duration=20:size=320x240:rate=15" \
    -f lavfi -i "sine=frequency=440:duration=20" \
    -c:v libx264 -pix_fmt yuv420p -shortest \
    /tmp/test-video.mp4

openshell sandbox upload $SANDBOX /tmp/test-video.mp4 /tmp/

openshell sandbox exec -n $SANDBOX -- python3 \
    /sandbox/.hermes-data/workspace/omni-video-analyze.py \
    /tmp/test-video.mp4 "What is in this video?"
```

Expected (last lines):

```
--- Omni Analysis ---
The video displays a television test pattern (specifically SMPTE color bars)
with a horizontal rainbow gradient bar running across the lower portion.
Inside a black box on the right side of the screen, a pixelated white number
counts up sequentially from 1 to 20.

[4176 tokens, 351KB payload]
```

If you see this, the gateway → Omni path is healthy.

### Part 7 — Bring up the web UI

**Shortcut:**

```bash
bash scripts/start.sh
```

The script checks the sandbox is Ready, builds the UI if `ui/dist` is missing, makes sure the server's Python deps are installed, and runs uvicorn on port 8765. The same uvicorn serves both the API (`/api/*`) and the built React app (`/`).

You should see:

```
→ sandbox: my-hermes
→ url:     http://localhost:8765

✓ sandbox Ready
✓ UI built at /path/to/ui/dist
✓ server deps ready

→ launching server
  open http://localhost:8765 in your browser
  Ctrl-C to stop

INFO:     Uvicorn running on http://0.0.0.0:8765
```

**Or by hand:**

```bash
# install UI deps and build the static bundle (~30s)
cd ui
npm install
npm run build
cd ..

# install server deps
pip install -r server/requirements.txt

# run the server
cd server
SANDBOX=my-hermes uvicorn server:app --host 0.0.0.0 --port 8765
```

Open `http://localhost:8765`. You should see:

- A header with a "Live · Nemotron 3 Nano Omni 30B" pill
- A flow diagram (You → Sandbox → Omni)
- A chat input at the bottom
- A bottom ticker showing live policy events as you exercise the agent

### Part 8 — Use the demo

In the browser:

1. **Drop a short video** onto the chat. Type *"What's happening in this clip?"*. Watch the flow diagram light up Hermes → Sandbox → Omni. The answer streams back.
2. **Ask a follow-up** that wasn't in the original answer ("what colors are in it?"). The diagram lights again — Hermes re-runs the script with the new question instead of answering from memory.
3. **Drop a PDF** (it gets rendered to per-page PNGs on the host, uploaded as a directory, and sent to Omni as a multi-image payload). Ask *"what's the main argument?"*.
4. **Click the mic icon** and speak a question. The browser records audio, the host transcodes it, Omni hears it as audio.
5. **Open the Memory drawer** to see the session log — every prompt, tool call, and attachment is indexed with full-text search.
6. **Open the Policy drawer** and click *Run Security Check*. Six destinations are tested; five blocked, one allowed. Then flip the `nvidia.com` toggle off and re-run — the policy hot-swaps in ~5 seconds.

### Part 9 — Stop the demo

If `start.sh` is in the foreground, hit `Ctrl-C`.

If you backgrounded it (e.g. via `tmux` or `&`):

```bash
bash scripts/stop.sh
```

Expected:

```
→ stopping process(es) on port 8765: 1215884
✓ stopped
```

---

## Long videos

The single-call path tops out at ~9 MB after base64 encoding (gateway body cap), about 2 min of 480p video. For longer content, this cookbook ships a host-side helper that splits the video into chunks, uploads them as a directory, and lets the same skill loop over the chunks and synthesize one answer.

```bash
bash scripts/chunk-upload.sh /path/to/long-talk.mp4
# default chunks at 120s; pass a second arg for different segment length:
#   bash scripts/chunk-upload.sh /path/to/long-talk.mp4 90
```

Expected:

```
→ probing /path/to/long-talk.mp4
  duration: 397.184000s, chunking into 120s segments at 480p
→ writing chunks.json manifest
  4 chunks, 397.3s total, 7.4 MB on disk
→ uploading /tmp/long-talk-chunks into sandbox 'my-hermes'
✓ Upload complete
```

In the chat, paste:

```
Analyze the video at /tmp/long-talk-chunks — give me three takeaways.
```

The skill detects "directory of MP4 files" and runs Omni once per chunk with absolute timestamps in each prompt, then makes one synthesis call across all the chunk summaries. Cost is linear in source video length — roughly 11K tokens per minute of source.

## PDFs (also via host helper)

```bash
bash scripts/pdf-upload.sh /path/to/document.pdf
```

Expected:

```
→ rendering /path/to/document.pdf → /tmp/document-pages (150 dpi)
  12 pages, 8 MB on disk
→ uploading /tmp/document-pages into sandbox 'my-hermes'
✓ Upload complete
```

In the chat:

```
Read the document at /tmp/document-pages — what's the main argument?
```

Omni's per-request image cap is 8 images. The skill auto-batches PDFs longer than that — the same chunk-and-synthesize pattern as long videos. For an 8-page PDF, the skill makes one call. For 30 pages, it makes 4 batch calls plus one synthesis call. Cost is linear in page count (~few thousand tokens per page).

## See the policy block

In a second terminal:

```bash
openshell logs my-hermes --tail --source sandbox | grep --line-buffered -E "ALLOWED|DENIED"
```

Then in the chat:

```
Try to fetch https://google.com with curl so we can see NemoClaw block it.
```

In the logs terminal you'll see something like:

```
[OCSF] NET:OPEN [MED] DENIED /usr/bin/curl -> google.com:443 [policy:- engine:opa]
```

The agent reports the block in plain language. Every call to `integrate.api.nvidia.com` is `ALLOWED`; everything else is `DENIED`.

---

## Day-2 operations

### After a host reboot

```bash
nemoclaw my-hermes status                # confirm Phase: Ready
SANDBOX=my-hermes bash scripts/start.sh  # bring the UI back up
```

If `Phase` is not `Ready`, the openshell gateway likely needs a kick:

```bash
openshell gateway status
openshell gateway start  # if it's not running
```

### Add a new skill

Drop a new directory under `skills/` with its own `SKILL.md`, then:

```bash
nemoclaw $SANDBOX skill install skills/your-new-skill
openshell sandbox exec -n $SANDBOX -- hermes skills list
```

Restart `hermes chat` (or refresh the web UI) so Hermes picks up the new skill.

### Hermes TUI for debugging

The web UI is the demo path. The TUI is for poking at things:

```bash
nemoclaw my-hermes connect
hermes chat
```

You're now in the sandbox shell. Hermes runs in its TUI; type questions, watch tool calls, exit with `/exit` or `Ctrl-D`.

### Snapshots and starting over

```bash
# snapshot the sandbox before a destructive change
nemoclaw my-hermes snapshot create

# nuke and start over
nemoclaw my-hermes destroy --yes
nemoclaw onboard --agent hermes
# repeat Parts 3-5
```

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| TUI banner / `nemoclaw list` shows Super 120B even after the swap | Display labels weren't updated. Re-run the two `sed`/`python3` commands in Part 3. The gateway route is correct; only the labels lie. |
| `SSL EOF occurred in violation of protocol` from `omni-video-analyze.py` | Payload exceeded ~9 MB. Use `chunk-upload.sh` (Long Videos section), or trim with `ffmpeg -i big.mp4 -t 120 -c copy small.mp4`. |
| `'NoneType' object has no attribute 'strip'` mid-chunked-run | Old script. Re-upload the v3 from `scripts/omni-video-analyze.py`. |
| `Connection refused` on `inference.local` from inside the sandbox | Gateway lost its route. Re-run `openshell inference set ...` from Part 3. |
| Hermes says "I can't browse the web" when asked to look up a definition | SOUL.md didn't load or there are two stale copies. Re-run the two SOUL upload commands in Part 5, restart `hermes chat`. |
| `exit 126` when Hermes runs a script | Lost the executable bit. `openshell sandbox exec -n $SANDBOX -- chmod +x /sandbox/.hermes-data/workspace/*.py`. |
| Hermes hallucinates a name for the speaker on a long video | Omni has no face/voice grounding. Open recordings with a self-introduction, or add to the prompt: `Refer to the speaker as "the narrator" — do not assign a name unless they introduce themselves`. |
| `start.sh` says sandbox is not Ready | `nemoclaw my-hermes status` to see the actual phase. If `Pending`, wait 30s and retry. If `Failed`, check `nemoclaw my-hermes logs`. |
| Port 8765 already in use when `start.sh` runs | Another server is already on that port. `bash scripts/stop.sh` to kill it, or set `PORT=8766` and re-run. |
| UI loads but `/api/*` calls fail | The server didn't start cleanly. Check the terminal where `start.sh` is running — uvicorn errors will be visible there. |
| `openshell sandbox upload DEST` made a directory instead of putting the file | Trailing slash matters. `upload SRC /tmp/` puts the file in `/tmp/`. `upload SRC /tmp` makes a directory called `/tmp`. |

## Tailing logs

```bash
# OCSF policy verdicts (most useful for debugging policy)
openshell logs my-hermes --tail --source sandbox | grep --line-buffered -E "ALLOWED|DENIED"

# Gateway-side events (tunnel, command exec)
openshell logs my-hermes --tail --source gateway
```

## Repo layout

```
hermes-omni-demo/
├── hermes-omni-guide.md         this file
├── policy/
│   └── hermes-omni-lookup.yaml  Wikipedia + Free Dictionary policy blocks
├── memories/
│   └── SOUL.md                  Hermes identity / steering
├── skills/
│   ├── video-analyze/SKILL.md   handles video, audio, image, PDF-pages, chunked dirs
│   └── jargon-lookup/SKILL.md   Wikipedia + Free Dictionary lookup
├── scripts/
│   ├── omni-video-analyze.py    the multimodal skill — runs inside the sandbox
│   ├── lookup-jargon.py         the jargon skill — runs inside the sandbox
│   ├── chunk-upload.sh          host helper — long video → chunks dir → upload
│   ├── pdf-upload.sh            host helper — PDF → page PNGs → upload
│   ├── setup.sh                 wraps Part 5 (policy + skills + scripts upload)
│   ├── start.sh                 build UI + run server on port 8765
│   └── stop.sh                  kill whatever's on the demo port
├── server/                      FastAPI backend
│   ├── server.py
│   └── requirements.txt
└── ui/                          React + Vite + Tailwind frontend
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── api/client.ts
        ├── components/{ChatPanel,FlowDiagram,PolicyDrawer,...}.tsx
        └── styles/index.css
```
