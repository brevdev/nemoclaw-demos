# zeroclaw `model_spawn` — Implementation Design

**Status**: ✅ IMPLEMENTED — `crates/zeroclaw-runtime/src/tools/model_spawn.rs` (zeroclaw-contrib commit 6ac998ec)  
**Canonical spec**: `docs/tools/model-spawn.md` in openclaw/openclaw  
**OpenClaw impl**: `src/agents/tools/model-spawn-tool.ts` (openclaw-contrib commit b450f1ca7d)  
**Author**: InvestorClaw team, 2026-04-14  
**Source**: Binary string analysis of zeroclaw 0.6.9

---

## What zeroclaw 0.6.9 Actually Has

### `model_routing_config` (`src/tools/model_routing_config.rs`)

Static configuration management for model routing. Actions: `get`, `list_hints`, `set_default`, `upsert_scenario`, `remove_scenario`, `upsert_agent`, `remove_agent`.

**Key limitation**: `set_default` writes to the config file on disk. It is **not** a live session-scoped override — it changes the global default for all subsequent turns across all sessions.

### `delegate` (`src/tools/delegate.rs`)

Delegate a subtask to a **pre-registered named agent profile**. The profile must exist (created via `model_routing_config.upsert_agent`) before the `delegate` call. Supports background execution and parallel named-agent dispatch.

**Key limitation**: No inline model specification. Cannot do `delegate(model="together/X", task="...")` without a prior registration step. No ephemeral semantics (profiles persist after the run).

### Gap vs. `model_spawn` spec

| Feature | Required by spec | zeroclaw today |
|---------|-----------------|----------------|
| `live` mode — session-scoped model override | ✅ | ❌ `set_default` is global config, not session-scoped |
| `spawn` single — inline model spec, ephemeral | ✅ | ❌ Requires pre-registered profile |
| `spawn` multi — parallel spawns, inline model per entry | ✅ | ❌ `delegate.agents[]` requires named profiles only |
| Clean-up after spawn (`cleanup="delete"`) | ✅ | ❌ No ephemeral semantics |

---

## What Needs to be Added to zeroclaw

### Change 1: Session-scoped model override (`live` mode)

Add a `live_switch` action to `model_routing_config`. Unlike `set_default`, this sets an **in-memory, session-local** override that applies only to the current conversation and is never written to config.

**New action: `model_routing_config(action="live_switch", provider, model)`**

**Implementation in `src/tools/model_routing_config.rs`**:

```rust
"live_switch" => {
    let provider = args.provider
        .ok_or_else(|| "provider required for live_switch")?;
    let model = args.model
        .ok_or_else(|| "model required for live_switch")?;

    ctx.session.pending_model_override = Some(ModelRef {
        provider: provider.clone(),
        model: model.clone(),
    });

    Ok(json!({
        "status": "ok",
        "action": "live_switch",
        "model": format!("{}/{}", provider, model),
        "switchPending": true,
        "note": format!("Model switch to {}/{} queued. Takes effect at the next clean turn boundary.", provider, model)
    }))
}
```

**Session state change** (`src/agent/agent.rs` or session struct):

```rust
pub struct SessionState {
    // ... existing fields ...

    /// Session-local model override set by model_spawn(mode="live").
    /// Consulted by the reliable provider before selecting the default model.
    /// Cleared on session reset (/new, /reset). Never persisted to config.
    pub pending_model_override: Option<ModelRef>,
}

pub struct ModelRef {
    pub provider: String,
    pub model: String,
}
```

**Provider dispatch change** (`src/providers/reliable.rs`):

```rust
// Before selecting the configured default model, check for a session override.
let (provider, model) = if let Some(ref override_ref) = ctx.session.pending_model_override {
    (override_ref.provider.clone(), override_ref.model.clone())
} else {
    (cfg.default_provider.clone(), cfg.default_model.clone())
};
```

---

### Change 2: Inline ephemeral spawns (`spawn` mode)

