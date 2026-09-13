// The AI-assistant app's own base URL, called directly from this page (a
// different app/origin) to keep the transcript live after pickup, and by
// the Java backend itself to relay replies. Demo default; change if the
// Python app runs somewhere else.
const PYTHON_APP_BASE = "http://localhost:8000";

const agentNameEl = document.getElementById("agent-name");
const agentNameLabelEl = document.getElementById("agent-name-label");
agentNameEl.value = localStorage.getItem("cs-agent-name") || "";
agentNameEl.addEventListener("input", () => {
  localStorage.setItem("cs-agent-name", agentNameEl.value);
});

function agentName() {
  return agentNameEl.value.trim() || "Unnamed agent";
}

// --- Role (RBAC) ---
//
// The role is self-declared by this page and sent as an X-CS-Role header on
// every request that touches cases or chat hand-offs. The SERVER enforces
// it (see CaseController/ChatRequestController) - hiding a tab here is only
// a convenience for a legitimate user, not the actual access control.
// NOTE: there is no login in this demo, so this is authorization without
// authentication - anyone could change their declared role. A real
// deployment needs the role to come from a verified identity/session, not
// a client-side dropdown.

const roleSelectEl = document.getElementById("role-select");
const roleGateSelectEl = document.getElementById("role-gate-select");
const roleGateEl = document.getElementById("role-gate");
let currentRole = localStorage.getItem("cs-role") || "";
roleSelectEl.value = currentRole;
roleGateSelectEl.value = currentRole;

const AGENT_NAME_LABELS = {
  CS_REP: "Agent name",
  ADVISOR: "Advisor name",
  OPERATIONS: "Operations name",
};

function authFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentRole) headers["X-CS-Role"] = currentRole;
  return fetch(url, { ...options, headers });
}

// CS_REP now has both tabs available (chats are still their primary job;
// Case Queue is where they pick up Fraud/Dispute cases) - default them to
// chats rather than whichever tab happens to come first in the DOM.
const PREFERRED_DEFAULT_TAB = { CS_REP: "chats", ADVISOR: "cases", OPERATIONS: "cases" };

function applyRoleVisibility() {
  roleGateEl.hidden = Boolean(currentRole);
  roleSelectEl.value = currentRole;
  roleGateSelectEl.value = currentRole;
  agentNameLabelEl.textContent = AGENT_NAME_LABELS[currentRole] || "Agent name";

  const tabButtons = document.querySelectorAll(".tab-btn");
  let preferredTab = null;
  let firstAllowedTab = null;
  tabButtons.forEach((btn) => {
    const allowedRoles = btn.dataset.roles.split(",");
    const allowed = allowedRoles.includes(currentRole);
    btn.hidden = !allowed;
    if (allowed && !firstAllowedTab) firstAllowedTab = btn;
    if (allowed && btn.dataset.tab === PREFERRED_DEFAULT_TAB[currentRole]) preferredTab = btn;
  });

  const activeTabBtn = document.querySelector(".tab-btn.active");
  if (!activeTabBtn || activeTabBtn.hidden) {
    const targetTab = preferredTab || firstAllowedTab;
    tabButtons.forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    if (targetTab) {
      targetTab.classList.add("active");
      document.getElementById(`tab-${targetTab.dataset.tab}`).classList.add("active");
    }
  }

  updateTypeFilterOptions();
  if (currentRole === "ADVISOR" || currentRole === "OPERATIONS" || currentRole === "CS_REP") loadCases();
  if (currentRole === "CS_REP") loadChatRequests();
}

function onRoleChosen(role) {
  currentRole = role;
  localStorage.setItem("cs-role", currentRole);
  applyRoleVisibility();
}

roleSelectEl.addEventListener("change", () => onRoleChosen(roleSelectEl.value));
roleGateSelectEl.addEventListener("change", () => onRoleChosen(roleGateSelectEl.value));

// --- Tabs ---

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.hidden) return;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// --- Cases ---

const caseListEl = document.getElementById("case-list");
const filterTypeEl = document.getElementById("filter-type");
const filterStatusEl = document.getElementById("filter-status");

const ROLE_CASE_TYPES = {
  ADVISOR: ["CALLBACK", "MORTGAGE_APPLICATION", "MORTGAGE_REVIEW", "OTHER"],
  CS_REP: ["FRAUD", "DISPUTE"],
  OPERATIONS: ["MORTGAGE_OPERATIONS", "FRAUD", "DISPUTE"],
};

