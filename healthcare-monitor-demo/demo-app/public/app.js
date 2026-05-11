const titles = {
  health: "Runtime",
  topology: "Architecture",
  evidence: "Evidence",
  dashboard: "Operations",
  egress: "Governance",
};

const stepSummaries = {
  health:
    "Confirm the image-baked runtime, policy, skills, and gateway are ready before running the agent workflow.",
  topology:
    "Inspect the OpenClaw-native multi-agent layout, Docker-based sandbox deployment, specialist prompts and skills, and the deterministic files that ground every agent step.",
  evidence:
    "Run the deterministic local tools beside command output, then inspect the raw synthetic data that grounds the specialist agents.",
  dashboard:
    "Run operator analysis and the multi-agent plan from the same command-center view while watching the live queue and decision state.",
  egress:
    "Show that external lookups are policy-controlled, inspect the recurring watch job, and use the embedded OpenShell terminal to observe the boundary live.",
};

const actionLabels = {
  "runtime-status": "NemoClaw Status",
  probe: "OpenClaw Gateway Probe",
  "verify-runtime": "Runtime Kit Verification",
  upload: "Sandbox Config",
  "policy-list": "Sandbox Policy List",
  "apply-demo-policy": "Apply Local Policy",
  "agent-topology": "Agent Topology",
  intake: "Intake Tool",
  triage: "Triage Tool",
  schedule: "Capacity Tool",
  audit: "Audit Tool",
  "watch-summary": "Healthcare Monitor Watch Summary",
  "manual-watch": "Manual Cron Watch",
  report: "48-Hour Report",
  cron: "Cron Job",
  "blocked-lookup": "Blocked Lookup",
  "agent-plan": "Multi-Agent Plan",
  "agent-egress": "Agent Egress Explanation",
  "operator-analysis": "Operator Decision Analysis",
};

const actionExplanations = {
  "runtime-status":
    "Shows whether the NemoClaw sandbox is ready, which model/provider is active, whether inference is healthy, and which effective network policies are loaded. Use this as the first readiness check.",
  probe:
    "Checks that the OpenClaw gateway inside the sandbox is reachable. If this fails, the agent commands and GUI-backed sandbox actions will not work reliably.",
  "policy-list":
    "Lists NemoClaw policy presets known to the sandbox. This is useful for orientation, but for custom policies the stronger proof is NemoClaw Status, where the effective network policy is printed.",
  "apply-demo-policy":
    "Applies the healthcare monitor custom policy preset to the sandbox. You only need this after first setup or after changing the policy file; repeated runs can report Policy unchanged.",
  "verify-runtime":
    "Runs local deterministic checks against the synthetic data, analyzer script, report generation, cron JSON, and shell script syntax. This proves the folder is internally consistent before the live runtime is used.",
  upload:
    "Reads the image-baked OpenClaw config from inside the sandbox. In this architecture, agents, skills, data, tools, and cron are baked into the custom sandbox image rather than uploaded after onboarding.",
  "agent-topology":
    "Prints the configured multi-agent architecture: main coordinator, five leaf specialists, each specialist's skill and workspace, and the least-privilege tool policy.",
  intake:
    "Intake normalizes the synthetic referral queue and checks source-data quality before triage, capacity, and audit agents consume it.",
  "operator-analysis":
    "Reviews the current operator decisions against deterministic triage, capacity, and audit evidence. This avoids live model latency while preserving the decision-support story.",
  triage:
    "Triage ranks the synthetic referral queue by clinical urgency using local escalation rules and note summaries. It turns intake records into critical, high, medium, or routine priorities with explicit drivers.",
  schedule:
    "Capacity matching assigns each prioritized referral to available synthetic clinic slots. It prefers the requested service line and location, then flags anything that needs manual command-center intervention.",
  audit:
    "Audit checks the scheduled actions against payer and governance rules. It flags prior authorization needs, audit-required actions, and the rationale an operator can review before acting.",
  "watch-summary":
    "Watch Summary is the always-on operations signal. It condenses current backlog volume, urgent referrals, capacity gaps, prior authorization flags, and the governance note into a short command-center update.",
  "manual-watch":
    "Runs the scheduled watch evidence CLI inside the sandbox. This tests the recurring story without waiting for the hourly scheduler.",
  report:
    "48-Hour Report is the executive action plan. It combines triage, scheduling, and audit outputs into a reviewable healthcare operations plan.",
  cron:
    "Displays the scheduled Healthcare Monitor Watch job installed inside the sandbox image. It proves the recurring monitoring task is explicit, inspectable, and bounded to synthetic local data.",
  "blocked-lookup":
    "Runs the intentional egress test. The tool attempts a lookup to example.org, and the expected result is a policy block such as 403 Forbidden. This is the live governance proof point.",
  "agent-plan":
    "Runs the main OpenClaw coordinator through the web app's fixed CLI allowlist. The app detects the sandbox gateway port, then main lists agents, spawns specialists, and runs the deterministic report as the final evidence source.",
  "agent-egress":
    "Runs the blocked-egress CLI through the web app's command allowlist so the governance proof point is visible without relying on a bare agent gateway session.",
};

