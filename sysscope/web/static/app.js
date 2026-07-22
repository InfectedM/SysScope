"use strict";

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
      (d.power_state === "active" ? "ativo" : d.power_state);
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="name">${d.disk}</div>
      <span class="state ${d.power_state}">${stateLabel}</span>
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
      <td>${r.disk}</td>
      <td>${r.detection}</td>
      <td class="culprit">${r.top_culprit || "…"}</td>`;
    tb.appendChild(tr);
  }
}

function connectWs() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
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
  connectWs();
  setInterval(loadIncidents, 10000);
}

init();
