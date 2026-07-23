"use strict";

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function fmtBytes(bps) {
  if (bps < 1024) return bps.toFixed(0) + " B/s";
  if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + " KB/s";
  return (bps / 1024 / 1024).toFixed(2) + " MB/s";
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString("pt-PT");
}

function renderDisks(disks) {
  const el = document.getElementById("disk-cards");
  el.innerHTML = "";
  disks.sort((a, b) => a.disk.localeCompare(b.disk));
  for (const d of disks) {
    const spun = (d.power_state === "standby" || d.power_state === "sleeping");
    const stateLabel = spun ? "adormecido" :
      (d.power_state === "active" ? "ativo" :
       d.power_state === "unknown" ? "desconhecido" : d.power_state);
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="name">${esc(d.disk)}</div>
      <span class="state ${d.power_state}">${esc(stateLabel)}</span>
      <div class="io">
        leitura: ${fmtBytes(d.read_bps)}<br>
        escrita: ${fmtBytes(d.write_bps)}
      </div>`;
    el.appendChild(card);
  }
}

async function loadIncidents() {
  const res = await fetch("/api/incidents?limit=50");
  const rows = await res.json();
  const tb = document.querySelector("#incident-table tbody");
  tb.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtTime(r.ts)}</td>
      <td>${esc(r.disk)}</td>
      <td>${esc(r.detection)}</td>
      <td class="culprit">${esc(r.top_culprit || "…")}</td>`;
    tb.appendChild(tr);
  }
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
    (failed.length ? `<span style="color:#f87171">${failed.length} falhados: ${esc(failed.join(", "))}</span>` : "sem falhas");
  const tb = document.querySelector("#containers-table tbody");
  tb.innerHTML = "";
  cont.sort((a, b) => (b.blk_read + b.blk_write) - (a.blk_read + a.blk_write));
  for (const c of cont) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(c.name)}</td><td>${fmtPct(c.cpu_pct)}</td>` +
      `<td>${fmtBytes(c.mem_used)}</td>` +
      `<td>${fmtBytes(c.net_rx)} / ${fmtBytes(c.net_tx)}</td>` +
      `<td>${fmtBytes(c.blk_read)} / ${fmtBytes(c.blk_write)}</td>`;
    tb.appendChild(tr);
  }
}

async function loadNetwork() {
  const net = await fetch("/api/network").then(r => r.json());
  const nt = document.querySelector("#net-table tbody");
  nt.innerHTML = "";
  for (const i of (net.interfaces || [])) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(i.iface)}</td><td>${fmtBytes(i.rx_bps)}/s</td><td>${fmtBytes(i.tx_bps)}/s</td>`;
    nt.appendChild(tr);
  }
  const ct = document.querySelector("#conn-table tbody");
  ct.innerHTML = "";
  for (const c of (net.connections || []).slice(0, 100)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(c.proto)}</td><td>${esc(c.state)}</td>` +
      `<td>${esc(c.local)}</td><td>${esc(c.remote)}</td><td>${esc(c.process || "—")}</td>`;
    ct.appendChild(tr);
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
  await loadIncidents();
  await loadServices();
  await loadNetwork();
  await loadAccess();
  connectWs();
  setInterval(loadIncidents, 10000);
  setInterval(loadServices, 5000);
  setInterval(loadNetwork, 5000);
}

init();