const actionPreviews = {
  "runtime-status": `Sandbox: healthcare-monitor
Model: nvidia/nemotron-3-super-120b-a12b
Provider: build.nvidia.com
Inference: healthy
Phase: Ready
Policy source: sandbox
network_policies:
  healthcare-monitor-local
OpenClaw: running`,
  probe: `Probe complete: OpenClaw gateway is running in 'healthcare-monitor'.`,
  "policy-list": `Policy presets:
  applied: restricted baseline
  custom: healthcare-monitor-local

For effective policy proof, use NemoClaw Status and look under network_policies.`,
  "apply-demo-policy": `[healthcare-monitor-local] Endpoints that would be opened: localhost, 127.0.0.1
Applied preset: healthcare-monitor-local
Policy unchanged if already applied.`,
  "verify-runtime": `local verification passed
Validated triage, schedule, audit, report, watch-summary, cron JSON, and shell scripts.`,
  upload: `Image-baked OpenClaw config present:
- /sandbox/.openclaw/openclaw.json
- /sandbox/.openclaw/skills
- /sandbox/.openclaw/workspace-main
- /sandbox/.openclaw/workspace-intake
- /sandbox/.openclaw/workspace-clinical-triage
- /sandbox/.openclaw/cron/jobs.json`,
  "agent-topology": `{
  "default_agent": "main",
  "pattern": "main coordinator delegates to leaf specialist sub-agents with sessions_spawn",
  "specialists": [
    "intake",
    "clinical-triage",
    "capacity-planner",
    "payer-audit",
    "command-writer"
  ],
  "least_privilege": {
    "main": ["sessions_spawn", "sessions_yield", "agents_list"],
    "specialists": ["read", "exec", "process"]
  }
}`,
  intake: `{
  "total_referrals": 8,
  "service_lines": {
    "Cardiology": 2,
    "Oncology": 1,
    "Primary Care": 1
  },
  "duplicates": [],
  "missing_fields": []
}`,
  "operator-analysis": `Decision Support Analysis

R-1001 manual-review: risk of delaying a critical cardiology follow-up already scheduled in an urgent slot.
R-1003 expedite: aligned with critical oncology priority; initiate prior authorization immediately.
R-1008 auth hold: misaligned because audit says no prior auth is required.

Next actions:
1. Proceed with supported urgent slots.
2. Start auth work where audit requires it.
3. Remove holds that are not supported by the audit output.`,
  triage: `[
  { "referral_id": "R-1001", "priority": "critical", "drivers": ["chest_pain"] },
  { "referral_id": "R-1003", "priority": "critical", "drivers": ["possible_malignancy"] },
  { "referral_id": "R-1008", "priority": "critical", "drivers": ["shortness_of_breath"] },
  { "referral_id": "R-1004", "priority": "high", "drivers": ["respiratory_symptoms"] }
]`,
  schedule: `[
  { "referral_id": "R-1001", "status": "scheduled", "slot": "S-2001" },
  { "referral_id": "R-1003", "status": "scheduled", "slot": "S-2002" },
  { "referral_id": "R-1008", "status": "scheduled", "slot": "S-2005" }
]

Summary: 8 scheduled, 0 capacity gaps.`,
  audit: `{
  "summary": { "total_referrals": 8, "scheduled": 8, "capacity_gaps": 0, "critical_or_high": 5 },
  "prior_auth_flags": ["R-1003", "R-1005", "R-1006", "R-1007"],
  "audit_required": "critical and high priority actions"
}`,
  "watch-summary": `CARE_BACKLOG_WATCH
total_referrals=8
critical_or_high=5
scheduled=8
capacity_gaps=0

urgent_actions:
- R-1001 critical Cardiology -> scheduled S-2001
- R-1003 critical Oncology -> scheduled S-2002
- R-1008 critical Cardiology -> scheduled S-2005`,
  "manual-watch": `Scheduled Healthcare Monitor Watch

Current backlog signal:
- 8 total referrals
- 5 critical/high referrals
- 8 scheduled
- 0 capacity gaps

Critical/high referrals needing action:
- R-1001 critical Cardiology -> S-2001
- R-1003 critical Oncology -> S-2002
- R-1008 critical Cardiology -> S-2005

Governance note:
Ran from the cron payload using sandbox-local synthetic data only.`,
  report: `# 48-Hour Care Backlog Action Plan

- Total referrals: 8
- Scheduled from available capacity: 8
- Capacity gaps: 0
- Critical/high priority: 5

Recommended Actions:
R-1001 critical Cardiology -> scheduled S-2001
R-1003 critical Oncology -> scheduled S-2002
R-1008 critical Cardiology -> scheduled S-2005`,
  "agent-plan": `# Multi-Agent Healthcare Monitor Plan

Coordinator: main
Specialists: intake, clinical-triage, capacity-planner, payer-audit
Tools: agents_list, sessions_spawn, exec
Final evidence: deterministic 48-hour report

Operator direction:
1. Act on critical/high referrals first.
2. Keep scheduled urgent slots.
3. Start prior authorization for flagged cases.
4. Preserve audit rationale for review.`,
  "blocked-lookup": `Attempting intentional egress lookup:
https://example.org/healthcare-monitor-blocked-lookup

Expected result:
Tunnel connection failed: 403 Forbidden`,
  "agent-egress": `Blocked Egress Explanation

The tool attempted an unapproved external lookup.
OpenShell policy blocked the request.
Business value: agents can be useful while still operating inside observable, approval-driven boundaries.`,
  cron: `{
  "name": "Healthcare Monitor Watch",
  "enabled": true,
  "schedule": { "kind": "every", "everyMs": 3600000 },
  "message": "Run watch-summary using synthetic local data only."
}`,
};

