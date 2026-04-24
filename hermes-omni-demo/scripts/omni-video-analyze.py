#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Nemotron Omni video analysis — sends the full video to Omni in one API call.

This script is designed to run INSIDE a NemoClaw sandbox. It calls the openshell
gateway's inference route at https://inference.local/v1 instead of hitting
integrate.api.nvidia.com directly. The gateway injects the NVIDIA API key and
proxies the request out, so no key ever needs to exist inside the sandbox.

The `model` field is ignored by the gateway — it rewrites all requests to
whatever `openshell inference set` was pointed at (set Omni for this cookbook).

Practical payload ceiling: ~9 MB of base64-encoded video per call (gateway body
cap). That's roughly 2 minutes of 480p or 1 minute of 720p. Longer videos need
to be trimmed client-side.

Modes:
    analyze     Describe what's happening in the video (default)
    transcript  Extract audio captions as JSON with timestamps

Usage:
    python3 omni-video-analyze.py /path/to/video.mp4
    python3 omni-video-analyze.py /path/to/video.mp4 "What topics are covered?"
    python3 omni-video-analyze.py /path/to/video.mp4 --mode transcript
"""
import sys, json, base64, urllib.request, os, subprocess, re, argparse, struct

API_URL = "https://inference.local/v1/chat/completions"
# Model field is rewritten by the openshell gateway based on its configured
# inference route. Kept here only as a documentation hint.
MODEL = "private/nvidia/nemotron-3-nano-omni-reasoning-30b-a3b"


def get_duration(video_path: str):
    """Get video duration in seconds. Uses ffprobe if present, else parses MP4 mvhd atom.
    Returns None if duration can't be determined (analysis still proceeds)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout:
            return float(json.loads(result.stdout)["format"]["duration"])
    except FileNotFoundError:
        pass
    try:
        return _mp4_duration_pure_python(video_path)
    except Exception:
        return None


def _mp4_duration_pure_python(path: str) -> float:
    """Parse MP4/MOV duration from the mvhd atom without ffprobe."""
    with open(path, "rb") as f:
        data = f.read()

    def scan(buf, offset, end):
        while offset < end - 8:
            size = struct.unpack(">I", buf[offset:offset + 4])[0]
            atype = buf[offset + 4:offset + 8]
            if size == 1:
                size = struct.unpack(">Q", buf[offset + 8:offset + 16])[0]
                hdr = 16
            else:
                hdr = 8
            if size <= 0:
                break
            if atype == b"moov":
                inner = scan(buf, offset + hdr, offset + size)
                if inner is not None:
                    return inner
            elif atype == b"mvhd":
                version = buf[offset + hdr]
                body = offset + hdr + 4
                if version == 1:
                    timescale = struct.unpack(">I", buf[body + 16:body + 20])[0]
                    duration = struct.unpack(">Q", buf[body + 20:body + 28])[0]
                else:
                    timescale = struct.unpack(">I", buf[body + 8:body + 12])[0]
                    duration = struct.unpack(">I", buf[body + 12:body + 16])[0]
                return duration / timescale if timescale else 0.0
            offset += size
        return None

    result = scan(data, 0, len(data))
    if result is None:
        raise RuntimeError(f"Could not determine duration of {path}")
    return result


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def call_omni(video_path: str, prompt: str, max_tokens: int = 2048) -> dict:
    """Send the whole video to Omni via the openshell gateway."""
    with open(video_path, "rb") as f:
        video_b64 = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(video_path)[1].lstrip(".") or "mp4"
    mime = f"video/{ext}"

    payload = json.dumps({
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{video_b64}"}},
            ],
        }],
        "max_tokens": max_tokens,
    }).encode()

    size_mb = len(payload) / 1e6
    if size_mb > 9:
        print(
            f"Warning: payload is {size_mb:.1f} MB. The openshell gateway caps "
            "inference bodies around ~9 MB; the call may fail with an SSL EOF. "
            "Trim the video with ffmpeg if needed.",
            file=sys.stderr,
        )

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
    )

    size_kb = len(video_b64) // 1024
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())

    msg = data["choices"][0]["message"]
    return {
        "content": msg["content"].strip(),
        "reasoning": (msg.get("reasoning_content") or msg.get("reasoning") or "").strip(),
        "tokens": data["usage"]["total_tokens"],
        "payload_kb": size_kb,
    }


