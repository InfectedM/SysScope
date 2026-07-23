"use strict";

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtBytes(bps) {
  if (bps < 1024) return bps.toFixed(0) + " B/s";
  if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + " KB/s";
  return (bps / 1024 / 1024).toFixed(2) + " MB/s";
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString("pt-PT");
}

let diskInfo = {};
let lastDisks = [];
const _spark = {};       // disco -> instância uPlot
let _sparkData = {};     // disco -> [ts[], total_bps[]]

async function loadDiskInfo() {
  try {
    diskInfo = await fetch("/api/disks/info").then(r => r.json());
  } catch (e) { diskInfo = diskInfo || {}; }
  if (lastDisks.length) renderDisks(lastDisks);   // re-render com a info nova
}

const DISK_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="2" y="14" width="20" height="7" rx="1.5" stroke="currentColor" stroke-width="2"/><path d="M6.5 20.5v0M2 14 5 4h14l3 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="17.5" cy="17.5" r="1" fill="currentColor"/></svg>';

function fmtRate(bps) {
  const s = fmtBytes(bps);
  const m = s.match(/^([\d.]+)\s(.+)$/);
  return m ? { value: m[1], unit: m[2] } : { value: s, unit: "" };
}

function renderDisks(disks) {
  lastDisks = disks;
  const el = document.getElementById("disk-cards");
  el.innerHTML = "";
  disks.sort((a, b) => a.disk.localeCompare(b.disk));
  for (const d of disks) {
    const isActive = d.power_state === "active";
    const stateLabel = isActive ? "ativo" : "adormecido";
    const stateClass = isActive ? "active" : "standby";
    const info = diskInfo[d.disk] || {};
    const mountLine = (info.mount || info.device)
      ? `${esc(info.mount || "—")} · ${esc(info.device || "—")}` : "";
    const users = (info.users || []);
    const chips = users.length
      ? users.map(u => `<span class="app-chip">${esc(u.name)}${u.files > 1 ? `<span class="chip-count">${u.files}</span>` : ""}</span>`).join("")
      : `<span class="app-chip" style="opacity:.6">—</span>`;
    const rd = fmtRate(d.read_bps), wr = fmtRate(d.write_bps);
    const card = document.createElement("div");
    card.className = "disk-card";
    card.innerHTML = `
      <div class="disk-card-top">
        ${DISK_ICON}
        <span class="disk-name">${esc(d.disk)}</span>
      </div>
      <span class="status-pill ${esc(stateClass)}"><span class="dot"></span>${esc(stateLabel)}</span>
      <div class="rate-row">
        <div class="rate">
          <span class="rate-label">leitura</span>
          <span class="rate-value">${esc(rd.value)}<span class="unit">${esc(rd.unit)}</span></span>
        </div>
        <div class="rate">
          <span class="rate-label">escrita</span>
          <span class="rate-value">${esc(wr.value)}<span class="unit">${esc(wr.unit)}</span></span>
        </div>
      </div>
      ${mountLine ? `<div class="mountinfo" title="${mountLine}">${mountLine}</div>` : ""}
      <div class="used-by">
        <div class="used-by-label">em uso por</div>
        <div class="app-chips">${chips}</div>
      </div>
      <div class="spark" id="spark-${d.disk}"></div>`;
    el.appendChild(card);
  }
  drawSparks();
}

// Sparkline de throughput total (leitura+escrita) por disco, últimos ~10 min.
// Os cartões são reconstruídos a cada tick do WebSocket, por isso os gráficos
// são recriados a partir dos dados em cache (redesenho idêntico, sem cintilação).
async function refreshSparkData() {
  const since = Date.now() / 1000 - 600;
  await Promise.all(lastDisks.map(async (d) => {
    try {
      const rows = await fetch(`/api/disks/${encodeURIComponent(d.disk)}/samples?since=${since}`)
        .then((r) => r.json());
      _sparkData[d.disk] = [
        rows.map((r) => r.ts),
        rows.map((r) => (r.read_bps || 0) + (r.write_bps || 0)),
      ];
    } catch (e) { /* mantém dados anteriores */ }
  }));
  drawSparks();
}

function drawSparks() {
  if (typeof uPlot === "undefined") return;
  for (const d of lastDisks) {
    const el = document.getElementById("spark-" + d.disk);
    if (!el) continue;
    if (_spark[d.disk]) { _spark[d.disk].destroy(); delete _spark[d.disk]; }
    const data = _sparkData[d.disk];
    if (!data || data[0].length < 2) { el.innerHTML = ""; continue; }
    _spark[d.disk] = new uPlot({
      width: el.clientWidth || 220,
      height: 46,
      cursor: { show: false },
      legend: { show: false },
      scales: { x: { time: true } },
      axes: [{ show: false }, { show: false }],
      series: [
        {},
        { stroke: "#a78bfa", width: 1.5, fill: "rgba(139,92,246,.18)",
          points: { show: false } },
      ],
    }, data, el);
  }
}