const output = document.querySelector("#output");
const commandTitle = document.querySelector("#commandTitle");
const lastStatus = document.querySelector("#lastStatus");
const sectionTitle = document.querySelector("#sectionTitle");
const sectionSummary = document.querySelector("#sectionSummary");
const clearOutput = document.querySelector("#clearOutput");
const outputPanel = document.querySelector(".output-panel");
const evidenceOutputMount = document.querySelector("#evidenceOutputMount");
const globalOutputMount = document.querySelector("#globalOutputMount");
const actionExplanation = document.querySelector("#actionExplanation");
const actionExplanationTitle = document.querySelector("#actionExplanationTitle");
const actionExplanationText = document.querySelector("#actionExplanationText");
const referralRows = document.querySelector("#referralRows");
const fileWatch = document.querySelector("#fileWatch");
const dashboardUpdated = document.querySelector("#dashboardUpdated");
const embeddedTerminal = document.querySelector("#embeddedTerminal");
const terminalStatus = document.querySelector("#terminalStatus");
const startTerminal = document.querySelector("#startTerminal");
const stopTerminal = document.querySelector("#stopTerminal");
const clearTerminal = document.querySelector("#clearTerminal");
const refreshEvidence = document.querySelector("#refreshEvidence");
const evidenceHead = document.querySelector("#evidenceHead");
const evidenceBody = document.querySelector("#evidenceBody");
const toolLogic = document.querySelector("#toolLogic");
const topologyAgents = document.querySelector("#topologyAgents");
const topologyFlow = document.querySelector("#topologyFlow");
const topologyFiles = document.querySelector("#topologyFiles");
const topologyFileViewer = document.querySelector("#topologyFileViewer");
const topologyFileTitle = document.querySelector("#topologyFileTitle");
const topologyFileContent = document.querySelector("#topologyFileContent");
const deploymentFlow = document.querySelector("#deploymentFlow");
const policyNote = document.querySelector("#policyNote");
const policyEndpoints = document.querySelector("#policyEndpoints");
const policyBinaries = document.querySelector("#policyBinaries");
let currentStep = "health";
let evidenceData = null;
let topologyLoaded = false;
let currentEvidenceTab = "referrals";
let lastTerminalState = {
  title: "No command run yet",
  output: "Choose a step and run a command.",
  explanationHidden: true,
  explanationTitle: "Command Context",
  explanationText: "",
};
let runningAction = null;
let terminalRunning = false;
let terminalRows = 28;
let terminalCols = 100;
let terminalScreen = [];
let terminalCursor = { row: 0, col: 0 };

function setStep(stepId) {
  currentStep = stepId;
  document.querySelectorAll(".step").forEach((button) => {
    button.classList.toggle("active", button.dataset.step === stepId);
  });
  document.querySelectorAll(".stage").forEach((stage) => {
    stage.classList.toggle("active", stage.id === stepId);
  });
  sectionTitle.textContent = titles[stepId] || "Live Walkthrough";
  sectionSummary.textContent = stepSummaries[stepId] || "";
  positionOutputPanel(stepId);
  if (stepId === "egress") {
    loadTerminalStatus();
  }
  if (stepId === "topology") {
    loadTopology();
  }
  if (stepId === "evidence") {
    loadEvidence();
  }
}

function positionOutputPanel(stepId) {
  if (!outputPanel || !evidenceOutputMount || !globalOutputMount) {
    return;
  }
  outputPanel.hidden = stepId === "topology";
  if (outputPanel.hidden) {
    return;
  }
  const target = stepId === "evidence" ? evidenceOutputMount : globalOutputMount;
  if (outputPanel.parentElement !== target) {
    target.appendChild(outputPanel);
  }
}

function setBusy(action, busy) {
  document.querySelectorAll("button[data-action]").forEach((button) => {
    button.disabled = busy;
  });
  lastStatus.textContent = busy ? `Running ${actionLabels[action]}` : "Ready";
  runningAction = busy ? action : null;
}

function formatResult(result) {
  const parts = [];
  parts.push(`$ ${result.command}`);
  parts.push(`exit_code=${result.exitCode}`);
  if (result.agentText) {
    parts.push("");
    parts.push(result.agentText.trim());
  } else if (result.stdout?.trim()) {
    parts.push("");
    parts.push(result.stdout.trim());
  }
  if (result.stderr?.trim()) {
    parts.push("");
    parts.push("[stderr]");
    parts.push(result.stderr.trim());
  }
  return parts.join("\n");
}

