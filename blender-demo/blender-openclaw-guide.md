# Connecting Blender to OpenClaw in a NemoClaw Sandbox on DGX Spark

This guide walks you through connecting [Blender](https://www.blender.org/) to an OpenClaw agent running inside an OpenShell sandbox, all on the same DGX Spark. By the end, your AI agent will be able to create, modify, and render 3D objects in Blender on your behalf.

The connection uses **MCP (Model Context Protocol)** -- a standard that lets AI agents communicate with external tools. In this case, it gives OpenClaw a way to send commands to a running Blender instance.

## Prerequisites

This guide assumes you have a running OpenShell sandbox with OpenClaw on your DGX Spark.

| Requirement | Details |
|-------------|---------|
| Running OpenClaw sandbox | A working OpenShell sandbox with OpenClaw on your DGX Spark. |
| Blender installed on the Spark | [Blender](https://www.blender.org/download/) installed on the DGX Spark host. |
| Blender MCP addon | The `addon.py` file from [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp). This addon runs inside Blender and exposes its functionality over MCP. |
| mcp-proxy | A bridge that exposes blender-mcp as an HTTP/SSE endpoint. Installed via `uvx` (part of the [uv](https://github.com/astral-sh/uv) project) on the host. |
| mcporter | Download the npm package (`mcporter-<version>.tgz`) from the [mcporter releases page](https://github.com/steipete/mcporter/releases). |

## Part 1: Blender Setup (On the DGX Spark Host)

These steps are performed on the DGX Spark host, **outside** the sandbox.

### Step 1: Install the Blender MCP Addon

1. Download `addon.py` from [https://github.com/ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp).
2. Open Blender and go to **Edit > Preferences > Add-ons**.
3. Click **Install** and select the `addon.py` file.
4. Enable the addon by checking the box next to it. The addon will start listening on `localhost:9876`.

### Step 2: Verify the Addon is Running

In Blender, you should see a "BlenderMCP" panel in the sidebar (press **N** to toggle it). The panel should show the server status as running.

### Step 3: Start the MCP Proxy

The Blender addon speaks raw TCP, not MCP over HTTP. The mcp-proxy sits on the host and bridges the two: it runs blender-mcp (which talks to the addon via TCP) and exposes it as an HTTP/SSE endpoint that mcporter inside the sandbox can reach.

If you don't have `uvx` installed:
``` bash
pip install uv
```

Start the proxy:
``` bash
uvx mcp-proxy --host 0.0.0.0 --port 9877 uvx blender-mcp &
```

Verify it's running:
``` bash
curl -s http://localhost:9877/sse
```

## Part 2: Update the Sandbox Policy

Find your Spark's IP:
``` bash
hostname -I | awk '{print $1}'
```

Add the following block to your sandbox policy YAML under `network_policies`:

``` yaml
  blender_mcp:
    name: blender_mcp
    endpoints:
      - host: "{SPARK_IP}"
        port: 9877
        protocol: rest
        tls: passthrough
        enforcement: enforce
        access: full
    binaries:
      - { path: /usr/local/bin/python3* }
      - { path: /usr/bin/python3* }
      - { path: /usr/local/bin/python* }
      - { path: /usr/bin/node* }
      - { path: /usr/local/bin/node* }
      - { path: /usr/bin/curl* }
      - { path: /bin/bash* }
      - { path: /usr/bin/bash* }
```

Replace `{SPARK_IP}` with your DGX Spark's actual IP address.

> TIP to get the current policy you can run `openshell policy get my-assistant --full 2>&1 | sed -n '/^---$/,$ p' | tail -n +2 > current-policy.yaml`


Apply the updated policy:
``` bash
openshell policy set --policy your-policy.yaml {sandbox_name}
```

Verify:
``` bash
openshell logs
```

## Part 3: mcporter and Blender Skill Setup (Inside the Sandbox)

The sandbox filesystem is mostly read-only (`/` is read-only). Writable paths are `/sandbox` and `/tmp`, so all tools are installed under `/sandbox`.

### Step 1: Upload and Install mcporter

Download the npm package from the [mcporter releases page](https://github.com/steipete/mcporter/releases) on the host, then upload it into the sandbox:

``` bash
# On the host
openshell sandbox upload {sandbox_name} /path/to/mcporter-<version>.tgz /tmp/
openshell sandbox connect {sandbox_name}
```

Inside the sandbox, extract and set up mcporter:
``` bash
mkdir -p /sandbox/node_modules /sandbox/bin
tar -xzf /tmp/mcporter-<version>.tgz -C /sandbox/node_modules/
```

Create a wrapper script so mcporter can be called from anywhere:
``` bash
printf '#!/bin/bash\nexec node /sandbox/node_modules/package/dist/cli.js "$@"\n' \
  > /sandbox/bin/mcporter
chmod +x /sandbox/bin/mcporter
```

> **Note:** Check the extracted contents with `ls /sandbox/node_modules/package/dist/` if the path above doesn't match your version.

### Step 2: Create the mcporter Config

mcporter connects to the mcp-proxy running on the host over HTTP/SSE:

``` bash
mkdir -p ~/.mcporter
cat > ~/.mcporter/mcporter.json << 'EOF'
{
  "mcpServers": {
    "blender": {
      "type": "http",
      "baseUrl": "http://{SPARK_IP}:9877/sse"
    }
  }
}
EOF
```

Replace `{SPARK_IP}` with your DGX Spark's IP address.

### Step 3: Upload the Blender Skill

The Blender skill file teaches the OpenClaw agent what mcporter commands are available and how to call them. Without it, the agent won't know Blender exists. The skill file is located at [`blender-skill/SKILL.md`](blender-skill/SKILL.md) in this repository.

From the host, upload it into the sandbox:
``` bash
openshell sandbox upload {sandbox_name} \
  /path/to/blender-skill/SKILL.md \
  /sandbox/.openclaw/skills/blender/
```

### Step 4: Restart the Gateway

The OpenClaw gateway must be restarted to pick up the new skill. Add `/sandbox/bin` to PATH so the agent can find mcporter:

``` bash
openclaw gateway stop
sleep 3
PATH="/sandbox/bin:$PATH" \
nohup openclaw gateway run \
  --allow-unconfigured --dev \
  --bind loopback --port 18789 \
  --token hello \
  > /tmp/gateway.log 2>&1 &
```

### Step 5: Verify Blender MCP Connectivity

Test that mcporter can reach Blender:
``` bash
/sandbox/bin/mcporter call blender.get_scene_info \
  user_prompt="what is in the scene"
```

You should see JSON output describing the current Blender scene.

## Trying It Out

Open the OpenClaw web UI (the URL from `openclaw gateway run` output) and try prompts like:

- "Using mcporter to connect to blender, create a red cube in the center of the blender scene"

## Troubleshooting

| Issue | Fix |
|-------|-----|
| mcporter can't reach Blender | Verify the mcp-proxy is running on the host (`curl -s http://localhost:9877/sse`). Confirm `{SPARK_IP}` is correct in `mcporter.json`. |
| Agent doesn't know about Blender | Make sure `SKILL.md` was uploaded to `/sandbox/.openclaw/skills/blender/` and the gateway was restarted. |
| `l7_decision=deny` in OpenShell logs | The sandbox policy isn't allowing traffic. Check the `blender_mcp` block has the correct host/port and the binary making the connection is in the binaries list. |
| Blender addon not responding | Check the BlenderMCP panel in Blender's sidebar. Restart the addon if needed. |
