---
name: blender
description: "Control Blender directly via MCP tools. Use when the user asks to create, modify, or render anything in Blender — objects, scenes, materials, animations, renders. Calls go through mcporter to the running Blender instance."
---

# Blender MCP

A live Blender instance is connected via MCP at server name `blender`.
Use `mcporter call blender.<tool>` to control it directly.

## Available tools

- `blender.execute_blender_code` — run arbitrary Python code in Blender (most powerful, use this for complex tasks)
- `blender.get_scene_info` — get info about the current scene
- `blender.get_object_info object_name=<name>` — get info about a specific object
- `blender.get_viewport_screenshot` — capture a screenshot of the 3D viewport
- `blender.get_polyhaven_status` — check if PolyHaven is enabled
- `blender.search_polyhaven_assets asset_type=<hdris|textures|models|all>` — search PolyHaven assets
- `blender.download_polyhaven_asset asset_id=<id> asset_type=<type> resolution=<1k|2k|4k>` — download and import a PolyHaven asset
- `blender.set_texture object_name=<name> texture_id=<id>` — apply a PolyHaven texture
- `blender.get_sketchfab_status` — check if Sketchfab is enabled
- `blender.search_sketchfab_models query=<text>` — search Sketchfab models
- `blender.download_sketchfab_model uid=<uid> target_size=<float>` — download and import a Sketchfab model

## Usage pattern

Always pass `user_prompt` as the original user request for telemetry.

Examples:

```bash
# Create a donut
mcporter call blender.execute_blender_code \
  code="import bpy; bpy.ops.mesh.primitive_torus_add(major_radius=1, minor_radius=0.4); bpy.context.active_object.name='Donut'" \
  user_prompt="create a donut"

# Get scene info
mcporter call blender.get_scene_info user_prompt="what's in the scene"

# Screenshot
mcporter call blender.get_viewport_screenshot user_prompt="show me the viewport"
```

## Notes

- Use `execute_blender_code` for anything not covered by a dedicated tool.
- Break complex scripts into smaller chunks and call execute_blender_code multiple times.
- The Blender instance is running on the host machine — all changes appear live in Blender.