async function runAction(action) {
  const label = actionLabels[action] || action;
  commandTitle.textContent = label;
  showActionExplanation(action, label);
  output.textContent = `Running ${label}...\n\nLong agent turns can take two or three minutes.`;
  focusOutputPanel();
  setBusy(action, true);

  try {
    const response = await fetch(`/api/run/${action}`, { method: "POST" });
    const result = await response.json();
    output.textContent = formatResult(result);
    lastStatus.textContent = result.ok ? "Completed" : `Exited ${result.exitCode}`;
    saveTerminalState();
    loadDashboard();
  } catch (error) {
    output.textContent = `Request failed: ${error.message}`;
    lastStatus.textContent = "Request failed";
    saveTerminalState();
  } finally {
    setBusy(action, false);
  }
}

function saveTerminalState() {
  lastTerminalState = {
    title: commandTitle.textContent,
    output: output.textContent,
    explanationHidden: actionExplanation.hidden,
    explanationTitle: actionExplanationTitle.textContent,
    explanationText: actionExplanationText.textContent,
  };
}

function focusOutputPanel() {
  if (!outputPanel) {
    return;
  }
  outputPanel.classList.add("connected");
  outputPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => outputPanel.classList.remove("connected"), 1800);
}

function restoreTerminalState() {
  if (runningAction) {
    return;
  }
  commandTitle.textContent = lastTerminalState.title;
  output.textContent = lastTerminalState.output;
  actionExplanation.hidden = lastTerminalState.explanationHidden;
  actionExplanationTitle.textContent = lastTerminalState.explanationTitle;
  actionExplanationText.textContent = lastTerminalState.explanationText;
}

async function showActionPreview(action) {
  if (runningAction) {
    return;
  }
  const label = actionLabels[action] || action;
  commandTitle.textContent = `${label} Preview`;
  showActionExplanation(action, label);
  output.textContent = "Loading command preview...";
  try {
    const response = await fetch(`/api/preview/${action}`);
    const preview = await response.json();
    output.textContent = formatPreview(action, preview);
  } catch (error) {
    output.textContent = [
      "Command preview unavailable.",
      "",
      actionPreviews[action] || "No sample output available for this action.",
    ].join("\n");
  }
}

function formatPreview(action, preview) {
  const parts = [];
  parts.push("Command that will run on click:");
  parts.push(`$ ${preview.command}`);
  parts.push(`cwd=${preview.cwd}`);
  parts.push(`timeout=${preview.timeout}s`);
  if (preview.isAgent) {
    parts.push("note=agent call; this can take two or three minutes");
  }
  const sample = actionPreviews[action];
  if (sample) {
    parts.push("");
    parts.push("Example output:");
    parts.push(sample);
  }
  return parts.join("\n");
}

function showActionExplanation(action, label) {
  const explanation = actionExplanations[action];
  if (!explanation) {
    actionExplanation.hidden = true;
    actionExplanationTitle.textContent = "Command Context";
    actionExplanationText.textContent = "";
    return;
  }
  actionExplanation.hidden = false;
  actionExplanationTitle.textContent = `${label} Context`;
  actionExplanationText.textContent = explanation;
}

function priorityClass(priority) {
  return `priority-pill priority-${priority || "medium"}`;
}

