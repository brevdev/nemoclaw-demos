---
name: planet
description: "Planet satellite imagery catalog, tasking cost estimation, and satellite pass availability. Use when: user asks about satellite imagery, Earth observation data, available scenes, cloud cover, imagery statistics, tasking cost, satellite pass schedule, imaging windows, tasking orders, captures, account quota, or wants a satellite thumbnail. Commands: node ~/.openclaw/skills/planet/scripts/planet-api.js <command>. Catalog: item-types, search --start ISO --end ISO --bbox W,S,E,N [--max-cloud 0.1] [--type PSScene] [--limit 10], item --id <id>, assets --id <id>, stats --start ISO --end ISO --bbox W,S,E,N [--interval month], thumbnail --id <id> [--width 512], tile-url --id <id>. Tasking (read-only): tasking-pricing --bbox W,S,E,N [--product X], imaging-windows --bbox W,S,E,N --start ISO --end ISO, tasking-orders [--status S], tasking-order --id <id>, tasking-captures [--order id]. Account: my-quota. NOT for: placing tasking orders, canceling orders, downloading full imagery, satellite tasking requests, or any action that incurs charges."
metadata: { "openclaw": { "emoji": "🛰️", "requires": { "bins": ["node"] } } }
---

# Planet Satellite Imagery Skill

Search Planet's satellite imagery catalog, estimate tasking costs, check satellite pass availability, and view account quota.

## When to Use

- "What satellite imagery is available over San Francisco?"
- "How much would it cost to task a satellite over the Pentagon?"
- "When is the next satellite pass over Washington DC?"
- "Find clear imagery (low cloud cover) over London in March 2026"
- "Show me my existing tasking orders"
- "What quota do I have remaining?"
- "Download a thumbnail of that scene and email it to me"

## Catalog Commands

All commands use: `node ~/.openclaw/skills/planet/scripts/planet-api.js <command>`

### List available item types

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js item-types
```

Returns all satellite constellations/item types (PSScene, SkySatScene, etc.).

### Search the catalog

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js search --start "2026-03-01T00:00:00Z" --end "2026-03-31T00:00:00Z" --bbox "-122.5,37.7,-122.3,37.9" --max-cloud 0.1 --limit 5
node ~/.openclaw/skills/planet/scripts/planet-api.js search --type SkySatScene --start "2026-01-01T00:00:00Z" --end "2026-04-01T00:00:00Z" --bbox "-73.99,40.75,-73.95,40.77"
node ~/.openclaw/skills/planet/scripts/planet-api.js search --start "2026-04-01T00:00:00Z" --end "2026-04-07T00:00:00Z" --downloadable
```

Search options: `--type` (default PSScene), `--start`, `--end`, `--bbox W,S,E,N`, `--max-cloud` (0-1), `--geometry` (GeoJSON), `--limit`, `--downloadable`.

### Get item details

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js item --id 20260301_180000_00_2489 --type PSScene
```

### List item assets

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js assets --id 20260301_180000_00_2489 --type PSScene
```

### Get statistics

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js stats --start "2025-01-01T00:00:00Z" --end "2026-01-01T00:00:00Z" --bbox "-122.5,37.7,-122.3,37.9" --interval month
```

### Generate tile URL

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js tile-url --id 20260301_180000_00_2489 --type PSScene
```

### Download thumbnail

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js thumbnail --id 20260301_180000_00_2489 --type PSScene --width 1024
```

Downloads a PNG thumbnail to `/tmp/planet-thumb-{id}.png`. Use with gog's `--attach` flag to email the image.

### List saved searches

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js searches --limit 5
```

## Tasking Commands (read-only, no orders placed, no charges)

### Estimate tasking cost

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-pricing --bbox "-77.04,38.89,-77.03,38.90"
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-pricing --bbox "-122.5,37.7,-122.3,37.9" --product SkySatCollect
```

Returns estimated quota cost, pricing model, area in km2, and multipliers. Does NOT place an order.

### Check satellite pass availability (imaging windows)

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js imaging-windows --bbox "-77.04,38.89,-77.03,38.90" --start "2026-04-10T00:00:00Z" --end "2026-04-17T00:00:00Z"
node ~/.openclaw/skills/planet/scripts/planet-api.js imaging-windows --bbox "-122.5,37.7,-122.3,37.9" --max-cloud 0.3
```

Returns available satellite pass windows with cloud forecast, off-nadir angle, GSD, satellite type, and per-window pricing. This is an async search (submits, then polls for results). Does NOT place an order.

### List existing tasking orders

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-orders
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-orders --status active --limit 5
```

### Get tasking order details

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-order --id <order-id>
```

### List tasking captures

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-captures
node ~/.openclaw/skills/planet/scripts/planet-api.js tasking-captures --order <order-id> --limit 20
```

## Account Commands

### Show quota and products

```bash
node ~/.openclaw/skills/planet/scripts/planet-api.js my-quota
```

Returns products with total, used, and remaining quota.

## Safety

This skill is read-only for tasking. It can estimate costs and check availability but CANNOT place orders, cancel orders, or incur any charges. The tasking-pricing and imaging-windows commands are preview/estimate endpoints only.
