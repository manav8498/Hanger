"use strict";

const KEY_NAME = "hangar_api_key";
const app = document.querySelector("#app");
const modal = document.querySelector("#auth-modal");
const form = document.querySelector("#auth-form");
const keyInput = document.querySelector("#api-key");
const logout = document.querySelector("#logout");
const cancelAuth = document.querySelector("#auth-cancel");
const banner = document.querySelector("#banner");
const sidePanel = document.querySelector("#side-panel");
const sideTitle = document.querySelector("#side-panel-title");
const sideJson = document.querySelector("#side-panel-json");
const sideClose = document.querySelector("#side-panel-close");

let streamAbort = null;
let panelRecords = [];
let detailEvents = [];
let detailSession = null;

function apiKey() {
  return localStorage.getItem(KEY_NAME) || "";
}

function headers(extra = {}) {
  return { "X-API-Key": apiKey(), ...extra };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: headers(options.headers || {}),
  });
  if (response.status === 401) {
    showAuthRejected();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function showAuth() {
  modal.classList.remove("hidden");
  keyInput.value = apiKey();
  keyInput.focus();
}

function hideAuth() {
  if (apiKey()) {
    modal.classList.add("hidden");
  }
}

function showAuthRejected() {
  banner.classList.remove("hidden");
  banner.innerHTML = 'API key rejected. <button class="ghost" type="button">Log out</button>';
  banner.querySelector("button").addEventListener("click", () => {
    localStorage.removeItem(KEY_NAME);
    showAuth();
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  localStorage.setItem(KEY_NAME, keyInput.value.trim());
  hideAuth();
  render();
});

cancelAuth.addEventListener("click", () => showAuth());
logout.addEventListener("click", () => {
  localStorage.removeItem(KEY_NAME);
  window.location.reload();
});
sideClose.addEventListener("click", closePanel);
window.addEventListener("hashchange", render);

if (!apiKey()) {
  showAuth();
} else {
  hideAuth();
}
render();

async function render() {
  abortStream();
  closePanel();
  setActiveNav();
  if (!apiKey()) {
    app.innerHTML = "";
    return;
  }

  const hash = window.location.hash || "#/";
  try {
    if (hash === "#/" || hash === "#") {
      await renderOverview();
    } else if (hash === "#/agents") {
      await renderAgents();
    } else if (hash === "#/environments") {
      await renderEnvironments();
    } else if (hash === "#/sessions") {
      await renderSessions();
    } else if (hash.startsWith("#/sessions/")) {
      await renderSessionDetail(decodeURIComponent(hash.slice("#/sessions/".length)));
    } else {
      app.innerHTML = `<section class="section"><h1>Not found</h1></section>`;
    }
  } catch (error) {
    if (error.message !== "unauthorized") {
      app.innerHTML = `<section class="section"><h1>Error</h1><p class="muted">${escapeHtml(error.message)}</p></section>`;
    }
  }
}

function setActiveNav() {
  const hash = window.location.hash || "#/";
  document.querySelectorAll(".nav a").forEach((link) => {
    const href = link.getAttribute("href");
    const active = href === hash || (href === "#/sessions" && hash.startsWith("#/sessions/"));
    link.classList.toggle("active", active);
  });
}

async function renderOverview() {
  app.innerHTML = loading("Overview");
  const [health, agents, environments, sessions] = await Promise.all([
    api("/healthz"),
    list("/v1/agents"),
    list("/v1/environments"),
    list("/v1/sessions"),
  ]);
  const activeSessions = sessions.filter((session) => session.status !== "terminated");
  const recentEvents = await loadRecentEvents(sessions);
  app.innerHTML = `
    <section class="section">
      <div class="section-head">
        <h1>Overview</h1>
        <button id="refresh" class="ghost" type="button">Refresh</button>
      </div>
      ${healthHtml(health)}
    </section>
    <section class="section grid counts">
      ${countCard("Agents", agents.length)}
      ${countCard("Environments", environments.length)}
      ${countCard("Active sessions", activeSessions.length)}
    </section>
    <section class="section">
      <h2>Recent events</h2>
      ${eventsTable(recentEvents)}
    </section>`;
  document.querySelector("#refresh").addEventListener("click", renderOverview);
}

async function renderAgents() {
  app.innerHTML = loading("Agents");
  const agents = sortByCreated(await list("/v1/agents"));
  panelRecords = agents;
  app.innerHTML = `
    <section class="section">
      <h1>Agents</h1>
      ${table(["id", "name", "model", "version", "created_at", "archived"], agents.map((agent, index) => ({
        index,
        values: [
          mono(agent.id),
          escapeHtml(agent.name || ""),
          escapeHtml(agent.model?.id || ""),
          escapeHtml(String(agent.version ?? "")),
          timeLabel(agent.created_at),
          agent.archived_at ? "yes" : "no",
        ],
      })))}
    </section>`;
  bindPanelRows("Agent");
}

async function renderEnvironments() {
  app.innerHTML = loading("Environments");
  const environments = sortByCreated(await list("/v1/environments"));
  panelRecords = environments;
  app.innerHTML = `
    <section class="section">
      <h1>Environments</h1>
      ${table(["id", "name", "type", "archived", "created_at"], environments.map((environment, index) => ({
        index,
        values: [
          mono(environment.id),
          escapeHtml(environment.name || ""),
          escapeHtml(environment.config?.type || ""),
          environment.archived_at ? "yes" : "no",
          timeLabel(environment.created_at),
        ],
      })))}
    </section>`;
  bindPanelRows("Environment");
}

async function renderSessions() {
  app.innerHTML = loading("Sessions");
  const sessions = sortByCreated(await list("/v1/sessions"));
  app.innerHTML = `
    <section class="section">
      <h1>Sessions</h1>
      ${sessionsTable(sessions)}
    </section>`;
}

async function renderSessionDetail(sessionId) {
  app.innerHTML = loading("Session");
  const [session, eventBody] = await Promise.all([
    api(`/v1/sessions/${encodeURIComponent(sessionId)}`),
    api(`/v1/sessions/${encodeURIComponent(sessionId)}/events?limit=1000`),
  ]);
  detailSession = session;
  detailEvents = eventBody.data || [];
  drawSessionDetail();
  const lastId = maxEventId(detailEvents);
  connectStream(sessionId, lastId);
}

function drawSessionDetail(ended = false) {
  const counts = eventCounts(detailEvents);
  app.innerHTML = `
    <section class="detail-layout">
      <aside class="detail-left">
        <div class="detail-head">
          <h1>Session</h1>
          <a href="#/sessions">Back</a>
        </div>
        ${ended ? '<div class="status-card"><strong>session ended</strong></div>' : ""}
        <div class="meta-card">${sessionMeta(detailSession)}</div>
        <div class="meta-card">
          ${metaRow("total events", `<span id="count-total">${counts.total}</span>`)}
          ${metaRow("agent messages", `<span id="count-messages">${counts.messages}</span>`)}
          ${metaRow("tool uses", `<span id="count-tools">${counts.tools}</span>`)}
          ${metaRow("errors", `<span id="count-errors">${counts.errors}</span>`)}
        </div>
      </aside>
      <section>
        <div class="section-head">
          <h2>Event log</h2>
          <button id="load-history" class="ghost" type="button">Load history</button>
        </div>
        <div id="event-log" class="event-log">${detailEvents.map(eventCard).join("")}</div>
      </section>
    </section>`;
  document.querySelector("#load-history").addEventListener("click", async () => {
    const body = await api(`/v1/sessions/${encodeURIComponent(detailSession.id)}/events?limit=1000`);
    detailEvents = body.data || [];
    drawSessionDetail(ended);
  });
  bindExpandButtons();
  scrollLogBottom();
}

async function list(path) {
  const body = await api(path);
  return body.data || [];
}

async function loadRecentEvents(sessions) {
  const recentSessions = sortByCreated(sessions).slice(0, 5);
  const batches = await Promise.all(
    recentSessions.map((session) => api(`/v1/sessions/${encodeURIComponent(session.id)}/events?limit=2`))
  );
  return batches
    .flatMap((batch) => batch.data || [])
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .slice(0, 10);
}

function connectStream(sessionId, lastId) {
  streamAbort = new AbortController();
  const streamHeaders = headers(lastId ? { "Last-Event-ID": String(lastId) } : {});
  fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/events/stream`, {
    headers: streamHeaders,
    signal: streamAbort.signal,
  })
    .then((response) => {
      if (response.status === 401) {
        showAuthRejected();
        throw new Error("unauthorized");
      }
      if (!response.ok || !response.body) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      return readSse(response.body.getReader(), sessionId);
    })
    .catch((error) => {
      if (error.name !== "AbortError" && error.message !== "unauthorized") {
        showBanner(`stream error: ${error.message}`);
      }
    });
}

async function readSse(reader, sessionId) {
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      return;
    }
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replaceAll("\r\n", "\n");
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const event = parseSse(part, sessionId);
      if (!event || event.type === "ping") {
        continue;
      }
      detailEvents.push(event);
      appendEvent(event);
      if (event.type === "session.status_idle" || event.type === "session.status_terminated") {
        detailSession.status = event.type === "session.status_idle" ? "idle" : "terminated";
        abortStream();
        drawSessionDetail(true);
        showBanner("session ended");
        return;
      }
    }
  }
}

function parseSse(block, sessionId) {
  const lines = block.split("\n");
  let id = "";
  let type = "message";
  let data = "";
  for (const line of lines) {
    if (line.startsWith("id:")) id = line.slice(3).trim();
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  return { id, type, session_id: sessionId, content: safeJson(data), created_at: null };
}

function appendEvent(event) {
  const log = document.querySelector("#event-log");
  if (!log) return;
  log.insertAdjacentHTML("beforeend", eventCard(event));
  updateDetailCounts();
  bindExpandButtons();
  scrollLogBottom();
}

function updateDetailCounts() {
  const counts = eventCounts(detailEvents);
  const fields = {
    "#count-total": counts.total,
    "#count-messages": counts.messages,
    "#count-tools": counts.tools,
    "#count-errors": counts.errors,
  };
  Object.entries(fields).forEach(([selector, value]) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = String(value);
  });
}

function healthHtml(health) {
  const components = health.components || {};
  const rows = ["database", "dbos", "docker"]
    .map((name) => {
      const item = components[name] || {};
      return `<div class="component-row"><span>${name}</span>${badge(item.status || "unknown")}<span>${componentDetail(item)}</span></div>`;
    })
    .join("");
  return `<div class="status-card">
    <div class="section-head"><h2>Hangar ${escapeHtml(health.version || "")}</h2>${badge(health.status)}</div>
    ${rows}
  </div>`;
}

function countCard(label, value) {
  return `<div class="count-card"><span class="muted">${label}</span><strong>${value}</strong></div>`;
}

function eventsTable(events) {
  if (!events.length) return empty("No recent events.");
  return `<div class="table-wrap"><table><thead><tr><th>time</th><th>session</th><th>type</th><th>summary</th></tr></thead><tbody>
    ${events.map((event) => `<tr><td class="mono">${timeLabel(event.created_at)}</td><td>${sessionLink(event.session_id)}</td><td>${badge(event.type)}</td><td>${escapeHtml(eventSummary(event.type, event.content || {}))}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function table(headers, rows) {
  if (!rows.length) return empty("No rows.");
  return `<div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead><tbody>
    ${rows.map((row) => `<tr class="clickable" data-panel-index="${row.index}">${row.values.map((value) => `<td>${value}</td>`).join("")}</tr>`).join("")}
  </tbody></table></div>`;
}

function sessionsTable(sessions) {
  if (!sessions.length) return empty("No sessions.");
  return `<div class="table-wrap"><table><thead><tr><th>id</th><th>agent</th><th>title</th><th>status</th><th>created</th><th>updated</th></tr></thead><tbody>
    ${sessions.map((session) => `<tr><td>${sessionLink(session.id)}</td><td class="mono">${shortId(session.agent_id)}</td><td>${escapeHtml(session.title || "")}</td><td>${badge(session.status)}</td><td class="mono">${timeLabel(session.created_at)}</td><td class="mono">${timeLabel(session.updated_at)}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function sessionMeta(session) {
  return [
    metaRow("id", mono(session.id)),
    metaRow("title", escapeHtml(session.title || "")),
    metaRow("status", badge(session.status)),
    metaRow("agent", mono(session.agent_id)),
    metaRow("environment", mono(session.environment_id)),
    metaRow("created", timeLabel(session.created_at)),
    metaRow("updated", timeLabel(session.updated_at)),
    session.stop_reason ? metaRow("stop reason", escapeHtml(JSON.stringify(session.stop_reason))) : "",
  ].join("");
}

function eventCard(event) {
  const content = event.content || {};
  return `<article class="event-card">
    <div class="event-meta"><span class="mono">${timeLabel(event.created_at)}</span>${badge(event.type)}<span>${escapeHtml(eventSummary(event.type, content))}</span></div>
    <button class="ghost expand" type="button">Expand</button>
    <pre class="event-json hidden">${escapeHtml(JSON.stringify(content, null, 2))}</pre>
  </article>`;
}

function bindPanelRows(title) {
  document.querySelectorAll("[data-panel-index]").forEach((row) => {
    row.addEventListener("click", () => openPanel(title, panelRecords[Number(row.dataset.panelIndex)]));
  });
}

function bindExpandButtons() {
  document.querySelectorAll(".expand").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => {
      const json = button.parentElement.querySelector(".event-json");
      json.classList.toggle("hidden");
      button.textContent = json.classList.contains("hidden") ? "Expand" : "Collapse";
    });
  });
}

function openPanel(title, record) {
  sideTitle.textContent = title;
  sideJson.textContent = JSON.stringify(record, null, 2);
  sidePanel.classList.add("open");
  sidePanel.setAttribute("aria-hidden", "false");
}

function closePanel() {
  sidePanel.classList.remove("open");
  sidePanel.setAttribute("aria-hidden", "true");
}

function abortStream() {
  if (streamAbort) {
    streamAbort.abort();
    streamAbort = null;
  }
}

function eventCounts(events) {
  return {
    total: events.length,
    messages: events.filter((event) => event.type === "agent.message").length,
    tools: events.filter((event) => event.type === "agent.tool_use").length,
    errors: events.filter((event) => event.type === "session.error" || event.type === "session.status_error").length,
  };
}

function eventSummary(type, content) {
  let summary = JSON.stringify(content);
  if (type === "agent.message") summary = contentText(content) || summary;
  if (type === "session.status_idle") summary = content.stop_reason?.type || "idle";
  if (type.startsWith("session.status_")) summary = type.replace("session.status_", "");
  if (type === "session.error") summary = content.message || "error";
  if (type === "agent.tool_use") summary = content.name || "tool";
  if (type === "span.model_request_end") summary = JSON.stringify(content.usage || content);
  return clip(summary, 180);
}

function contentText(content) {
  const blocks = Array.isArray(content.content) ? content.content : [];
  return blocks.map((block) => block.text || "").join("");
}

function componentDetail(component) {
  if (Number.isInteger(component.latency_ms)) return `${component.latency_ms}ms`;
  if (Number.isInteger(component.active_workflows)) return `${component.active_workflows} workflows`;
  if (Number.isInteger(component.container_count)) return `${component.container_count} containers`;
  return component.reason || "-";
}

function statusClass(status) {
  if (status === "agent.message") return "agent-message";
  if (status.includes("error")) return "error";
  if (status.includes("terminated")) return "terminated";
  if (status.includes("idle")) return "idle";
  if (status.includes("running")) return "running";
  if (status.includes("starting")) return "starting";
  if (status.includes("degraded")) return "degraded";
  if (status.includes("skipped")) return "skipped";
  if (status === "ok") return "ok";
  return "skipped";
}

function badge(status) {
  const safe = escapeHtml(String(status || "unknown"));
  return `<span class="badge ${statusClass(safe)}">${safe}</span>`;
}

function timeLabel(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return new Date().toLocaleTimeString([], timeOptions());
  return date.toLocaleTimeString([], timeOptions());
}

function timeOptions() {
  return { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
}

function sortByCreated(rows) {
  return [...rows].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
}

function maxEventId(events) {
  return events.reduce((max, event) => Math.max(max, Number(event.id) || 0), 0);
}

function metaRow(label, value) {
  return `<div class="meta-row"><span class="muted">${label}</span><span>${value}</span></div>`;
}

function sessionLink(id) {
  return `<a class="mono" href="#/sessions/${encodeURIComponent(id)}">${escapeHtml(id)}</a>`;
}

function shortId(id) {
  const value = String(id || "");
  const [prefix, rest] = value.split("_");
  return rest ? `${prefix}_${rest.slice(0, 8)}` : value.slice(0, 12);
}

function mono(value) {
  return `<span class="mono truncate">${escapeHtml(String(value || ""))}</span>`;
}

function empty(text) {
  return `<p class="muted">${escapeHtml(text)}</p>`;
}

function loading(title) {
  return `<section class="section"><h1>${escapeHtml(title)}</h1><p class="muted">loading...</p></section>`;
}

function showBanner(text) {
  banner.classList.remove("hidden");
  banner.textContent = text;
}

function scrollLogBottom() {
  const log = document.querySelector("#event-log");
  if (log) log.lastElementChild?.scrollIntoView({ block: "end", inline: "nearest" });
}

function clip(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function safeJson(data) {
  try {
    return JSON.parse(data);
  } catch {
    return { data };
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