function updateTypeFilterOptions() {
  const allowedTypes = ROLE_CASE_TYPES[currentRole];
  filterTypeEl.querySelectorAll("option[value]").forEach((opt) => {
    if (!opt.value) return; // "All types"
    opt.hidden = Boolean(allowedTypes) && !allowedTypes.includes(opt.value);
  });
  if (filterTypeEl.value && allowedTypes && !allowedTypes.includes(filterTypeEl.value)) {
    filterTypeEl.value = "";
  }
}

function formatType(type) {
  return type.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatStatus(status) {
  return status.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

async function loadCases() {
  if (!currentRole) return;
  const params = new URLSearchParams();
  if (filterTypeEl.value) params.set("type", filterTypeEl.value);
  if (filterStatusEl.value) params.set("status", filterStatusEl.value);
  try {
    const res = await authFetch(`/api/cases?${params}`);
    if (res.status === 403) {
      caseListEl.innerHTML = `<div class="empty-hint">Your role (${currentRole}) isn't authorized to view cases.</div>`;
      return;
    }
    const cases = await res.json();
    caseListEl.innerHTML = "";
    if (!cases.length) {
      caseListEl.innerHTML = `<div class="empty-hint">No cases match these filters.</div>`;
      return;
    }
    for (const c of cases) {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div class="card-main">
          <span class="card-title">${c.id} — ${formatType(c.type)}</span>
          <span class="card-sub">${c.customerName || "Unknown customer"} · ${timeAgo(c.createdAt)}${c.assignedAgent ? ` · ${c.assignedAgent}` : ""}</span>
        </div>
        <span class="badge ${c.status}">${formatStatus(c.status)}</span>
      `;
      card.addEventListener("click", () => openCaseModal(c));
      caseListEl.appendChild(card);
    }
  } catch (err) {
    caseListEl.innerHTML = `<div class="empty-hint">Could not load cases. Is the service running?</div>`;
  }
}

document.getElementById("refresh-cases").addEventListener("click", loadCases);
filterTypeEl.addEventListener("change", loadCases);
filterStatusEl.addEventListener("change", loadCases);

// --- Case detail modal ---

const caseModal = document.getElementById("case-modal");
const caseModalTitle = document.getElementById("case-modal-title");
const caseModalBody = document.getElementById("case-modal-body");

// "propertyAddress" -> "Property Address" - so the customer-provided,
// document-extracted, and agent-decision fields an Advisor/Operations
// needs to see (stuffed into `extra` by the agents) read naturally instead
// of as raw camelCase keys.
function formatExtraKey(key) {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/^./, (c) => c.toUpperCase());
}

function openCaseModal(c) {
  caseModalTitle.textContent = `${c.id} — ${formatType(c.type)}`;
  const extra = c.extra || {};
  const extraRows = Object.entries(extra)
    .filter(([k]) => k !== "auditCustomerId")
    .map(([k, v]) => `<dt>${formatExtraKey(k)}</dt><dd>${v}</dd>`)
    .join("");
  const auditLink = extra.auditCustomerId
    ? `<dt>Audit trail</dt><dd><a href="${PYTHON_APP_BASE}/api/audit/${extra.auditCustomerId}" target="_blank" rel="noopener">View full decision history ↗</a></dd>`
    : "";

  const approveBtn =
    currentRole === "ADVISOR" && c.type === "MORTGAGE_REVIEW"
      ? `<button data-action="approve-to-ops">Approve → send to Operations</button>`
      : "";
  const submitBtn =
    currentRole === "CS_REP" &&
    (c.type === "FRAUD" || c.type === "DISPUTE") &&
    c.status !== "SUBMITTED" &&
    c.status !== "RESOLVED"
      ? `<button data-action="submit-to-ops">Submit to Operations</button>`
      : "";

  caseModalBody.innerHTML = `
    <dl>
      <dt>Status</dt><dd><span class="badge ${c.status}">${formatStatus(c.status)}</span></dd>
      <dt>Customer</dt><dd>${c.customerName || "—"}${c.customerId ? ` (${c.customerId})` : ""}</dd>
      <dt>Description</dt><dd>${c.description || "—"}</dd>
      <dt>Assigned agent</dt><dd>${c.assignedAgent || "Not yet assigned"}</dd>
      <dt>Created</dt><dd>${new Date(c.createdAt).toLocaleString()}</dd>
      ${extraRows}
      ${auditLink}
    </dl>
    <div class="modal-actions">
      <button data-action="pickup">Pick up</button>
      <button class="secondary" data-action="in-progress">Mark In Progress</button>
      <button class="secondary" data-action="resolved">Mark Resolved</button>
      ${approveBtn}
      ${submitBtn}
    </div>
    <p id="case-modal-error" class="reply-status error"></p>
  `;
  caseModalBody.querySelector('[data-action="pickup"]').addEventListener("click", async () => {
    const res = await authFetch(`/api/cases/${c.id}/pickup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: agentName() }),
    });
    if (!handleCaseActionResponse(res)) return;
    closeCaseModal();
    loadCases();
  });
  caseModalBody.querySelector('[data-action="in-progress"]').addEventListener("click", () => setCaseStatus(c.id, "IN_PROGRESS"));
  caseModalBody.querySelector('[data-action="resolved"]').addEventListener("click", () => setCaseStatus(c.id, "RESOLVED"));
  const approveEl = caseModalBody.querySelector('[data-action="approve-to-ops"]');
  if (approveEl) {
    approveEl.addEventListener("click", async () => {
      const res = await authFetch(`/api/cases/${c.id}/approve-to-operations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: agentName() }),
      });
      if (!handleCaseActionResponse(res)) return;
      closeCaseModal();
      loadCases();
    });
  }
  const submitEl = caseModalBody.querySelector('[data-action="submit-to-ops"]');
  if (submitEl) {
    submitEl.addEventListener("click", async () => {
      const res = await authFetch(`/api/cases/${c.id}/submit-to-operations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: agentName() }),
      });
      if (!handleCaseActionResponse(res)) return;
      closeCaseModal();
      loadCases();
    });
  }
  caseModal.hidden = false;
}

