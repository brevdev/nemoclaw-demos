# NASA Astronomy Picture of the Day Demo

Your AI agent explores NASA's astronomy archive — fetching stunning space imagery, explaining celestial objects, and reasoning across photos.

> **One-line story:** "Let's start with space." Agent fetches today's NASA astronomy photo, explains what it is, and lets the audience click through to a full-screen image.

---

## What You Get

| Capability | Description |
|---|---|
| **Today's Photo** | Fetch the current Astronomy Picture of the Day with title, explanation, and HD image URL |
| **Date Lookup** | Retrieve any APOD entry by date (archive goes back to June 16, 1995) |
| **Date Range** | Get all entries for a date range (e.g. "this week's photos") |
| **Random Discovery** | Pull N random entries from the entire 30-year archive |
| **Reasoning** | Agent compares photos, summarizes explanations, identifies celestial objects |

### What makes it different from Planet

Planet is **Earth looking down** — commercial satellite imagery with a Tier-1 security model, host-side proxy, and 15+ API commands. NASA APOD is **space looking out** — free public data, zero credentials, one API endpoint. The two complement each other for a "start in space, come back to Earth" demo narrative.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| NemoClaw sandbox | `nemoclaw onboard` completed |
| Internet access | Sandbox must reach `api.nasa.gov` (HTTPS) |

No GPU. No API key. No host-side services. No cost.

---

## Quick Start

```bash
cd nasa-apod-demo
./install.sh
```

The script:
1. Applies a network policy allowing `api.nasa.gov` for `curl` and `node`
2. Uploads `SKILL.md` to the sandbox
3. Clears agent sessions so the new skill is discovered
4. Verifies the API is reachable with `DEMO_KEY`

---

## Manual Setup

If you prefer to install step by step.

### Part 1: Apply Network Policy

Export and update the sandbox policy:

```bash
SANDBOX=my-assistant
openshell policy get $SANDBOX --full 2>&1 | sed '1,/^---$/d' > /tmp/current-policy.yaml
```

Add this block under `network_policies:` in the YAML:

```yaml
  nasa_apod:
    name: nasa_apod
    endpoints:
    - host: api.nasa.gov
      port: 443
      protocol: rest
      tls: passthrough
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /planetary/apod
    binaries:
    - path: /usr/bin/curl
    - path: /usr/local/bin/node
```

Apply:

```bash
openshell policy set $SANDBOX --policy /tmp/current-policy.yaml --wait
```

### Part 2: Upload the Skill

```bash
openshell sandbox upload $SANDBOX \
  skills/nasa-apod/SKILL.md \
  /sandbox/.openclaw/skills/nasa-apod/
```

**Fallback** (if `sandbox upload` hangs or is unavailable):

```bash
DOCKER_CTR=openshell-cluster-nemoclaw

docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- mkdir -p /sandbox/.openclaw/skills/nasa-apod

cat skills/nasa-apod/SKILL.md | docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw/skills/nasa-apod/SKILL.md'

docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chown -R sandbox:sandbox /sandbox/.openclaw/skills/nasa-apod
```

### Part 3: Clear Sessions

Connect and clear so the agent picks up the new skill:

```bash
nemoclaw $SANDBOX connect
```

Or manually:

```bash
openshell sandbox exec $SANDBOX -- \
  bash -c 'rm -rf /sandbox/.openclaw-data/agents/main/sessions/*'
```

---

## Demo Prompts

### Hook — "Start with space"

```text
What's today's Astronomy Picture of the Day from NASA?
```

The agent calls the API, returns the title, a summary of the explanation, and the HD image URL. **Click the URL** — a full-screen space photo appears.

### Date exploration

```text
Show me NASA's astronomy picture from June 3rd 2025.
```

Shows the agent can parameterize API calls with specific dates.

### Batch discovery

```text
Find 5 random NASA astronomy photos and tell me which one is the most visually stunning.
```

Agent fetches 5 random entries, reads the descriptions, and picks a favorite with reasoning.

### Comparison (pure reasoning)

```text
Compare today's photo with the one from last Christmas. Which is more scientifically significant?
```

No new API call needed — agent reasons over data it already has. This is the "intelligence" moment.

### Transition to Planet (the killer combo)

```text
Now let's come back to Earth. What satellite imagery is available over Taipei this week?
```

Same agent, same session, different domain. Transitions from NASA APOD to Planet integration — "start in space, come back to Earth, same system."

---

## Expected Output

The agent presents results as a formatted chat message:

```text
Today's Astronomy Picture of the Day

Title: Artemis II: Flight Day 6
Date: 2026-04-11

On flight day 6, the Artemis II mission achieved a historic lunar flyby.
The Orion spacecraft reached nearly 407,000 km from Earth — the farthest
any human has traveled since Apollo 13 in 1970. This selfie from a solar
array camera frames the spacecraft, the lunar far side, and Earth as a
small bright crescent beyond the limb.

HD Image: https://apod.nasa.gov/apod/image/2604/art002e009567_1920.jpg

Click the image link to view the full-resolution photo.
```

---

## File Structure

```
nasa-apod-demo/
├── install.sh                    # Automated installer
├── nasa-apod-guide.md           # This guide
├── policy/
│   └── nasa-apod.yaml           # Policy template
└── skills/
    └── nasa-apod/
        └── SKILL.md              # Agent skill definition
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Agent doesn't know about NASA APOD | Re-run `./install.sh` or upload SKILL.md manually and clear sessions |
| `l7_decision=deny` in OpenShell logs | Policy not applied. Check `nasa_apod` block is present: `openshell policy get $SANDBOX --full \| grep nasa` |
| "Rate limit exceeded" | DEMO_KEY allows 50 requests/day. For booth use, get a free key at [api.nasa.gov](https://api.nasa.gov/) and replace `DEMO_KEY` in SKILL.md |
| Response has `media_type: video` | ~10% of APOD entries are YouTube videos. Agent should note this and provide the video URL. Add `thumbs=true` to get a thumbnail. |
| Agent returns empty or error | Check sandbox can reach the API: `openshell sandbox exec $SANDBOX -- curl -s "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"` |



