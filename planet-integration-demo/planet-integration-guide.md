# Planet Integration Guide for NemoClaw / OpenClaw

Add [Planet Insights Platform](https://docs.planet.com/develop/apis/) satellite imagery capabilities to your NemoClaw agent. Search Planet's catalog, estimate tasking costs, check satellite pass availability, view account quota, and download thumbnails -- all through the secure OpenShell sandbox.

---

## What You Get

| Capability | Description |
|---|---|
| **Catalog Search** | Search Planet's archive by location, date, cloud cover, and item type |
| **Statistics** | Histogram counts of available imagery over time |
| **Item Details** | Full metadata for any scene (geometry, properties, acquisition time) |
| **Asset Listing** | Check available asset types and activation status |
| **Thumbnails** | Download scene thumbnails to `/tmp/` |
| **Tile URLs** | Generate XYZ tile URLs for visualization |
| **Tasking Pricing** | Estimate tasking cost for an area (read-only, no orders) |
| **Imaging Windows** | Check satellite pass availability and feasibility |
| **Tasking Orders** | View existing orders and their status |
| **Tasking Captures** | List captures associated with orders |
| **Account Quota** | Show products with remaining quota |

### Safety

All tasking commands are **read-only**. The proxy blocks POST requests to the order creation endpoint at the network level, making it physically impossible to place orders or incur charges.

---

## Prerequisites

1. **NemoClaw** installed and a sandbox running (`nemoclaw onboard` completed)
2. **Planet account** with an API key from [planet.com/account](https://www.planet.com/account/#/user-settings)
3. **Python 3** on the host (for the proxy service)
4. **Node.js** inside the sandbox (included by default)

---

## Quick Start

```bash
cd planet-integration-demo
./install.sh
```

The script:
1. Prompts for your Planet API key (saved to `~/.nemoclaw/credentials.json`)
2. Starts the host-side proxy service
3. Applies the network policy
4. Deploys the skill to the sandbox
5. Writes the proxy URL to the skill's `.env` (no API key in sandbox)
6. Clears agent sessions so the new skill is discovered

---

## Security: Tier 1 (Host-Side Proxy)

Your Planet API key **never enters the sandbox**.

```
+----------------------------------+
|  OpenShell Sandbox               |
|                                  |
|  planet-api.js (node)            |
|    GET /api/data/v1/item-types   |
|    (no credentials)              |
|         |                        |
+---------|------------------------+
          | HTTP (policy-enforced)
          v
+----------------------------------+
|  Host: planet-proxy.py (:9201)   |
|                                  |
|  Reads ~/.nemoclaw/credentials   |
|  Injects Authorization header    |
|  Blocks order creation (403)     |
|         |                        |
+---------|------------------------+
          | HTTPS
          v
+----------------------------------+
|  api.planet.com                  |
|  tiles.planet.com                |
+----------------------------------+
```

| Layer | Protection |
|---|---|
| **API Key Isolation** | Key on host only, never in the sandbox |
| **Host-Side Proxy** | Injects credentials and forwards requests |
| **Order Blocklist** | POST to `/api/tasking/v2/orders` returns 403 |
| **Network Policy** | L7 proxy restricts sandbox to the proxy endpoint only |
| **Binary Scoping** | Only `node` can make outbound requests |
| **No Docker Rebuild** | Works on a live sandbox |
| **Hot-Updatable Keys** | Edit `credentials.json`, changes are instant |

---

## Usage Examples

### Catalog prompts

- "What satellite imagery types does Planet offer?"
- "Search for clear imagery over San Francisco from last month"
- "How many PlanetScope scenes cover London this year?"
- "Show me details for that scene"
- "Download a thumbnail of that scene"

### Tasking prompts (read-only)

- "How much would it cost to task a satellite over the Pentagon?"
- "When is the next satellite pass over Washington DC?"
- "Show me my existing tasking orders"
- "What's my Planet quota?"

### CLI usage (inside the sandbox)

```bash
# Catalog
node ~/.openclaw/skills/planet/scripts/planet-api.js item-types
node ~/.openclaw/skills/planet/scripts/planet-api.js search \
  --start "2026-03-01T00:00:00Z" --end "2026-03-31T00:00:00Z" \
  --bbox "-122.5,37.7,-122.3,37.9" --max-cloud 0.1 --limit 5
node ~/.openclaw/skills/planet/scripts/planet-api.js stats \
  --start "2025-01-01T00:00:00Z" --end "2026-01-01T00:00:00Z" \
  --bbox "-122.5,37.7,-122.3,37.9" --interval month
node ~/.openclaw/skills/planet/scripts/planet-api.js thumbnail --id <item-id> --width 1024

# Tasking (read-only)
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-pricing --bbox "-77.04,38.89,-77.03,38.90"
node ~/.openclaw/skills/planet/scripts/planet-api.js imaging-windows \
  --bbox "-77.04,38.89,-77.03,38.90" --start "2026-04-10T00:00:00Z" --end "2026-04-17T00:00:00Z"
node ~/.openclaw/skills/planet/scripts/planet-api.js my-quota
```

---

## File Structure

```
planet-integration-demo/
+-- install.sh                         # Automated installer
+-- planet-proxy.py                    # Host-side API proxy (Tier 1)
+-- planet-integration-guide.md        # This guide
+-- policy/
|   +-- planet.yaml                    # Policy template
+-- skills/
    +-- planet/
        +-- SKILL.md                   # Agent skill definition
        +-- scripts/
            +-- planet-api.js          # Node.js API client
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Agent doesn't find the skill | Clear sessions: re-run `./install.sh` |
| `Planet proxy unreachable` | Check proxy: `curl http://127.0.0.1:9201/health` |
| `Credential load failed` | Verify `PLANET_API_KEY` in `~/.nemoclaw/credentials.json` |
| `401 Unauthorized` | API key is invalid; update in `credentials.json` (instant) |
| `403 Blocked` on tasking order | Expected -- order creation is blocked for safety |
| No search results | Expand date range, increase max-cloud, try broader bbox |

---

Created by **Tim Klawa** (tklawa@nvidia.com)