def analyze_video(video_path: str, prompt: str = None):
    if not os.path.exists(video_path):
        sys.exit(f"File not found: {video_path}")

    duration = get_duration(video_path)
    size_mb = os.path.getsize(video_path) / 1e6
    print(f"Video: {video_path}")
    if duration is not None:
        print(f"Duration: {fmt_time(duration)} ({duration:.1f}s), {size_mb:.1f}MB")
    else:
        print(f"Size: {size_mb:.1f}MB")

    if prompt is None:
        prompt = (
            "Watch this video carefully and describe in detail what is happening: "
            "what you see, what you hear, what actions take place, and the overall "
            "content or purpose of the video."
        )

    print("\nSending to Nemotron Omni 30B...")
    result = call_omni(video_path, prompt, max_tokens=4096)

    if result["reasoning"]:
        print("\n--- Omni Reasoning ---")
        print(result["reasoning"])
    print("\n--- Omni Analysis ---")
    print(result["content"])
    print(f"\n[{result['tokens']} tokens, {result['payload_kb']}KB payload]")
    return result


def transcript_video(video_path: str):
    if not os.path.exists(video_path):
        sys.exit(f"File not found: {video_path}")

    duration = get_duration(video_path)
    size_mb = os.path.getsize(video_path) / 1e6
    print(f"Video: {video_path}")
    if duration is not None:
        print(f"Duration: {fmt_time(duration)} ({duration:.1f}s), {size_mb:.1f}MB")
    else:
        print(f"Size: {size_mb:.1f}MB")
    print("Mode: transcript\n")

    transcript_prompt = (
        "Listen carefully to ALL speech and audio in this video. "
        "Transcribe everything that is said. Output ONLY a JSON array of objects "
        "with this exact format — no other text before or after the JSON:\n"
        "[\n"
        '  {"timestamp": "M:SS", "speaker": "Speaker Name or Label", "text": "what they said"},\n'
        "  ...\n"
        "]\n"
        "Rules:\n"
        "- Timestamps relative to the start of the video\n"
        '- Use descriptive speaker labels (e.g., "Professor", "Student", "Narrator")\n'
        "- Transcribe speech verbatim — do not summarize\n"
        "- If there is no speech, return an empty array: []\n"
        "- Output ONLY valid JSON, nothing else"
    )

    print("Sending to Nemotron Omni 30B for transcription...")
    result = call_omni(video_path, transcript_prompt, max_tokens=8192)
    captions = _parse_transcript_json(result["content"])

    output = {
        "video": video_path,
        "duration": fmt_time(duration) if duration is not None else None,
        "duration_seconds": round(duration, 1) if duration is not None else None,
        "total_tokens": result["tokens"],
        "transcript": captions if captions is not None else [
            {"timestamp": "0:00", "speaker": "unknown", "text": result["content"], "raw": True}
        ],
    }

    print(f"\n{'=' * 60}")
    print("TRANSCRIPT OUTPUT")
    print(f"{'=' * 60}")
    print(json.dumps(output, indent=2))
    n = len(output["transcript"])
    print(f"\n[{result['tokens']} tokens, {n} caption(s)]")
    return output


def _parse_transcript_json(text: str):
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze video with Nemotron Omni 30B (full video, one API call)",
    )
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--mode", "-m", choices=["analyze", "transcript"],
                        default="analyze",
                        help="Mode: analyze (default) or transcript (JSON captions)")
    parser.add_argument("prompt", nargs="?", default=None,
                        help="Custom prompt (optional, analyze mode only)")

    args = parser.parse_args()

    if args.mode == "transcript":
        transcript_video(args.video)
    else:
        analyze_video(args.video, args.prompt)
