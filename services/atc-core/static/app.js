// ATC Approval UI. Vanilla JS, no build step, no framework - matches the
// stack in PROJECT_PLAN.md S3. Polls once on load, then stays live via
// WebSocket (S8: action.pending, action.resolved), with auto-reconnect on
// drop (S9: "WS drop -> UI auto-reconnect") and a periodic re-poll as a
// fallback in case events are ever missed mid-reconnect.

const HOLD_TIMEOUT_SECONDS = 120;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;
const FALLBACK_POLL_MS = 10000;

const pendingActions = new Map(); // action_id -> action
const fleetAgents = new Map(); // agent_id -> agent
const countdownIntervals = new Map(); // action_id -> interval handle

const pendingListEl = document.getElementById("pending-list");
const fleetListEl = document.getElementById("fleet-list");
const connectionStatusEl = document.getElementById("connection-status");

function decidedBy() {
  return "operator";
}

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${url} -> ${resp.status}: ${body}`);
  }
  return resp.status === 204 ? null : resp.json();
}

// --- rendering ---------------------------------------------------------

function riskClass(riskLevel) {
  return `risk-${riskLevel.toLowerCase()}`;
}

function renderPending() {
  const actions = Array.from(pendingActions.values()).sort(
    (a, b) => a.requested_at - b.requested_at
  );

  if (actions.length === 0) {
    pendingListEl.innerHTML = '<div class="empty-state">No actions awaiting approval.</div>';
    return;
  }

  pendingListEl.innerHTML = "";
  for (const action of actions) {
    pendingListEl.appendChild(renderActionCard(action));
  }
}

function renderActionCard(action) {
  const card = document.createElement("div");
  card.className = `action-card ${riskClass(action.risk_level)}`;
  card.dataset.actionId = action.action_id;

  // Consequence line: what approving actually commits the operator to.
  const irreversible = action.reversibility === "IRREVERSIBLE";
  const consequenceChips = [
    irreversible ? '<span class="chip chip-irreversible">CANNOT BE UNDONE</span>' : "",
    action.reversibility === "COMPENSABLE" ? '<span class="chip chip-compensable">undo available</span>' : "",
    action.blast_radius ? `<span class="chip chip-blast">${escapeHtml(action.blast_radius)}</span>` : "",
  ].join("");

  card.innerHTML = `
    <div class="row1">
      <span class="tool">${escapeHtml(action.tool)}</span>
      <span class="risk-badge ${riskClass(action.risk_level)}">${action.risk_level}</span>
    </div>
    <div class="meta">agent <strong>${escapeHtml(action.agent_id)}</strong>${
      action.resource_name ? ` &middot; ${escapeHtml(action.resource_name)}` : ""
    }</div>
    <div class="reason">${escapeHtml(action.risk_reason || "")} (${escapeHtml(action.rule_id)})</div>
    ${consequenceChips ? `<div class="consequences">${consequenceChips}</div>` : ""}
    <div class="countdown-track"><div class="countdown-fill"></div></div>
    <div class="countdown-label"></div>
    <div class="action-buttons">
      <button class="btn-approve">Approve</button>
      <button class="btn-deny">Deny</button>
    </div>
  `;

  card.querySelector(".btn-approve").addEventListener("click", (e) => decide(action.action_id, "approve", e.target));
  card.querySelector(".btn-deny").addEventListener("click", (e) => decide(action.action_id, "deny", e.target));

  startCountdown(action);
  return card;
}

function startCountdown(action) {
  stopCountdown(action.action_id);

  const fillEl = () => pendingListEl.querySelector(`[data-action-id="${action.action_id}"] .countdown-fill`);
  const labelEl = () => pendingListEl.querySelector(`[data-action-id="${action.action_id}"] .countdown-label`);

  const tick = () => {
    const fill = fillEl();
    const label = labelEl();
    if (!fill || !label) {
      stopCountdown(action.action_id);
      return;
    }
    const elapsed = Date.now() / 1000 - action.requested_at;
    const remaining = Math.max(0, HOLD_TIMEOUT_SECONDS - elapsed);
    const pct = Math.max(0, Math.min(100, (remaining / HOLD_TIMEOUT_SECONDS) * 100));
    fill.style.width = `${pct}%`;
    fill.classList.toggle("urgent", remaining <= 20);
    label.textContent = remaining > 0 ? `${Math.ceil(remaining)}s to auto-deny` : "expiring...";
  };

  tick();
  countdownIntervals.set(action.action_id, setInterval(tick, 1000));
}

function stopCountdown(actionId) {
  const handle = countdownIntervals.get(actionId);
  if (handle) {
    clearInterval(handle);
    countdownIntervals.delete(actionId);
  }
}

function renderFleet() {
  const agents = Array.from(fleetAgents.values()).sort((a, b) => a.id.localeCompare(b.id));

  if (agents.length === 0) {
    fleetListEl.innerHTML = '<div class="empty-state">No agents registered.</div>';
    return;
  }

  fleetListEl.innerHTML = "";
  for (const agent of agents) {
    fleetListEl.appendChild(renderFleetCard(agent));
  }
}

function renderFleetCard(agent) {
  const card = document.createElement("div");
  card.className = "fleet-card";
  card.dataset.agentId = agent.id;

  const heartbeat = agent.last_heartbeat_ts
    ? `${Math.round(Date.now() / 1000 - agent.last_heartbeat_ts)}s ago`
    : "never";

  card.innerHTML = `
    <div class="row1">
      <div>
        <span class="status-dot ${agent.quarantined ? "quarantined" : ""}"></span>
        <span class="agent-id">${escapeHtml(agent.id)}</span>
        <div class="persona">${escapeHtml(agent.persona)}</div>
      </div>
      <button class="btn-quarantine ${agent.quarantined ? "active" : ""}">
        ${agent.quarantined ? "Quarantined" : "Quarantine"}
      </button>
    </div>
    <div class="scope">
      ${agent.scope.map((s) => `<span class="scope-chip">${escapeHtml(s)}</span>`).join("")}
    </div>
    <div class="heartbeat">last heartbeat: ${heartbeat}</div>
  `;

  card.querySelector(".btn-quarantine").addEventListener("click", (e) => quarantine(agent, e.target));
  return card;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

// --- actions -----------------------------------------------------------

async function decide(actionId, verb, buttonEl) {
  buttonEl.closest(".action-buttons").querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await fetchJSON(`/api/actions/${encodeURIComponent(actionId)}/${verb}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decided_by: decidedBy() }),
    });
    // No local removal here - the action.resolved WS event (or fallback
    // poll) is the single source of truth for when a card actually leaves.
  } catch (err) {
    console.error("decide failed:", err);
    buttonEl.closest(".action-buttons").querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

async function quarantine(agent, buttonEl) {
  buttonEl.disabled = true;
  try {
    const updated = await fetchJSON(`/api/agents/${encodeURIComponent(agent.id)}/quarantine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quarantined: !agent.quarantined }),
    });
    fleetAgents.set(updated.id, updated);
    renderFleet();
  } catch (err) {
    console.error("quarantine failed:", err);
  } finally {
    buttonEl.disabled = false;
  }
}

// --- data loading + live updates ----------------------------------------

async function loadInitialState() {
  const [agents, actions] = await Promise.all([
    fetchJSON("/api/agents"),
    fetchJSON("/api/actions?status=pending"),
  ]);

  fleetAgents.clear();
  for (const agent of agents) fleetAgents.set(agent.id, agent);
  renderFleet();

  pendingActions.clear();
  for (const action of actions) pendingActions.set(action.action_id, action);
  renderPending();
}

function handleEvent(event) {
  if (event.type === "action.pending") {
    pendingActions.set(event.payload.action_id, event.payload);
    renderPending();
  } else if (event.type === "action.resolved") {
    pendingActions.delete(event.payload.action_id);
    stopCountdown(event.payload.action_id);
    renderPending();
  } else if (event.type === "agent.heartbeat") {
    fleetAgents.set(event.payload.id, event.payload);
    renderFleet();
  }
  // risk.updated: {agent_id, risk_score} isn't a full Agent record and
  // AgentOut doesn't carry risk_score yet (S8 fleet-card polish item) -
  // nothing to merge into fleetAgents until that lands.
}

let reconnectAttempt = 0;

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.addEventListener("open", () => {
    reconnectAttempt = 0;
    connectionStatusEl.textContent = "live";
    connectionStatusEl.className = "connected";
    loadInitialState().catch((err) => console.error("reload after reconnect failed:", err));
  });

  ws.addEventListener("message", (event) => {
    try {
      handleEvent(JSON.parse(event.data));
    } catch (err) {
      console.error("bad WS message:", err);
    }
  });

  ws.addEventListener("close", () => {
    connectionStatusEl.textContent = "reconnecting...";
    connectionStatusEl.className = "disconnected";
    const delay = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempt);
    reconnectAttempt += 1;
    setTimeout(connectWebSocket, delay);
  });

  ws.addEventListener("error", () => ws.close());
}

loadInitialState().catch((err) => console.error("initial load failed:", err));
connectWebSocket();
setInterval(() => loadInitialState().catch((err) => console.error("poll failed:", err)), FALLBACK_POLL_MS);