async function loadIncidents() {
  const res = await fetch("/api/incidents?limit=50");
  const rows = await res.json();
  const tb = document.querySelector("#incident-table tbody");
  tb.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = r.id;
    tr.onclick = () => openIncident(r.id);
    tr.innerHTML = `
      <td class="mono">${fmtTime(r.ts)}</td>
      <td class="mono">${esc(r.disk)}</td>
      <td>${esc(r.detection)}</td>
      <td class="culprit">${esc(r.top_culprit || "…")}</td>`;
    tb.appendChild(tr);
  }
}

async function openIncident(id) {
  const modal = document.getElementById("incident-modal");
  const body = document.getElementById("modal-body");
  body.innerHTML = "a carregar…";
  modal.hidden = false;
  const data = await fetch("/api/incidents/" + id).then(r => r.json());
  const inc = data.incident || {};
  const evs = data.events || [];
  let html = `<div class="summary-line">${esc(inc.disk || "")} · ${esc(inc.detection || "")} · ${fmtTime(inc.ts)} · culpado: <b>${esc(inc.top_culprit || "—")}</b></div>`;
  if (!evs.length) {
    html += `<p class="summary-line">Sem acessos capturados nesta janela.</p>`;
  } else {
    html += `<div class="table-wrap"><table><thead><tr><th>Quando</th><th>Processo</th><th>Op</th><th>Ficheiro</th></tr></thead><tbody>` +
      evs.map(e => `<tr><td class="mono">${fmtTime(e.ts)}</td><td>${esc(e.container || e.comm)}</td><td>${esc(e.op)}</td><td class="mono truncate" title="${esc(e.path)}">${esc(e.path)}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }
  body.innerHTML = html;
}

function closeIncident() { document.getElementById("incident-modal").hidden = true; }

async function loadPatterns() {
  const rows = await fetch("/api/incidents/summary?hours=24").then(r => r.json());
  const el = document.getElementById("incident-patterns");
  if (!rows.length) { el.textContent = "Sem spin-ups nas últimas 24h."; return; }
  el.innerHTML = "<b>Últimas 24h:</b> " + rows.map(r =>
    `<div class="pattern-row"><span class="disk">${esc(r.disk)}</span> — ${r.count}× ` +
    r.culprits.map(c => `<span class="chip">${esc(c.name)} (${c.count})</span>`).join("") +
    `</div>`).join("");
}

function fmtPct(p) { return (p ?? 0).toFixed(1) + "%"; }

async function loadServices() {
  const [svc, cont] = await Promise.all([
    fetch("/api/services").then(r => r.json()),
    fetch("/api/containers").then(r => r.json()),
  ]);
  const sum = document.getElementById("services-summary");
  const failed = (svc.failed || []);
  sum.innerHTML = `${svc.active ?? 0} ativos de ${svc.total ?? 0} serviços · ` +
    (failed.length ? `<span class="danger-text">${failed.length} falhados: ${esc(failed.join(", "))}</span>` : "sem falhas");
  const tb = document.querySelector("#containers-table tbody");
  tb.innerHTML = "";
  cont.sort((a, b) => (b.blk_read + b.blk_write) - (a.blk_read + a.blk_write));
  for (const c of cont) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(c.name)}</td><td class="num">${fmtPct(c.cpu_pct)}</td>` +
      `<td class="num">${fmtBytes(c.mem_used)}</td>` +
      `<td class="num">${fmtBytes(c.net_rx)} / ${fmtBytes(c.net_tx)}</td>` +
      `<td class="num">${fmtBytes(c.blk_read)} / ${fmtBytes(c.blk_write)}</td>`;
    tb.appendChild(tr);
  }
}

async function loadNetwork() {
  const net = await fetch("/api/network").then(r => r.json());
  const nt = document.querySelector("#net-table tbody");
  nt.innerHTML = "";
  for (const i of (net.interfaces || [])) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(i.iface)}</td><td class="num">${fmtBytes(i.rx_bps)}/s</td><td class="num">${fmtBytes(i.tx_bps)}/s</td>`;
    nt.appendChild(tr);
  }
  const ct = document.querySelector("#conn-table tbody");
  ct.innerHTML = "";
  for (const c of (net.connections || []).slice(0, 100)) {
    const tr = document.createElement("tr");
    const local = esc(c.local), remote = esc(c.remote);
    tr.innerHTML = `<td>${esc(c.proto)}</td><td>${esc(c.state)}</td>` +
      `<td class="mono truncate" title="${local}">${local}</td>` +
      `<td class="mono truncate" title="${remote}">${remote}</td>` +
      `<td class="truncate" title="${esc(c.process || "—")}">${esc(c.process || "—")}</td>`;
    ct.appendChild(tr);
  }
}

function fmtDur(s) {
  if (!s) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  return d > 0 ? `${d}d ${h}h` : `${h}h ${Math.floor((s % 3600) / 60)}m`;
}
function fmtWhen(ts) { return ts ? new Date(ts * 1000).toLocaleString("pt-PT") : "—"; }

async function loadSystem() {
  const s = await fetch("/api/system").then(r => r.json());
  const el = document.getElementById("system-body");
  const temps = Object.entries(s.temps || {}).map(([k, v]) => `${esc(k)}: ${v}°C`).join("  ");
  const cells = [
    ["CPU", (s.cpu_percent ?? 0).toFixed(1) + "%"],
    ["Carga", (s.load || []).map(x => x.toFixed(2)).join(" ")],
    ["Memória", `${fmtBytes(s.mem_used || 0)} / ${fmtBytes(s.mem_total || 0)} (${(s.mem_percent ?? 0).toFixed(0)}%)`],
    ["Swap", `${fmtBytes(s.swap_used || 0)} / ${fmtBytes(s.swap_total || 0)}`],
    ["Uptime", fmtDur(s.uptime_seconds)],
    ["Temperaturas", temps || "—"],
  ];
  el.innerHTML = cells.map(([k, v]) =>
    `<div class="metric"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
}

