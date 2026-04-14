# PST Mail Agent for OpenClaw (Outlook PST via Aspose.Email + MCP)

Give your OpenClaw agent the ability to read, search, and draft emails directly from an Outlook `.pst` file — all through a secure MCP server running on the host. The sandbox can call 7 natural-language tools while remaining completely isolated from the host filesystem and Python runtime.

> **What is a `.pst` file?**
> A `.pst` (Personal Storage Table) file is an Outlook data file that stores a local copy of your mailbox — emails, contacts, calendar items, and folder structure. You typically encounter one when:
> - You export or archive mail from Outlook ("File → Open & Export → Import/Export")
> - Your organization archives old mailboxes off the live Exchange/M365 server
> - You receive a mailbox export from IT or legal for review
>
> **Limitations to be aware of:**
> This demo is designed for **read-only archive search**. The `.pst` file is a static snapshot — it is not synced with a live Outlook account. That means:
> - Search, read, and extract operations work great and give accurate results for the archived data.
> - The `draft_email` tool writes a draft file locally (`.msg`/`.eml`) but does **not** send it or sync it back to Outlook. If you need to actually send the draft, you must open it in Outlook separately.
> - Any changes (drafts, folder moves) you make to the `.pst` won't be reflected in your live Outlook inbox unless you explicitly re-import.

---

## What You Get

| Capability | Tool |
|---|---|
| **Natural-language dispatcher** | `pst_agent` — LLM routes any free-text query to the right tool automatically |
| **Full email + contact extract** | `extract_pst` — dump all emails and contacts from the PST |
| **Search by sender** | `search_emails_by_sender` — filter by From address or name fragment |
| **Latest emails** | `get_latest_emails` — N most recent messages, sorted by date descending |
| **Folder tree** | `list_pst_folders` — folder hierarchy with item counts |
| **Search by subject** | `search_emails_by_subject` — keyword match on the Subject line |
| **Draft email** | `draft_email` — compose an unsent MSG or EML draft |

