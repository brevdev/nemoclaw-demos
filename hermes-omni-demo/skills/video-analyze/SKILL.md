---
name: video-analyze
description: Analyze video files using Nemotron Omni 30B multimodal model. Sends the entire video to Omni in one API call and returns a description or audio transcript. Use whenever the user provides a video path and wants it analyzed, described, summarized, or transcribed.
version: 2.0.0
metadata:
  hermes:
    tags: [video, omni, multimodal, transcript, analysis, nemotron]
---

# Video Analysis with Nemotron Omni

Analyze videos using NVIDIA's Nemotron Omni 30B multimodal model. The script sends the whole video to Omni in a single API call — no chunking, no ffmpeg required.

## When to use this skill

- User provides a video path and asks to analyze, describe, or summarize it
- User asks "what's happening in this video", "transcribe the audio", "what does the speaker say"
- User wants a plain-English or structured analysis of video content

## CRITICAL — run the script via the `terminal` tool, NOT `execute_code`

The `execute_code` tool runs in an isolated Python environment without network access. Calling the script from there will fail with a confusing error. Always use the terminal tool.

## How to invoke

### Mode 1: Analyze (default) — describes content, actions, topics

**Default prompt:**
```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /path/to/video.mp4
```

**Custom prompt:**
```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /path/to/video.mp4 "Summarize the lecture in 3 bullets."
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /path/to/video.mp4 "What technical terms does the speaker use?"
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /path/to/video.mp4 "Focus on the last minute — what conclusion is reached?"
```

### Mode 2: Transcript — extracts audio captions as JSON

```bash
python3 /sandbox/.hermes-data/workspace/omni-video-analyze.py /path/to/video.mp4 --mode transcript
```

Transcript output format:
```json
{
  "video": "/path/to/video.mp4",
  "duration": "3:05",
  "transcript": [
    {"timestamp": "0:03", "speaker": "Professor", "text": "Today we will discuss..."},
    {"timestamp": "0:15", "speaker": "Professor", "text": "A unit vector is..."}
  ]
}
```

## Follow-up questions

Each call to `omni-video-analyze.py` re-sends the video to Omni. If the user asks a follow-up (e.g., you first answered "what's the conclusion?" and they then ask "who is the professor?"), **re-run the script with the new question**. Do not answer from memory of a previous narrow answer.

## Tips

- If a specific portion matters, say so in the prompt ("describe only the first 30 seconds", "focus on the conclusion")
- Custom prompts only work in analyze mode (not transcript mode)
- Transcript mode may return raw text instead of structured JSON if Omni has issues
- Practical size limit: tested working up to ~16 MB base64 payload (~3 min of 480p video) per call
