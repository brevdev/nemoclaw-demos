# nemoclaw-demos

A repository of guides with examples you can take after a successful [hello-world setup of NemoClaw](https://github.com/NVIDIA/NemoClaw).

## Demos

| Demo | Description |
|------|-------------|
| [**vlm-demo**](vlm-demo/vlm-subagent-guide.md) | Zero-to-hero cookbook for adding a Vision Language Model (VLM) sub-agent to OpenClaw using Nemotron Omni. No GPU required. |
| [**openclaw-omni-demo**](openclaw-omni-demo/README.md) | Compact reference for the NemoClaw + Omni vision sub-agent setup with raw config files (`openclaw.json`, `policy.yaml`, `TOOLS.md`). |
| [**speech-demo**](speech-demo/speech-stt-guide.md) | Zero-to-hero cookbook for adding speech-to-text to OpenClaw using NVIDIA Parakeet. No GPU required. |
| [**blender-demo**](blender-demo/blender-openclaw-guide.md) | Connecting Blender to OpenClaw for natural language 3D interactions via MCP. |
| [**gog-demo**](gog-demo/gog-openclaw-guide.md) | Connecting Google Workspace (Gmail, Calendar, Drive) to OpenClaw via the `gog` CLI. |
| [**google-workspace-demo**](google-workspace-demo/google-workspace-guide.md) | Full Google Workspace integration (Gmail, Calendar, Drive, Sheets, Contacts, Tasks) with Tier 1 push daemon security. |
| [**planet-integration-demo**](planet-integration-demo/planet-integration-guide.md) | Planet satellite imagery catalog, tasking cost estimation, and satellite pass availability with Tier 1 proxy security. |
| [**wakeup-demo**](wakeup-demo/nemoclaw-wakeup-guide.md) | Host-controlled scheduled wakeup for periodic agent tasks (email checks, calendar, etc.) with sandbox security enforcement. |
| [**nasa-apod-demo**](nasa-apod-demo/nasa-apod-guide.md) | NASA Astronomy Picture of the Day |
| [**hermes-omni-demo**](hermes-omni-demo/hermes-omni-guide.md) | Zero-to-hero cookbook for a multimodal agent: Hermes + Nemotron 3 Nano Omni + NemoClaw policy. Video (short + chunked long), audio, PDF, image, and Wikipedia lookups behind a deny-by-default L7 proxy — plus an optional React + FastAPI web UI for live demos. No GPU required. |

## Official Resources

- [For users without local hardware: NemoClaw Brev Launchable](https://build.nvidia.com/nemoclaw)
- [For users with a Spark: OpenClaw Spark Playbook](https://build.nvidia.com/spark/openclaw) or [OpenShell Spark Playbook](https://build.nvidia.com/spark/openshell)
