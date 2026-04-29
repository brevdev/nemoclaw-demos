---
name: nasa-apod
description: "NASA Astronomy Picture of the Day. Use when: user asks about space, astronomy, NASA photos, today's space image, celestial objects, nebulae, galaxies, planets, or wants to see a stunning space picture. Commands: curl calls to api.nasa.gov/planetary/apod. Today: curl -s 'https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY'. Specific date: curl -s 'https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&date=YYYY-MM-DD'. Date range: curl -s 'https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD'. Random: curl -s 'https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&count=N&thumbs=true'. Always include thumbs=true when fetching videos. NOT for: live telescope feeds, NASA mission control data, rocket launch schedules, or real-time ISS tracking."
metadata: { "openclaw": { "emoji": "🔭", "requires": { "bins": ["curl"] } } }
---

# NASA Astronomy Picture of the Day Skill

Fetch and explore NASA's Astronomy Picture of the Day archive — stunning space imagery with expert explanations, dating back to June 16, 1995.

## When to Use

- "What's today's astronomy picture?"
- "Show me NASA's space photo from my birthday"
- "Find space pictures from last week"
- "Show me 5 random NASA astronomy photos"
- "What did NASA feature on Christmas 2024?"
- "Let's start with space — show me something stunning"

## API Endpoint

Base URL: `https://api.nasa.gov/planetary/apod`

All requests use `api_key=DEMO_KEY` (free, no signup required).

### Today's picture

```bash
curl -s "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"
```

### Specific date

```bash
curl -s "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&date=2025-06-03"
```

Dates must be between 1995-06-16 and today. Format: YYYY-MM-DD.

### Date range

```bash
curl -s "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&start_date=2026-04-01&end_date=2026-04-07"
```

Returns an array of APOD entries for the range.

### Random selection

```bash
curl -s "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&count=5&thumbs=true"
```

Returns N random entries from the entire archive.

## Response Fields

| Field | Description |
|-------|-------------|
| `title` | Image/video title |
| `date` | Publication date (YYYY-MM-DD) |
| `explanation` | Expert description of the image |
| `url` | Standard resolution image or video URL |
| `hdurl` | High-resolution image URL (not present for videos) |
| `media_type` | Either `image` or `video` |
| `thumbnail_url` | Video thumbnail (only when `thumbs=true` and `media_type=video`) |
| `copyright` | Photographer/creator credit (absent if public domain) |

## Presenting Results

When presenting APOD results to the user:

1. **Title** — bold, prominent
2. **Date** — when it was featured
3. **Image URL** — provide the `hdurl` (or `url` if hdurl is absent) so the user can view it
4. **Explanation** — summarize in your own words, then offer the full NASA explanation
5. **Copyright** — credit the creator if the field is present

For videos (`media_type=video`): note it's a video and provide the `url` (usually YouTube). If `thumbnail_url` is available, mention that too.

## Multi-Entry Formatting

When presenting multiple entries (date range or random), format as a numbered list with title, date, and a one-line summary. Then ask which one the user wants to explore in detail.

## Comparison Prompts

After fetching multiple images, the user may ask you to compare them. Reason about:
- Subject matter (galaxy vs nebula vs planet vs Earth observation)
- Visual characteristics described in the explanations
- Scientific significance
- Time span between the photos

## Rate Limits

DEMO_KEY allows 50 requests/day and 30 requests/hour per IP. More than enough for a demo session.

## Safety

This skill is read-only. It fetches publicly available NASA data. No authentication secrets, no cost, no side effects.
