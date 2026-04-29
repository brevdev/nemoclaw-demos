# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

---

## Agent-Specific Instructions

### If you are `main` (the primary agent)

You are text-only. You CANNOT see images with the `read` tool. NEVER use `read` on image files — you will get raw bytes, not visual content.

To analyze any image, delegate to the vision-operator sub-agent using `sessions_spawn`. Always use the full path under `/sandbox/.openclaw-data/workspace/` (NOT `/sandbox/.openclaw/workspace`):

```json
{
  "agentId": "vision-operator",
  "message": "Describe the image at /sandbox/.openclaw-data/workspace/frame_000270.jpg in detail"
}
```

Use `agents_list` to confirm vision-operator is available before spawning.

Delegate ANY task involving images (JPG, PNG, etc.), video frames, or visual content to vision-operator.

When writing files, always use `/sandbox/.openclaw-data/workspace/` as the base path. NEVER use `/sandbox/.openclaw/workspace`.

### If you are `vision-operator` (the vision sub-agent)

You ARE the vision-capable agent. You CAN see images. You use the Nemotron-3 Nano Omni model which supports image input.

To analyze an image, use the `read` tool with the **exact file path** provided in your task message. You will see the image contents directly.

IMPORTANT:
- The workspace is at `/sandbox/.openclaw-data/workspace/`. ALL reads and writes MUST use this path. NEVER use `/sandbox/.openclaw/workspace` — it does not exist and will fail.
- When writing output files (e.g. `image-description.md`), always write to `/sandbox/.openclaw-data/workspace/` (e.g. `/sandbox/.openclaw-data/workspace/image-description.md`).
- Do NOT `read` directories. Only `read` the specific image file path (e.g. `/sandbox/.openclaw-data/workspace/frame_000270.jpg`).
- Do NOT try to use `sessions_spawn` — you do not have it and do not need it.
- You are the final destination for image analysis tasks. Analyze the image yourself and return your findings directly.
