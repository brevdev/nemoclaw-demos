---
name: parakeet-stt
description: >-
  Speech-to-text transcription using NVIDIA Parakeet. The service is already
  running on the host — do NOT install or start it. Use curl to call the API.
  Use when transcribing audio files, converting speech to text, or processing
  voice recordings.
---

# Parakeet STT (Speech-to-Text)

Transcribe audio files using the Parakeet STT service. The service is **already running on the host** — do NOT try to install, clone, or start it yourself.

## How to Transcribe

Use `curl` to send audio files to the Parakeet API. Replace `PARAKEET_URL` below with the actual service URL (e.g. `http://172.31.35.26:5092`) before uploading this file to the sandbox.

**IMPORTANT:** Do NOT try to install Parakeet, clone repos, run Docker, or start uvicorn. The service is already running externally. Just use curl.

### Transcribe to plain text

```bash
curl -s -X POST PARAKEET_URL/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "response_format=text"
```

### Transcribe with timestamps (JSON)

```bash
curl -s -X POST PARAKEET_URL/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "response_format=verbose_json"
```

### Generate subtitles (SRT)

```bash
curl -s -X POST PARAKEET_URL/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "response_format=srt"
```

## Response Formats

| Format | Output |
|--------|--------|
| `text` | Plain text transcription |
| `json` | `{"text": "..."}` |
| `verbose_json` | Segments with timestamps and words |
| `srt` | SRT subtitles |
| `vtt` | WebVTT subtitles |

## Supported Audio Formats

WAV, MP3, OGG, FLAC, M4A, WEBM

## Supported Languages (25)

English, Spanish, French, German, Italian, Portuguese, Polish, Russian,
Ukrainian, Dutch, Swedish, Danish, Finnish, Norwegian, Greek, Czech,
Romanian, Hungarian, Bulgarian, Slovak, Croatian, Lithuanian, Latvian,
Estonian, Slovenian

Language is auto-detected — no configuration needed.

## Notes

- Audio files must be in the workspace at `/sandbox/.openclaw-data/workspace/`
- The service runs on the host, not inside the sandbox
- No API key is needed
- If `PARAKEET_URL` is not set, check with the user for the service URL