function renderDashboard(data) {
  const summary = data.summary || {};
  const referrals = data.referrals || [];
  const critical = referrals.filter((item) => item.priority === "critical").length;
  const high = referrals.filter((item) => item.priority === "high").length;
  const authFlags = referrals.filter((item) => item.priorAuthRequired).length;
  const auditFlags = referrals.filter((item) => item.auditRequired).length;
  const drivers = [
    ...new Set(referrals.flatMap((item) => item.drivers || [])),
  ].slice(0, 5);

  document.querySelector("#criticalCount").textContent = critical;
  document.querySelector("#highCount").textContent = high;
  document.querySelector("#scheduledCount").textContent = summary.scheduled ?? 0;
  document.querySelector("#gapCount").textContent = summary.capacity_gaps ?? 0;
  document.querySelector("#intakeTotal").textContent = summary.total_referrals ?? referrals.length;
  document.querySelector("#triageSignal").textContent = `${summary.critical_or_high ?? critical + high} critical/high`;
  document.querySelector("#capacitySignal").textContent = `${summary.scheduled ?? 0} scheduled`;
  document.querySelector("#auditSignal").textContent = `${authFlags} auth flags`;
  document.querySelector("#intakeSignal").textContent =
    referrals.length > 0 ? `${referrals.length} referrals normalized from local intake files.` : "No referrals loaded.";
  document.querySelector("#triageDrivers").textContent =
    drivers.length > 0 ? `Top drivers: ${drivers.join(", ")}.` : "No risk drivers found.";
  document.querySelector("#capacityDetails").textContent =
    `${summary.capacity_gaps ?? 0} capacity gaps; slots assigned from synthetic clinic capacity.`;
  document.querySelector("#auditDetails").textContent =
    `${auditFlags} audit-required actions; ${authFlags} prior authorization flags.`;
  dashboardUpdated.textContent = `Last refreshed ${data.updatedAt}`;

  referralRows.innerHTML = referrals
    .map((item) => {
      const slot = item.slot || {};
      const operator = item.operator || {};
      const decision = operator.decision || "pending";
      return `
        <tr>
          <td><strong>${item.referral_id}</strong><br><span>${item.patient_alias}</span></td>
          <td><span class="${priorityClass(item.priority)}">${item.priority}</span></td>
          <td>${item.service_line}<br><span>${item.preferred_location}</span></td>
          <td>${item.status}<br><span>${slot.slot_id || "none"}</span></td>
          <td>${item.auditRequired ? "audit" : "standard"}<br><span>${item.priorAuthRequired ? "prior auth" : "no auth flag"}</span></td>
          <td>
            <span class="decision-pill">${decision}</span>
            <div class="decision-buttons">
              <button data-decision="expedite" data-referral="${item.referral_id}" title="Mark this referral for rapid scheduling action.">Expedite</button>
              <button data-decision="hold-for-auth" data-referral="${item.referral_id}" title="Mark this referral as waiting on prior authorization or payer review.">Auth Hold</button>
              <button data-decision="manual-review" data-referral="${item.referral_id}" title="Mark this referral for manual command-center review.">Review</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  fileWatch.innerHTML = (data.files || [])
    .slice(0, 18)
    .map(
      (file) => `
        <div class="file-row">
          <strong>${file.path}</strong>
          <span>${file.modified} · ${file.bytes} bytes</span>
        </div>
      `,
    )
    .join("");

  document.querySelectorAll("button[data-decision]").forEach((button) => {
    button.addEventListener("click", () =>
      saveDecision(button.dataset.referral, button.dataset.decision),
    );
  });
}

function renderLogic(logic) {
  if (!toolLogic || !logic) {
    return;
  }
  const cards = [
    ["Triage", logic.triage],
    ["Capacity", logic.capacity],
    ["Audit", logic.audit],
    ["Watch", logic.watch],
  ];
  toolLogic.innerHTML = cards
    .map(
      ([title, lines]) => `
        <article>
          <h3>${title}</h3>
          <ul>${(lines || []).map((line) => `<li>${line}</li>`).join("")}</ul>
        </article>
      `,
    )
    .join("");
}

function renderEvidenceTable(tab) {
  if (!evidenceData || !evidenceHead || !evidenceBody) {
    return;
  }
  const files = evidenceData.files || {};
  const table = evidenceRows(tab, files);
  evidenceHead.innerHTML = `<tr>${table.headers.map((header) => `<th>${header}</th>`).join("")}</tr>`;
  evidenceBody.innerHTML = table.rows
    .map(
      (row) => `
        <tr>${table.headers
          .map((header) => `<td>${formatEvidenceCell(row[header])}</td>`)
          .join("")}</tr>
      `,
    )
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadTopology() {
  if (!topologyAgents || topologyLoaded) {
    return;
  }
  try {
    const response = await fetch("/api/topology");
    const data = await response.json();
    renderTopology(data);
    topologyLoaded = true;
  } catch (error) {
    topologyAgents.innerHTML = `<article class="agent-card">Topology unavailable: ${escapeHtml(error.message)}</article>`;
  }
}

function renderTopology(data) {
  const agents = (data.agents || []).filter((agent) => agent.id !== "main");
  topologyAgents.innerHTML = agents
    .map(
      (agent) => `
        <article class="agent-card leaf" data-agent-id="${escapeHtml(agent.id)}">
          <span>${escapeHtml(agent.id)}</span>
          <strong>${escapeHtml(agent.role)}</strong>
          <p><code>${escapeHtml(agent.cli)}</code></p>
          <small>${agent.canSpawn ? "can spawn" : "leaf agent"} · ${escapeHtml((agent.skills || []).join(", "))}</small>
        </article>
      `,
    )
    .join("");

  topologyFlow.innerHTML = (data.callFlow || [])
    .map(
      (item) => `
        <li>
          <strong>${escapeHtml(item.step)}</strong>
          <span>${escapeHtml(item.actor)} · <code>${escapeHtml(item.tool)}</code></span>
          ${item.cli ? `<code>${escapeHtml(item.cli)}</code>` : `<p>${escapeHtml(item.description || "")}</p>`}
        </li>
      `,
    )
    .join("");

  if (deploymentFlow) {
    deploymentFlow.innerHTML = (data.deploymentFlow || [])
      .map(
        (item) => `
          <li>
            <strong>${escapeHtml(item.step)}</strong>
            <span>${escapeHtml(item.actor)} · <code>${escapeHtml(item.tool)}</code></span>
            <p>${escapeHtml(item.description || "")}</p>
          </li>
        `,
      )
      .join("");
  }

  topologyFiles.innerHTML = (data.files || [])
    .map(
      (file) => `
        <button data-topology-file="${escapeHtml(file.path)}" title="${escapeHtml(file.label)}">
          ${escapeHtml(file.path)}
        </button>
      `,
    )
    .join("");

  topologyFiles.querySelectorAll("button[data-topology-file]").forEach((button) => {
    button.addEventListener("click", () => loadTopologyFile(button.dataset.topologyFile));
  });

  const firstFile = (data.files || []).find((file) => file.path === "workspaces/main/AGENTS.md") || data.files?.[0];
  if (firstFile) {
    loadTopologyFile(firstFile.path);
  }
}

async function loadTopologyFile(path) {
  if (!topologyFileViewer || !path) {
    return;
  }
  topologyFileViewer.hidden = false;
  topologyFileTitle.textContent = path;
  topologyFileContent.textContent = "Loading file...";
  try {
    const response = await fetch(`/api/topology/file?path=${encodeURIComponent(path)}`);
    const data = await response.json();
    if (data.ok === false) {
      throw new Error(data.error || "file unavailable");
    }
    topologyFileTitle.textContent = `${data.path} — ${data.label}`;
    topologyFileContent.textContent = data.content;
    topologyFileViewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
    topologyFiles?.querySelectorAll("button[data-topology-file]").forEach((button) => {
      button.classList.toggle("active", button.dataset.topologyFile === path);
    });
  } catch (error) {
    topologyFileContent.textContent = `File unavailable: ${error.message}`;
  }
}

function evidenceRows(tab, files) {
  if (tab === "notes") {
    return {
      headers: ["referral_id", "note_summary"],
      rows: Object.entries(files.notes || {}).map(([referral_id, note_summary]) => ({
        referral_id,
        note_summary,
      })),
    };
  }
  if (tab === "capacity") {
    return {
      headers: ["slot_id", "service_line", "location", "start_time", "duration_minutes", "clinician", "visit_type"],
      rows: files.capacity || [],
    };
  }
  if (tab === "rules") {
    const rules = files.escalationRules || {};
    return {
      headers: ["rule", "value", "used_by"],
      rows: [
        { rule: "critical_flags", value: rules.critical_flags, used_by: "Triage: score 100" },
        { rule: "high_flags", value: rules.high_flags, used_by: "Triage: score 80" },
        { rule: "medium_flags", value: rules.medium_flags, used_by: "Triage: score 50" },
        { rule: "default_priority", value: rules.default_priority, used_by: "Triage fallback" },
        { rule: "audit_required_for", value: rules.audit_required_for, used_by: "Audit flags" },
      ],
    };
  }
  if (tab === "payers") {
    return {
      headers: ["payer", "prior_auth_required", "expedite_window_hours", "notes"],
      rows: Object.entries(files.payerRules || {}).map(([payer, row]) => ({
        payer,
        prior_auth_required: row.prior_auth_required,
        expedite_window_hours: row.expedite_window_hours,
        notes: row.notes,
      })),
    };
  }
  return {
    headers: [
      "referral_id",
      "patient_alias",
      "age",
      "service_line",
      "reason",
      "requested_window_hours",
      "risk_flags",
      "preferred_location",
      "payer",
      "received_at",
    ],
    rows: files.referrals || [],
  };
}

function formatEvidenceCell(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return value ?? "";
}

async function loadEvidence() {
  if (!toolLogic || !evidenceHead || !evidenceBody) {
    return;
  }
  try {
    const response = await fetch("/api/evidence");
    evidenceData = await response.json();
    renderLogic(evidenceData.logic);
    renderEvidenceTable(currentEvidenceTab);
  } catch (error) {
    evidenceBody.innerHTML = `<tr><td>Evidence unavailable: ${error.message}</td></tr>`;
  }
}

async function saveDecision(referralId, decision) {
  lastStatus.textContent = `Saving ${decision} for ${referralId}`;
  const response = await fetch("/api/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      referralId,
      decision,
      owner: "Command center operator",
      note: "Selected from frontend operator dashboard",
    }),
  });
  const data = await response.json();
  renderDashboard(data);
  lastStatus.textContent = "Decision updated";
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard");
    const data = await response.json();
    renderDashboard(data);
  } catch (error) {
    dashboardUpdated.textContent = `Dashboard refresh failed: ${error.message}`;
  }
}

function setTerminalStatus(data) {
  terminalRunning = Boolean(data?.running);
  if (!terminalStatus) {
    return;
  }
  if (terminalRunning) {
    terminalStatus.textContent = `Running ${data.command} from ${data.cwd}`;
  } else if (data?.exitCode !== null && data?.exitCode !== undefined) {
    terminalStatus.textContent = `Terminal exited ${data.exitCode}`;
  } else {
    terminalStatus.textContent = "Terminal idle";
  }
}

function terminalSize() {
  if (!embeddedTerminal) {
    return { rows: 28, cols: 100 };
  }
  const style = window.getComputedStyle(embeddedTerminal);
  const lineHeight = Number.parseFloat(style.lineHeight) || 20;
  const charWidth = 8.6;
  return {
    rows: Math.max(12, Math.floor(embeddedTerminal.clientHeight / lineHeight)),
    cols: Math.max(60, Math.floor(embeddedTerminal.clientWidth / charWidth)),
  };
}

function resetTerminalScreen(message = "") {
  const size = terminalSize();
  terminalRows = size.rows;
  terminalCols = size.cols;
  terminalScreen = Array.from({ length: terminalRows }, () =>
    Array.from({ length: terminalCols }, () => " "),
  );
  terminalCursor = { row: 0, col: 0 };
  if (message) {
    writeTerminalText(message);
  }
  renderTerminal();
}

function renderTerminal() {
  if (!embeddedTerminal) {
    return;
  }
  embeddedTerminal.textContent = terminalScreen
    .map((row) => row.join("").replace(/\s+$/g, ""))
    .join("\n")
    .trimEnd();
  embeddedTerminal.scrollTop = embeddedTerminal.scrollHeight;
}

function clampCursor() {
  terminalCursor.row = Math.max(0, Math.min(terminalRows - 1, terminalCursor.row));
  terminalCursor.col = Math.max(0, Math.min(terminalCols - 1, terminalCursor.col));
}

function scrollTerminal() {
  terminalScreen.shift();
  terminalScreen.push(Array.from({ length: terminalCols }, () => " "));
  terminalCursor.row = terminalRows - 1;
}

function putTerminalChar(char) {
  if (terminalCursor.row >= terminalRows) {
    scrollTerminal();
  }
  terminalScreen[terminalCursor.row][terminalCursor.col] = char;
  terminalCursor.col += 1;
  if (terminalCursor.col >= terminalCols) {
    terminalCursor.col = 0;
    terminalCursor.row += 1;
  }
  if (terminalCursor.row >= terminalRows) {
    scrollTerminal();
  }
}

function clearTerminalFromCursor() {
  for (let row = terminalCursor.row; row < terminalRows; row += 1) {
    const startCol = row === terminalCursor.row ? terminalCursor.col : 0;
    for (let col = startCol; col < terminalCols; col += 1) {
      terminalScreen[row][col] = " ";
    }
  }
}

function clearTerminalLine() {
  for (let col = terminalCursor.col; col < terminalCols; col += 1) {
    terminalScreen[terminalCursor.row][col] = " ";
  }
}

function csiParams(sequence) {
  const normalized = sequence.replace(/^\?/, "");
  if (!normalized) {
    return [0];
  }
  return normalized.split(";").map((part) => Number.parseInt(part || "0", 10));
}

function applyCsi(sequence, finalChar) {
  const params = csiParams(sequence);
  if (finalChar === "H" || finalChar === "f") {
    terminalCursor.row = Math.max(0, (params[0] || 1) - 1);
    terminalCursor.col = Math.max(0, (params[1] || 1) - 1);
    clampCursor();
    return;
  }
  if (finalChar === "J") {
    if ((params[0] || 0) === 2) {
      resetTerminalScreen();
    } else {
      clearTerminalFromCursor();
    }
    return;
  }
  if (finalChar === "K") {
    clearTerminalLine();
    return;
  }
  if (finalChar === "A") terminalCursor.row -= params[0] || 1;
  if (finalChar === "B") terminalCursor.row += params[0] || 1;
  if (finalChar === "C") terminalCursor.col += params[0] || 1;
  if (finalChar === "D") terminalCursor.col -= params[0] || 1;
  if (finalChar === "G") terminalCursor.col = Math.max(0, (params[0] || 1) - 1);
  clampCursor();
}

function writeTerminalText(text) {
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === "\x1b" && text[index + 1] === "[") {
      let end = index + 2;
      while (end < text.length && !/[\x40-\x7e]/.test(text[end])) {
        end += 1;
      }
      if (end < text.length) {
        applyCsi(text.slice(index + 2, end), text[end]);
        index = end;
      }
      continue;
    }
    if (char === "\r") {
      terminalCursor.col = 0;
      continue;
    }
    if (char === "\n") {
      terminalCursor.row += 1;
      terminalCursor.col = 0;
      if (terminalCursor.row >= terminalRows) {
        scrollTerminal();
      }
      continue;
    }
    if (char === "\b") {
      terminalCursor.col = Math.max(0, terminalCursor.col - 1);
      continue;
    }
    if (char < " ") {
      continue;
    }
    putTerminalChar(char);
  }
}

async function terminalPost(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

async function loadTerminalStatus() {
  if (!embeddedTerminal) {
    return;
  }
  try {
    const response = await fetch("/api/terminal/status");
    setTerminalStatus(await response.json());
  } catch (error) {
    terminalStatus.textContent = `Terminal status unavailable: ${error.message}`;
  }
}

async function startEmbeddedTerminal() {
  const size = terminalSize();
  resetTerminalScreen("Starting openshell term...\n");
  embeddedTerminal.focus();
  try {
    setTerminalStatus(await terminalPost("/api/terminal/start", size));
    await readEmbeddedTerminal();
  } catch (error) {
    writeTerminalText(`\nTerminal start failed: ${error.message}`);
    renderTerminal();
  }
}

async function stopEmbeddedTerminal() {
  try {
    setTerminalStatus(await terminalPost("/api/terminal/stop"));
  } catch (error) {
    terminalStatus.textContent = `Terminal stop failed: ${error.message}`;
  }
}

async function writeEmbeddedTerminal(data) {
  if (!terminalRunning || !data) {
    return;
  }
  try {
    setTerminalStatus(await terminalPost("/api/terminal/write", { data }));
  } catch (error) {
    terminalStatus.textContent = `Terminal write failed: ${error.message}`;
  }
}

async function readEmbeddedTerminal() {
  if (!embeddedTerminal) {
    return;
  }
  try {
    const response = await fetch("/api/terminal/read");
    const data = await response.json();
    setTerminalStatus(data);
    if (data.chunk) {
      writeTerminalText(data.chunk);
      renderTerminal();
    }
  } catch (error) {
    terminalStatus.textContent = `Terminal read failed: ${error.message}`;
  }
}

function keyToTerminalData(event) {
  if (event.ctrlKey && event.key.length === 1) {
    const code = event.key.toUpperCase().charCodeAt(0) - 64;
    if (code > 0 && code < 27) {
      return String.fromCharCode(code);
    }
  }
  const special = {
    Enter: "\r",
    Backspace: "\x7f",
    Tab: "\t",
    Escape: "\x1b",
    ArrowUp: "\x1b[A",
    ArrowDown: "\x1b[B",
    ArrowRight: "\x1b[C",
    ArrowLeft: "\x1b[D",
  };
  if (special[event.key]) {
    return special[event.key];
  }
  if (!event.altKey && !event.metaKey && event.key.length === 1) {
    return event.key;
  }
  return "";
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    document.querySelector("#sandboxName").textContent = config.sandbox;
    document.querySelector("#modelName").textContent = config.model;
    document.querySelector("#providerName").textContent = config.provider;
    renderPolicySummary(config.policySummary || {});
  } catch {
    document.querySelector("#sandboxName").textContent = "unavailable";
    document.querySelector("#modelName").textContent = "unavailable";
    document.querySelector("#providerName").textContent = "unavailable";
    renderPolicySummary({});
  }
}

function renderPolicySummary(summary) {
  if (policyNote) {
    policyNote.textContent = summary.note || "Policy summary unavailable.";
  }
  if (policyEndpoints) {
    const endpoints = summary.endpoints || [];
    policyEndpoints.innerHTML = endpoints.length
      ? `<div class="policy-list">${endpoints
          .map(
            (item) =>
              `<div class="policy-item"><strong>${item.host}:${item.port}</strong><br><span>${item.access || "full"} access</span></div>`,
          )
          .join("")}</div>`
      : "<div class=\"policy-item\">No endpoint data available.</div>";
  }
  if (policyBinaries) {
    const binaries = summary.binaries || [];
    policyBinaries.innerHTML = binaries.length
      ? `<div class="binary-list">${binaries
          .map((item) => `<div class="binary-item">${item}</div>`)
          .join("")}</div>`
      : "<div class=\"binary-item\">No binary allowlist available.</div>";
  }
}

document.querySelectorAll(".step").forEach((button) => {
  button.addEventListener("click", () => setStep(button.dataset.step));
});

document.querySelectorAll("button[data-action]").forEach((button) => {
  if (!button.querySelector(".info-icon")) {
    const icon = document.createElement("span");
    icon.className = "info-icon";
    icon.tabIndex = 0;
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", `${actionLabels[button.dataset.action] || button.dataset.action} preview`);
    icon.textContent = "i";
    button.appendChild(icon);
  }
  button.addEventListener("click", () => runAction(button.dataset.action));
});

document.querySelectorAll(".info-icon").forEach((icon) => {
  const button = icon.closest("button[data-action]");
  icon.addEventListener("mouseenter", () => showActionPreview(button.dataset.action));
  icon.addEventListener("focus", () => showActionPreview(button.dataset.action));
  icon.addEventListener("mouseleave", restoreTerminalState);
  icon.addEventListener("blur", restoreTerminalState);
});

clearOutput.addEventListener("click", () => {
  commandTitle.textContent = "No command run yet";
  output.textContent = "Choose a step and run a command.";
  actionExplanation.hidden = true;
  actionExplanationTitle.textContent = "Command Context";
  actionExplanationText.textContent = "";
  lastStatus.textContent = "Ready";
  saveTerminalState();
});

if (startTerminal) {
  startTerminal.addEventListener("click", startEmbeddedTerminal);
}

if (stopTerminal) {
  stopTerminal.addEventListener("click", stopEmbeddedTerminal);
}

if (clearTerminal) {
  clearTerminal.addEventListener("click", () => {
    resetTerminalScreen();
    embeddedTerminal.focus();
  });
}

if (refreshEvidence) {
  refreshEvidence.addEventListener("click", loadEvidence);
}

document.querySelectorAll("[data-evidence-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    currentEvidenceTab = button.dataset.evidenceTab;
    document.querySelectorAll("[data-evidence-tab]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    renderEvidenceTable(currentEvidenceTab);
  });
});

if (embeddedTerminal) {
  embeddedTerminal.addEventListener("keydown", (event) => {
    const data = keyToTerminalData(event);
    if (!data) {
      return;
    }
    event.preventDefault();
    writeEmbeddedTerminal(data);
  });
  embeddedTerminal.addEventListener("paste", (event) => {
    const data = event.clipboardData.getData("text");
    if (!data) {
      return;
    }
    event.preventDefault();
    writeEmbeddedTerminal(data);
  });
  window.addEventListener("resize", () => {
    if (terminalRunning) {
      terminalPost("/api/terminal/resize", terminalSize()).then(setTerminalStatus);
    }
  });
  resetTerminalScreen("Click Start OpenShell Term, then click inside this terminal to type.");
}

loadConfig();
loadDashboard();
loadEvidence();
loadTerminalStatus();
saveTerminalState();
setInterval(loadDashboard, 10000);
setInterval(() => {
  if (terminalRunning || currentStep === "egress") {
    readEmbeddedTerminal();
  }
}, 800);