async function handleCaseActionResponse(res) {
  if (res.ok) return true;
  const errEl = document.getElementById("case-modal-error");
  if (!errEl) return false;
  if (res.status === 403) {
    errEl.textContent = `Your role (${currentRole}) isn't authorized for this action.`;
  } else if (res.status === 409) {
    const data = await res.json().catch(() => ({}));
    errEl.textContent = data.detail || data.message || "This case isn't ready for your role to act on yet.";
  } else {
    errEl.textContent = `Something went wrong (${res.status}).`;
  }
  return false;
}

async function setCaseStatus(caseId, status) {
  const res = await authFetch(`/api/cases/${caseId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!handleCaseActionResponse(res)) return;
  closeCaseModal();
  loadCases();
}

function closeCaseModal() {
  caseModal.hidden = true;
}

document.getElementById("case-modal-close").addEventListener("click", closeCaseModal);
caseModal.addEventListener("click", (e) => {
  if (e.target === caseModal) closeCaseModal();
});

// --- Chat requests ---

const chatRequestListEl = document.getElementById("chat-request-list");
const chatDetailEmptyEl = document.getElementById("chat-detail-empty");
const chatDetailEl = document.getElementById("chat-detail");
const chatDetailTitleEl = document.getElementById("chat-detail-title");
const chatTranscriptEl = document.getElementById("chat-transcript");
const pickupChatBtn = document.getElementById("pickup-chat-btn");
const replyForm = document.getElementById("reply-form");
const replyInput = document.getElementById("reply-input");
const replyStatusEl = document.getElementById("reply-status");

let selectedSessionId = null;
let livePollTimer = null;

async function loadChatRequests() {
  if (!currentRole) return;
  try {
    const res = await authFetch("/api/chat-requests");
    if (res.status === 403) {
      chatRequestListEl.innerHTML = `<div class="empty-hint">Your role (${currentRole}) isn't authorized to view chat requests.</div>`;
      return;
    }
    const requests = await res.json();
    chatRequestListEl.innerHTML = "";
    if (!requests.length) {
      chatRequestListEl.innerHTML = `<div class="empty-hint">No chat requests yet.</div>`;
      return;
    }
    for (const r of requests) {
      const card = document.createElement("div");
      card.className = "card" + (r.sessionId === selectedSessionId ? " active" : "");
      card.innerHTML = `
        <div class="card-main">
          <span class="card-title">${r.customerSummary || "Customer chat"}</span>
          <span class="card-sub">${r.sessionId.slice(0, 8)}… · ${timeAgo(r.createdAt)}${r.assignedAgent ? ` · ${r.assignedAgent}` : ""}</span>
        </div>
        <span class="badge ${r.status}">${formatStatus(r.status)}</span>
      `;
      card.addEventListener("click", () => selectChatRequest(r.sessionId));
      chatRequestListEl.appendChild(card);
    }
  } catch (err) {
    chatRequestListEl.innerHTML = `<div class="empty-hint">Could not load chat requests. Is the service running?</div>`;
  }
}