async function loadProcesses() {
  const procs = await fetch("/api/processes").then(r => r.json());
  const tb = document.querySelector("#proc-table tbody");
  tb.innerHTML = "";
  for (const p of procs) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="num">${p.pid}</td><td>${esc(p.name)}</td><td class="num">${(p.cpu_percent ?? 0).toFixed(1)}%</td>` +
      `<td class="num">${fmtBytes(p.mem_bytes || 0)}</td><td class="num">${fmtBytes(p.read_bytes || 0)} / ${fmtBytes(p.write_bytes || 0)}</td>`;
    tb.appendChild(tr);
  }
}

async function loadWakeups() {
  const w = await fetch("/api/wakeups").then(r => r.json());
  const body = document.getElementById("wakeups-body");
  const rtc = w.rtc_wakealarm ? fmtWhen(w.rtc_wakealarm) : "nenhum";
  body.innerHTML = `RTC wakealarm: ${esc(rtc)} · ${(w.cron || []).length} entradas de cron`;
  const tb = document.querySelector("#timers-table tbody");
  tb.innerHTML = "";
  for (const t of (w.timers || [])) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="mono">${esc(t.unit)}</td><td>${esc(t.activates)}</td>` +
      `<td class="mono">${fmtWhen(t.next)}</td><td class="mono">${fmtWhen(t.last)}</td>`;
    tb.appendChild(tr);
  }
}

async function loadAccess() {
  const st = await fetch("/api/settings").then(r => r.json());
  document.querySelectorAll(".access-btn").forEach(b => {
    b.classList.toggle("on", b.dataset.mode === st.bind_mode);
    b.onclick = () => setAccess(b.dataset.mode);
  });
  const urlEl = document.getElementById("access-url");
  urlEl.textContent = (st.bind_mode === "lan" && st.lan_urls.length)
    ? "→ " + st.lan_urls.join("  ") : "";
}

async function setAccess(mode) {
  const cur = document.querySelector(".access-btn.on")?.dataset.mode;
  if (mode === cur) return;
  const isLocal = ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
  if (mode === "localhost" && !isLocal) {
    if (!confirm("Vais desligar o acesso LAN. Esta página (aberta por IP) vai deixar de responder. Continuar?")) return;
  }
  await fetch("/api/settings/bind", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bind_mode: mode }),
  });
  const urlEl = document.getElementById("access-url");
  urlEl.textContent = "a reiniciar…";
  const deadline = Date.now() + 20000;
  const poll = async () => {
    if (Date.now() > deadline) {
      urlEl.textContent = "reinício demorado — recarrega a página manualmente";
      return;
    }
    try {
      const r = await fetch("/api/settings", { cache: "no-store" });
      if (r.ok) { location.reload(); return; }
    } catch (e) { /* servidor ainda a reiniciar */ }
    setTimeout(poll, 1000);
  };
  setTimeout(poll, 2000);
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    renderDisks(data.disks);
  };
  ws.onclose = () => setTimeout(connectWs, 3000);
}

async function init() {
  const res = await fetch("/api/disks");
  renderDisks(await res.json());
  await loadDiskInfo();
  await refreshSparkData();
  await loadIncidents();
  await loadServices();
  await loadNetwork();
  await loadSystem(); await loadProcesses(); await loadWakeups();
  await loadAccess();
  document.getElementById("modal-close").onclick = closeIncident;
  document.getElementById("incident-modal").onclick = (e) => {
    if (e.target.id === "incident-modal") closeIncident();
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeIncident(); });
  await loadPatterns();
  connectWs();
  setInterval(loadDiskInfo, 5000);
  setInterval(refreshSparkData, 5000);
  setInterval(loadIncidents, 10000);
  setInterval(loadServices, 5000);
  setInterval(loadNetwork, 5000);
  setInterval(loadSystem, 5000);
  setInterval(loadProcesses, 5000);
  setInterval(loadWakeups, 15000);
  setInterval(loadPatterns, 15000);
}

init();
