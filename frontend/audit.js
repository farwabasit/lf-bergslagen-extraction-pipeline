const timelineEl = document.getElementById("timeline");
const customerIdEl = document.getElementById("customer-id");
const eventCountEl = document.getElementById("event-count");
const integrityBadgeEl = document.getElementById("integrity-badge");
const agentFilterEl = document.getElementById("agent-filter");

const params = new URLSearchParams(window.location.search);
const customerId = params.get("customer_id") || "";

let allEvents = [];

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function titleCase(raw) {
  return String(raw)
    .replace(/[_.]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function decisionClass(decision) {
  return "decision-" + String(decision || "").toLowerCase().replace(/[^a-z]/g, "");
}

function formatTimestamp(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function formatValue(value) {
  if (Array.isArray(value)) return value.map(formatValue).join(", ") || "None";
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(value);
}

// Picks the interesting scalar (non-object, non-array-of-objects) fields
// from an action's recorded details, so the card shows a few readable facts
// up front - the full structure is still one click away via "Raw details".
function pickHighlights(details) {
  const source = details && typeof details === "object"
    ? (details.outputs && typeof details.outputs === "object" ? details.outputs : details)
    : {};

  const skipKeys = new Set(["outputs", "inputs", "reasons", "extra"]);
  const highlights = [];

  for (const [key, value] of Object.entries(source)) {
    if (skipKeys.has(key)) continue;
    if (value !== null && typeof value === "object") continue; // nested - leave to raw view
    highlights.push([titleCase(key), formatValue(value)]);
  }

  // A few fields worth surfacing even when they live one level up in
  // `inputs` (e.g. the loan amount a credit assessment was run against).
  if (details && details.inputs && typeof details.inputs === "object") {
    for (const key of ["loan_amount_sek", "property_value_sek", "monthly_gross_income_sek"]) {
      if (details.inputs[key] !== undefined && !highlights.some(([label]) => label === titleCase(key))) {
        highlights.push([titleCase(key), formatValue(details.inputs[key])]);
      }
    }
  }

  return highlights.slice(0, 8);
}

function reasonsList(details) {
  const reasons = details && (details.reasons || (details.outputs && details.outputs.reasons));
  return Array.isArray(reasons) ? reasons : null;
}

function renderEvent(event) {
  const li = document.createElement("li");
  li.className = "event";
  li.dataset.agent = event.agent || "";

  const dClass = decisionClass(event.decision);
  const highlights = pickHighlights(event.details);
  const reasons = reasonsList(event.details);

  const highlightsHtml = highlights.length
    ? `<ul class="event-highlights">${highlights
        .map(([label, value]) => `<li><span class="hl-label">${escapeHtml(label)}:</span>${escapeHtml(value)}</li>`)
        .join("")}</ul>`
    : "";

  const reasonsHtml = reasons && reasons.length
    ? `<ul class="event-highlights">${reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
    : "";

  li.innerHTML = `
    <span class="event-dot ${dClass}"></span>
    <div class="event-card">
      <div class="event-head">
        <span class="event-title"><span class="event-agent">${escapeHtml(titleCase(event.agent))}</span> — ${escapeHtml(titleCase(event.action))}</span>
        <span class="event-time">${escapeHtml(formatTimestamp(event.ts))}</span>
      </div>
      <span class="event-decision ${dClass}">${escapeHtml(event.decision || "—")}</span>
      ${highlightsHtml}
      ${reasonsHtml}
      <details class="event-details">
        <summary>Raw details</summary>
        <pre>${escapeHtml(JSON.stringify(event.details, null, 2))}</pre>
      </details>
    </div>
  `;
  return li;
}

function renderTimeline() {
  const selectedAgent = agentFilterEl.value;
  const events = allEvents
    .filter((e) => !selectedAgent || e.agent === selectedAgent)
    .slice()
    .sort((a, b) => new Date(b.ts) - new Date(a.ts)); // newest first

  timelineEl.innerHTML = "";
  if (!events.length) {
    timelineEl.innerHTML = '<li class="empty-hint">No agent actions recorded for this customer yet.</li>';
    return;
  }
  for (const event of events) {
    timelineEl.appendChild(renderEvent(event));
  }
}

function populateAgentFilter() {
  const agents = [...new Set(allEvents.map((e) => e.agent).filter(Boolean))].sort();
  for (const agent of agents) {
    const opt = document.createElement("option");
    opt.value = agent;
    opt.textContent = titleCase(agent);
    agentFilterEl.appendChild(opt);
  }
}

async function loadIntegrity() {
  try {
    const res = await fetch("/api/audit/verify");
    const data = await res.json();
    integrityBadgeEl.textContent = data.valid
      ? `Chain verified · ${data.entries} entries`
      : "Integrity check failed";
    integrityBadgeEl.classList.add(data.valid ? "valid" : "invalid");
  } catch {
    integrityBadgeEl.textContent = "Integrity check unavailable";
  }
}

async function loadAuditTrail() {
  customerIdEl.textContent = customerId || "(none given)";

  if (!customerId) {
    timelineEl.innerHTML = '<li class="empty-hint">No customer_id given in the link.</li>';
    eventCountEl.textContent = "0";
    return;
  }

  try {
    const res = await fetch(`/api/audit/${encodeURIComponent(customerId)}`);
    const data = await res.json();
    allEvents = data.events || [];
    eventCountEl.textContent = String(allEvents.length);
    populateAgentFilter();
    renderTimeline();
  } catch {
    timelineEl.innerHTML = '<li class="empty-hint">Could not load the audit trail. Please try again.</li>';
  }
}

agentFilterEl.addEventListener("change", renderTimeline);

loadIntegrity();
loadAuditTrail();