document.getElementById("refresh-chats").addEventListener("click", loadChatRequests);

function roleLabel(m) {
  if (m.role === "assistant") return "Sara (AI assistant)";
  if (m.role === "human") return m.agent_name || "CS Agent";
  return "Customer";
}

function renderTranscript(messages) {
  chatTranscriptEl.innerHTML = "";
  for (const m of messages) {
    const div = document.createElement("div");
    const role = m.role === "assistant" ? "assistant" : m.role === "human" ? "human" : "user";
    div.className = `transcript-msg ${role}`;
    div.innerHTML = `<span class="role-label">${roleLabel(m)}</span>`;
    div.appendChild(document.createTextNode(m.content));
    chatTranscriptEl.appendChild(div);
  }
  chatTranscriptEl.scrollTop = chatTranscriptEl.scrollHeight;
}

async function selectChatRequest(sessionId) {
  selectedSessionId = sessionId;
  chatDetailEmptyEl.hidden = true;
  chatDetailEl.hidden = false;
  replyStatusEl.textContent = "";
  replyStatusEl.className = "reply-status";

  const res = await authFetch(`/api/chat-requests/${sessionId}`);
  if (res.status === 403) {
    replyStatusEl.textContent = `Your role (${currentRole}) isn't authorized to open chat requests.`;
    replyStatusEl.className = "reply-status error";
    return;
  }
  const request = await res.json();
  chatDetailTitleEl.textContent = request.customerSummary || "Customer chat";
  renderTranscript(request.transcript);

  loadChatRequests();
  startLivePolling(sessionId);
}

function startLivePolling(sessionId) {
  if (livePollTimer) clearInterval(livePollTimer);
  livePollTimer = setInterval(async () => {
    if (selectedSessionId !== sessionId) return;
    try {
      // Polls the AI-assistant app directly (a different application) so
      // new customer messages sent after hand-off still show up here.
      const res = await fetch(`${PYTHON_APP_BASE}/api/sessions/${sessionId}`);
      if (!res.ok) return;
      const data = await res.json();
      renderTranscript(data.messages);
    } catch (err) {
      // Silent - background poll, and the Python app may be on a different
      // origin/port that isn't reachable from here in some setups.
    }
  }, 4000);
}

pickupChatBtn.addEventListener("click", async () => {
  if (!selectedSessionId) return;
  const res = await authFetch(`/api/chat-requests/${selectedSessionId}/pickup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent: agentName() }),
  });
  if (res.status === 403) {
    replyStatusEl.textContent = `Your role (${currentRole}) isn't authorized to pick up chats.`;
    replyStatusEl.className = "reply-status error";
    return;
  }
  loadChatRequests();
});

replyForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedSessionId) return;
  const message = replyInput.value.trim();
  if (!message) return;

  replyStatusEl.textContent = "Sending...";
  replyStatusEl.className = "reply-status";
  try {
    const res = await authFetch(`/api/chat-requests/${selectedSessionId}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: agentName(), message }),
    });
    if (!res.ok) {
      if (res.status === 403) {
        throw new Error(`Your role (${currentRole}) isn't authorized to reply to chats.`);
      }
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Server responded with ${res.status}`);
    }
    replyInput.value = "";
    replyStatusEl.textContent = "Sent.";
    const sentAt = selectedSessionId;
    setTimeout(() => {
      if (selectedSessionId === sentAt) selectChatRequest(sentAt);
    }, 300);
    loadChatRequests();
  } catch (err) {
    replyStatusEl.textContent = err.message;
    replyStatusEl.className = "reply-status error";
  }
});

// --- Init ---

applyRoleVisibility();
setInterval(() => {
  if (currentRole === "ADVISOR" || currentRole === "OPERATIONS" || currentRole === "CS_REP") loadCases();
}, 10000);
setInterval(() => {
  if (currentRole === "CS_REP") loadChatRequests();
}, 6000);