Extend the `delegate` tool to accept:
- An inline `model` parameter for one-off ephemeral runs
- An `ephemeral` flag (default `true` when `model` is provided inline) that discards the profile after the run
- A `spawns[]` array for parallel multi-model execution without named profiles

**Extended `delegate` params**:

```rust
pub struct DelegateArgs {
    // Existing:
    pub action:     Option<String>,        // delegate | check_result | list_results | cancel_task
    pub agent:      Option<String>,        // named profile (existing)
    pub task:       Option<String>,
    pub context:    Option<String>,
    pub background: Option<bool>,
    pub agents:     Option<Vec<String>>,   // parallel named agents (existing)
    pub task_id:    Option<String>,

    // New:
    pub model:           Option<String>,           // inline "provider/model-id"
    pub ephemeral:       Option<bool>,             // default true when model provided inline
    pub spawns:          Option<Vec<SpawnEntry>>,  // parallel inline spawns
    pub cleanup:         Option<String>,           // "delete" | "keep", default "delete"
    pub timeout_seconds: Option<u64>,
}

pub struct SpawnEntry {
    pub model:   String,
    pub task:    Option<String>,
    pub label:   Option<String>,
    pub context: Option<String>,
}
```

**Resolution logic in `src/tools/delegate.rs`**:

```rust
// Single inline spawn
if let Some(model_ref) = &args.model {
    if args.agent.is_some() {
        return Err("Provide either agent (named profile) or model (inline), not both.");
    }
    let task = args.task.ok_or("task required for inline spawn")?;
    let full_task = prepend_context(args.context.as_deref(), &task);
    let (provider, model_id) = split_first_slash(model_ref)?;

    let result = run_ephemeral_delegate(provider, model_id, &full_task, args.timeout_seconds, ctx).await?;

    return Ok(json!({
        "mode": "spawn",
        "multi": false,
        "model": model_ref,
        "status": if result.ok { "accepted" } else { "error" },
        "output": result.text
    }));
}

// Multi-model parallel inline spawns
if let Some(spawn_entries) = &args.spawns {
    if args.agent.is_some() || args.agents.is_some() {
        return Err("spawns[] is mutually exclusive with agent/agents (named profiles).");
    }
    let top_task = args.task.as_deref().unwrap_or("");
    let top_context = args.context.as_deref().unwrap_or("");

    let futures: Vec<_> = spawn_entries.iter().enumerate().map(|(idx, entry)| {
        let task    = entry.task.as_deref().unwrap_or(top_task);
        let context = entry.context.as_deref().unwrap_or(top_context);
        let label   = entry.label.as_deref().unwrap_or(&entry.model);
        let full_task = prepend_context(Some(context), task);
        async move {
            let (provider, model_id) = split_first_slash(&entry.model)?;
            let result = run_ephemeral_delegate(provider, model_id, &full_task, args.timeout_seconds, ctx).await?;
            Ok(json!({
                "label": label, "index": idx, "model": &entry.model,
                "status": if result.ok { "accepted" } else { "error" },
                "output": result.text
            }))
        }
    }).collect();

    let results = futures::future::join_all(futures).await;
    return Ok(json!({
        "mode": "spawn",
        "multi": true,
        "count": results.len(),
        "results": results
    }));
}
```

---

### `split_first_slash` helper

```rust
fn split_first_slash(ref_str: &str) -> Result<(String, String), String> {
    let trimmed = ref_str.trim();
    match trimmed.find('/') {
        Some(idx) if idx > 0 => {
            let provider = trimmed[..idx].to_string();
            let model_id = trimmed[idx + 1..].to_string();
            if model_id.is_empty() {
                Err(format!("model must be 'provider/model-id', got: {}", trimmed))
            } else {
                Ok((provider, model_id))
            }
        }
        _ => Err(format!(
            "model must include provider prefix (e.g. 'together/MiniMaxAI/MiniMax-M2.7'), got: {}",
            trimmed
        )),
    }
}
```

---