The server runs on the host on port **9003**. The sandbox reaches it through a network policy that allows only specific binaries to call specific hosts and ports — nothing else can cross the boundary.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Running NemoClaw sandbox | A working OpenShell sandbox with OpenClaw. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Python 3 on the host | For the MCP server and Aspose.Email library. |
| Aspose.Email for Python via .NET | See [installation instructions](#installation) below. |
| NVIDIA API key | Required for the `ChatNVIDIA` LLM dispatcher (`pst_agent`). Set as `NVIDIA_API_KEY` in `.env` or the environment. |
| Outlook PST file | Download the sample `Outlook.pst` (see [Data setup](#data-setup)) or point the server at your own PST. |

---

## Installation

The MCP server depends on `Aspose.Email-for-Python-via-NET`, which is not a standard pip package. Follow the installation steps from the upstream repository:

> **[To install you will need to do →](https://github.com/Zenodia/Aspose.Email-Python-Dotnet/blob/zcharpy/mcp-example/README.md#to-install-you-will-need-to-do)**

Once Aspose.Email is installed, create a local virtual environment with `uv` and install the remaining MCP server dependencies into it:

```bash
# Create a local venv (one-time)
uv venv .venv

# Install all host-side dependencies
uv pip install -r outlook-pst-demo/requirements-mcp.txt
uv pip install fastmcp langchain-nvidia-ai-endpoints colorama
```

> **Don't have `uv`?** Install it with `pip install uv` or follow the [uv docs](https://docs.astral.sh/uv/getting-started/installation/).

`requirements-mcp.txt` installs:

```
python-dotenv>=1.0
Aspose.Email-for-Python-via-NET
```

---

## Data Setup

Download the sample PST file into the `Data/` folder:

```bash
# From the outlook-pst-demo directory
mkdir -p Data
# Download Outlook.pst from the Aspose.Email Python example repository
```

> **[Download toy example Outlook.pst →](https://github.com/aspose-email/Aspose.Email-Python-Dotnet/blob/master/Examples/Data/Outlook.pst)**

Place the downloaded file at:

```
outlook-pst-demo/
└── Data/
    └── Outlook.pst
```

To use your own PST file instead, update the `DEFAULT_PST` path at the top of `extract_pst_mcp_server_llm.py`:

```python
DEFAULT_PST = "/absolute/path/to/your/mailbox.pst"
```

---

## Part 1: Start the MCP Server (on the Host)

```bash
cd outlook-pst-demo
python extract_pst_mcp_server_llm.py
```

The server listens at `http://0.0.0.0:9003/mcp` by default. Override with environment variables:

| Variable | Default | Description |
|---|---|---|
| `NVIDIA_API_KEY` | *(required)* | NVIDIA API key — needed **on the host** because the MCP server itself calls `ChatNVIDIA` to interpret free-text queries via the `pst_agent` dispatcher tool. The sandbox never touches this key. |
| `MCP_EXTRACT_PST_HOST` | `0.0.0.0` | Bind host |
| `MCP_EXTRACT_PST_PORT` | `9003` | Bind port |
| `MCP_EXTRACT_PST_PATH` | `/mcp` | URL path |
| `MCP_EXTRACT_PST_LOG_LEVEL` | `debug` | Log verbosity |
| `ASPOSE_EMAIL_LICENSE_PATH` | *(optional)* | Path to Aspose `.lic` file |

Set `NVIDIA_API_KEY` before starting the server — either export it in your shell or create a `.env` file in the `outlook-pst-demo/` directory:

```bash
# Option A — shell export (current session only)
export NVIDIA_API_KEY="nvapi-..."

# Option B — .env file (loaded automatically by the server via python-dotenv)
echo 'NVIDIA_API_KEY="nvapi-..."' > outlook-pst-demo/.env
```

---

## Part 2: Apply the Sandbox Policy

The sandbox cannot reach the host MCP server unless the network policy explicitly allows it. Apply `sandbox_policy.yaml` from this demo folder:

```bash
openshell policy set <sandbox_name> --policy outlook-pst-demo/sandbox_policy.yaml --wait
```

Verify the policy was applied:

```bash
openshell policy get <sandbox_name> --full
```

> **Tip:** To capture your current policy before modifying it, run:
> ```bash
> openshell policy get <sandbox_name> --full 2>&1 | sed -n '/^---$/,$ p' | tail -n +2 > current-policy.yaml
> ```

---

## Part 3: Install the PST Mail Skill

Upload the skill into the sandbox so OpenClaw can discover and use it:

```bash
openshell sandbox upload <sandbox_name> \
  outlook-pst-demo/pst-mail-skills \
  /sandbox/.openclaw/workspace/skills/
```

> The path `/sandbox/.openclaw/workspace/skills/` exists once OpenClaw is onboarded inside the sandbox.

### Install `fastmcp` inside the sandbox

The skill's client script (`scripts/pst_client.py`) requires `fastmcp` to connect to the MCP server. Install it inside the sandbox:

```bash
nemoclaw my-assistant connect
# Inside the sandbox:
python3 -m venv /sandbox/.venv
/sandbox/.venv/bin/pip install fastmcp
```

> **Why the venv?** The sandbox policy (`sandbox_policy.yaml`) restricts PyPI access to specific trusted binaries. A bare `pip install` using the system Python would be blocked. The relevant section of the policy is:
>
> ```yaml
> pypi:
>   name: pypi
>   endpoints:
>     - { host: pypi.org, port: 443 }
>     - { host: files.pythonhosted.org, port: 443 }
>     - { host: github.com, port: 443 }
>     - { host: objects.githubusercontent.com, port: 443 }
>     - { host: api.github.com, port: 443 }
>     - { host: downloads.python.org, port: 443 }
>   binaries:
>     - { path: /sandbox/.venv/bin/python }
>     - { path: /sandbox/.venv/bin/python3 }
>     - { path: /sandbox/.venv/bin/pip }
>     - { path: /app/.venv/bin/python }
>     - { path: /app/.venv/bin/python3 }
>     - { path: /app/.venv/bin/pip }
>     - { path: /usr/local/bin/uv }
>     - { path: "/sandbox/.uv/python/**" }
> ```
>
> Only the binaries listed above can reach PyPI — always install into `/sandbox/.venv` (or use `uv`) to stay within the allowed binaries.

### Verify the skill is wired up

Still inside the sandbox, confirm the skill files are in place:

```bash
ls /sandbox/.openclaw/workspace/skills/pst-mail-skills/
# Expected:
#   SKILL.md
#   scripts/
#     pst_client.py
```

Do a quick connectivity check against the MCP server on the host:

```bash
python3 /sandbox/.openclaw/workspace/skills/pst-mail-skills/scripts/pst_client.py \
  list_pst_folders '{}'
```

You should see the folder tree from `Outlook.pst`. If you get a connection error, check that the MCP server is running on the host and that the policy was applied correctly.

---

## Example — PST Mail Agent server (`extract_pst_mcp_server_llm.py`)

The server runs on the host and exposes exactly 7 tools. You can remove any tool on the server side without interrupting the MCP client — OpenClaw inside the sandbox accesses only what is exposed via the custom skill.

```
pst_agent                 ← natural-language dispatcher (LLM routes internally)
extract_pst               ← full extract of emails + contacts
search_emails_by_sender   ← filter by From address
get_latest_emails         ← N most recent, sorted by date
list_pst_folders          ← folder tree with counts
search_emails_by_subject  ← keyword search on Subject
draft_email               ← compose an unsent MSG/EML draft
```

Only these are callable from the network — everything else is private:

```python
# Only these are callable from the network — everything else is private
@mcp.tool()
async def pst_agent(query: str) -> str: ...

@mcp.tool()
async def search_emails_by_sender(sender: str, ...) -> str: ...

# helper functions below are never exposed
def _search_by_sender_sync(...): ...   # internal only
def _get_latest_emails_sync(...): ...  # internal only
```

---

## Security Model

Security is enforced at two independent layers. Both must be satisfied for the sandbox to reach any PST data.

### Layer 1 — Tool surface (`extract_pst_mcp_server_llm.py`)

The server process has full access to the host: filesystem, environment variables, subprocesses, and the Aspose library. None of that is reachable from the sandbox. The sandbox can only call the 7 decorated `@mcp.tool()` functions over HTTP — all internal helpers are invisible to the network.

### Layer 2 — `sandbox_policy.yaml` (network-level)

Even with a minimal tool surface, the sandbox cannot reach the host unless the policy file explicitly allows it. Apply the policy with:

```bash
openshell policy set <sandbox_name> --policy sandbox_policy.yaml --wait
```

The relevant block opens outbound HTTP from the sandbox to the PST MCP server on port 9003 only:

```yaml
network_policies:
  mcp_server_host:
    name: mcp_server_host
    endpoints:
      - host: host.openshell.internal   # PST mail agent (port 9003)
        port: 9003
        allowed_ips: [172.17.0.1]
      - host: 127.0.0.1
        port: 9003
    binaries:                           # only these binaries may make those calls
      - { path: /usr/local/bin/claude }
      - { path: /sandbox/.venv/bin/python }
      - { path: /sandbox/.venv/bin/python3 }
      - { path: /sandbox/test_mcp_client/.venv/bin/python }
      - { path: /sandbox/test_mcp_client/.venv/bin/python3 }
      - { path: "/sandbox/.uv/python/**" }
```

Nothing outside those hosts, ports, and binaries can initiate a connection to the host — even if malicious code runs inside the sandbox.

### Combined security guarantee

```
┌─────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                               │
│                                                             │
│   extract_pst_mcp_server_llm.py  (port 9003)               │
│   ├── @mcp.tool() pst_agent          ← reachable           │
│   ├── @mcp.tool() search_emails_*    ← reachable           │
│   ├── _internal_helper()             ← NOT reachable       │
│   └── os / subprocess / file I/O    ← NOT reachable        │
└──────────────────────────────┬──────────────────────────────┘
                               │  HTTP only to port 9003
                               │  policy: sandbox_policy.yaml
┌──────────────────────────────┴──────────────────────────────┐
│  SANDBOX (OpenClaw / OpenShell)                             │
│                                                             │
│   pst-mail-skills/scripts/pst_client.py                    │
│   └── calls pst_agent("natural language query")            │
└─────────────────────────────────────────────────────────────┘
```

---

## Trying It Out

Connect to your sandbox and try these prompts:

### Reading email

- "Show me the latest 10 emails"
- "Get the 5 most recent messages from my Inbox folder"
- "List all the folders in my mailbox with counts"
- "Extract all emails and contacts from the PST"

### Searching

- "Find all emails from alice@example.com"
- "Search for emails with 'project kickoff' in the subject"
- "Show emails received between 2024-01-01 and 2024-03-31"

### Drafting

- "Draft an email to bob@example.com with subject 'Follow-up' and save it to /tmp/draft.msg"
- "Compose a reply to the last email from the CEO and save as EML"

### Natural language (routed automatically via `pst_agent`)

- "Who sent me the most emails last month?"
- "What is the folder structure of my mailbox?"
- "Show me everything from marketing@company.com"

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError: aspose` | Follow the [Aspose.Email installation guide](https://github.com/Zenodia/Aspose.Email-Python-Dotnet/blob/zcharpy/mcp-example/README.md#to-install-you-will-need-to-do) exactly |
| `NVIDIA_API_KEY` not set | Export the key in your shell or add it to a `.env` file in the demo directory |
| `FileNotFoundError` on PST path | Check that `Outlook.pst` is in `Data/` or update `DEFAULT_PST` in the server file |
| Agent doesn't find the skill | Disconnect and reconnect to the sandbox, or clear agent sessions |
| `l7_decision=deny` in logs | Policy not applied — re-run `openshell policy set` and check `openshell policy get --full` |
| Sandbox can't reach port 9003 | Confirm the server is running on the host (`curl http://localhost:9003/mcp`) and the policy allows `host.openshell.internal:9003` |
| LLM response is not valid JSON | The `pst_agent` strips `<think>` tags and retries parsing; if it still fails, pass a more explicit query |

---

## File Structure

```
outlook-pst-demo/
+-- extract_pst_mcp_server_llm.py   # Host-side MCP server (7 tools, LLM dispatcher)
+-- requirements-mcp.txt            # pip dependencies for the MCP server
+-- sandbox_policy.yaml             # Network policy — opens port 9003 to the sandbox
+-- outlook-pst-openclaw-demo.md    # This guide
+-- Data/
|   +-- Outlook.pst                 # Sample PST file (download separately)
+-- pst-mail-skills/
    +-- SKILL.md                    # OpenClaw skill definition and usage examples
    +-- scripts/
        +-- pst_client.py           # MCP client — calls the 7 tools on port 9003
```

---

Created by **zcharpy**
