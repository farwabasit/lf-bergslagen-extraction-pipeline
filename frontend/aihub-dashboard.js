const $ = (id) => document.getElementById(id);

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatNumber(n) {
  return Number(n || 0).toLocaleString();
}

function formatDuration(seconds) {
  if (!seconds) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function shortDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function renderVerticalBars(container, items, { valueKey, labelFn, countLabel }) {
  const max = Math.max(1, ...items.map((i) => i[valueKey]));
  container.innerHTML = items
    .map((item) => {
      const heightPct = Math.round((item[valueKey] / max) * 100);
      return `
        <div class="vbar">
          <span class="vbar-count">${countLabel ? countLabel(item) : item[valueKey]}</span>
          <div class="vbar-fill" style="height:${Math.max(heightPct, 2)}%"></div>
          <span class="vbar-label">${escapeHtml(labelFn(item))}</span>
        </div>`;
    })
    .join("");
}

function renderHorizontalBars(container, items, { valueKey, labelKey, valueFormatter }) {
  if (!items.length) {
    container.innerHTML = '<div class="empty-hint">No interactions recorded yet.</div>';
    return;
  }
  const max = Math.max(1, ...items.map((i) => i[valueKey]));
  container.innerHTML = items
    .map((item) => {
      const widthPct = Math.round((item[valueKey] / max) * 100);
      const value = valueFormatter ? valueFormatter(item) : item[valueKey];
      return `
        <div class="hbar-row">
          <span class="hbar-label" title="${escapeHtml(item[labelKey])}">${escapeHtml(item[labelKey])}</span>
          <div class="hbar-track"><div class="hbar-fill" style="width:${Math.max(widthPct, 2)}%"></div></div>
          <span class="hbar-value">${escapeHtml(String(value))}</span>
        </div>`;
    })
    .join("");
}

function renderMiniList(container, items) {
  if (!items.length) {
    container.innerHTML = '<li class="empty-hint">None yet</li>';
    return;
  }
  container.innerHTML = items
    .map((i) => `<li><span>${escapeHtml(i.label)}</span><span class="count">${formatNumber(i.count)}</span></li>`)
    .join("");
}

function starString(avg) {
  if (avg === null || avg === undefined) return "—";
  const full = Math.round(avg);
  return "★".repeat(full) + "☆".repeat(5 - full);
}

const TOKEN_ROWS = [
  ["today", "Today"],
  ["last_7d", "Last 7 days"],
  ["last_30d", "Last 30 days"],
  ["last_365d", "Last 365 days"],
  ["all_time", "All time"],
];

async function loadDashboard() {
  const [summaryRes, integrityRes] = await Promise.all([
    fetch("/api/metrics/summary?days=14"),
    fetch("/api/audit/verify").catch(() => null),
  ]);

  const data = await summaryRes.json();
  const integrity = integrityRes && integrityRes.ok ? await integrityRes.json() : null;

  // --- Section A: customer interaction performance ---
  $("stat-total-interactions").textContent = formatNumber(data.interactions.total);
  $("stat-total-sessions").textContent = `${formatNumber(data.interactions.total_sessions)} conversations`;

  $("stat-avg-duration").textContent = formatDuration(data.avg_session_duration_seconds);

  $("stat-handoff-pct").textContent = `${data.handoffs.pct_of_sessions}%`;
  $("stat-handoff-count").textContent = `${formatNumber(data.handoffs.sessions)} of ${formatNumber(data.interactions.total_sessions)} conversations`;

  $("stat-cases-pct").textContent = `${data.cases_triggered.pct_of_interactions}%`;
  $("stat-cases-count").textContent = `${formatNumber(data.cases_triggered.count)} of ${formatNumber(data.interactions.total)} interactions`;

  $("stat-satisfaction").textContent = data.satisfaction.average !== null ? data.satisfaction.average.toFixed(2) : "No ratings yet";
  $("satisfaction-stars").textContent = starString(data.satisfaction.average);
  $("stat-satisfaction-count").textContent = `${formatNumber(data.satisfaction.count)} ratings submitted`;

  renderVerticalBars($("volume-chart"), data.interactions.by_day, {
    valueKey: "count",
    labelFn: (i) => shortDate(i.date),
  });

  const satisfactionItems = [1, 2, 3, 4, 5].map((n) => ({
    stars: n,
    count: data.satisfaction.distribution[String(n)] || 0,
  }));
  renderVerticalBars($("satisfaction-chart"), satisfactionItems, {
    valueKey: "count",
    labelFn: (i) => "★".repeat(i.stars),
  });

  renderHorizontalBars($("topics-chart"), data.topics, {
    valueKey: "count",
    labelKey: "label",
    valueFormatter: (i) => `${formatNumber(i.count)} (${i.pct}%)`,
  });

  renderMiniList($("handoff-list"), data.handoffs.by_topic);
  renderMiniList($("cases-list"), data.cases_triggered.by_topic);

  $("customer-insights-body").innerHTML = data.customer_insights.length
    ? data.customer_insights
        .map(
          (i) => `
      <tr>
        <td>${escapeHtml(i.label)}</td>
        <td>${formatNumber(i.count)}</td>
        <td>${i.average.toFixed(2)} ${starString(i.average)}</td>
        <td>${i.needs_attention ? '<span class="badge warn">Needs attention</span>' : ""}</td>
      </tr>`
        )
        .join("")
    : '<tr><td colspan="4" class="empty-hint">No ratings submitted yet.</td></tr>';

  // --- Section B: agent performance / technical ---
  $("stat-total-calls").textContent = formatNumber(data.technical.total_llm_calls);
  const models = Object.entries(data.technical.models_used || {});
  $("stat-models-used").textContent = models.length
    ? models.map(([m, c]) => `${m} (${c})`).join(", ")
    : "No calls yet";

  $("stat-avg-latency").textContent = data.technical.avg_latency_ms !== null
    ? `${Math.round(data.technical.avg_latency_ms)} ms`
    : "—";
  $("stat-avg-tokens").textContent = formatNumber(Math.round(data.technical.avg_tokens_per_call));

  if (integrity) {
    $("stat-audit-integrity").innerHTML = integrity.valid
      ? '<span class="badge valid">Verified</span>'
      : '<span class="badge invalid">Broken</span>';
    $("stat-audit-entries").textContent = `${formatNumber(integrity.entries)} audit entries`;
  } else {
    $("stat-audit-integrity").textContent = "Unavailable";
    $("stat-audit-entries").textContent = "";
  }

  $("token-table-body").innerHTML = TOKEN_ROWS.map(([key, label]) => {
    const t = data.tokens[key];
    return `
      <tr>
        <td>${label}</td>
        <td>${formatNumber(t.calls)}</td>
        <td>${formatNumber(t.prompt_tokens)}</td>
        <td>${formatNumber(t.completion_tokens)}</td>
        <td>${formatNumber(t.total_tokens)}</td>
      </tr>`;
  }).join("");

  $("last-updated").textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()}`;
}

$("refresh-btn").addEventListener("click", () => loadDashboard().catch(console.error));

loadDashboard().catch((err) => {
  console.error(err);
  $("last-updated").textContent = "Could not load metrics";
});

// Keep the dashboard reasonably live for anyone leaving it open on a screen.
setInterval(() => loadDashboard().catch(console.error), 30000);