### ACP Protocol Extension (cross-system scenarios)

When OpenClaw orchestrates a zeroclaw session via ACP, `model_spawn` needs wire-level representation. Add `ModelSpawn` message variants to the ACP protocol in both systems:

**zeroclaw (`src/channels/acp_server.rs`)**:

```rust
pub enum AcpMessage {
    // ... existing variants ...
    ModelSpawnLive {
        model: String,   // "provider/model-id"
    },
    ModelSpawnTask {
        model:           String,
        task:            String,
        context:         Option<String>,
        cleanup:         String,         // "delete" | "keep"
        timeout_seconds: Option<u64>,
    },
    ModelSpawnParallel {
        spawns:          Vec<AcpSpawnEntry>,
        top_task:        Option<String>,
        top_context:     Option<String>,
        cleanup:         String,
        timeout_seconds: Option<u64>,
    },
}

pub struct AcpSpawnEntry {
    pub model:   String,
    pub task:    Option<String>,
    pub label:   Option<String>,
    pub context: Option<String>,
}
```

**OpenClaw (`src/agents/acp-spawn.ts`)**:

```typescript
type AcpModelSpawnMessage =
  | { type: "model_spawn_live";     model: string }
  | { type: "model_spawn_task";     model: string; task: string; context?: string; cleanup: string; timeout_seconds?: number }
  | { type: "model_spawn_parallel"; spawns: AcpSpawnEntry[]; top_task?: string; top_context?: string; cleanup: string; timeout_seconds?: number };

type AcpSpawnEntry = { model: string; task?: string; label?: string; context?: string };
```

**Note:** ACP messages are for cross-system transport only. Single-system sessions use the native in-process path and do not go through ACP.

---

## Files to Modify in zeroclaw

| File | Change |
|------|--------|
| `src/tools/model_routing_config.rs` | Add `live_switch` action |
| `src/tools/delegate.rs` | Add `model`, `ephemeral`, `spawns[]`, `cleanup`, `timeout_seconds` params |
| `src/agent/agent.rs` (or session struct) | Add `pending_model_override: Option<ModelRef>` |
| `src/providers/reliable.rs` | Check `session.pending_model_override` before selecting default |
| `src/channels/acp_server.rs` | Add `ModelSpawn*` ACP message variants |

---

## Conformance Tests

```python
# tests/model_spawn_conformance.py
# Run against both systems to validate spec conformance.

LIVE_SWITCH_TEST = {
    "mode": "live",
    "model": "together/MiniMaxAI/MiniMax-M2.7"
}
# Expected: status="ok", switchPending=True

SINGLE_SPAWN_TEST = {
    "mode": "spawn",
    "model": "together/MiniMaxAI/MiniMax-M2.7",
    "task": "Reply with exactly: CONFORMANCE_OK",
    "cleanup": "delete",
    "timeout_seconds": 30
}
# Expected: multi=False, status="accepted"

MULTI_SPAWN_TEST = {
    "mode": "spawn",
    "task": "Reply with your model name only.",
    "spawns": [
        {"model": "together/MiniMaxAI/MiniMax-M2.7", "label": "minimax"},
        {"model": "together/zai-org/GLM-5",           "label": "glm5"}
    ],
    "cleanup": "delete",
    "timeout_seconds": 60
}
# Expected: multi=True, count=2, both results have status="accepted"
```

---

## InvestorClaw Use Cases

1. **Parallel W-step specialization**: Spawn MiniMax-M2.7 for W5 metric extraction (QC4=108 single) and GLM-5 for W3 risk analysis (QC4=86 hybrid) simultaneously, synthesize in W6 with the orchestrating model.

2. **Model comparison before committing**: Before a full benchmark workflow, spawn the same W4 prompt across 3 candidate models, pick the winner's output for synthesis.

3. **Live switch after consultation**: `mode="live"` mid-session to upgrade from a cost-optimized model to MiniMax-M2.7 once the session has accumulated enough context to benefit from its higher QC4.
