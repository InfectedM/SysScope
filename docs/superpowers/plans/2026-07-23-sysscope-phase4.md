# SysScope Fase 4 — Plano (detalhe de incidente, padrões, gráficos, limpeza)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** (2) Drill-down de incidentes (ver ficheiros/processos capturados). (3) Painel de padrões/reincidentes (agregação por disco+culpado). (4) Gráficos de throughput por disco (uPlot). (6) Remover código morto.

**Architecture:** Sem mudanças no coletor. Toda a agregação de padrões é feita por query read-only no servidor web. O frontend ganha: um modal de detalhe de incidente (consome `/api/incidents/{id}`), um bloco de padrões (novo `/api/incidents/summary`), e gráficos de linha com o uPlot já vendorizado (consomem `/api/disks/{disco}/samples`).

**Tech Stack:** Python 3.13, FastAPI, SQLite (read-only na web), uPlot (vendorizado), Outfit/JetBrains Mono, tema dark OLED já existente.

## Global Constraints
- Python 3.13; comentários/UI em PT-PT. Nunca acordar discos (nada de novo toca nos mounts).
- Frontend vanilla, sem build step; escapar strings server-derived com `esc()`; respeitar o visual dark OLED atual (violeta #8b5cf6, Outfit + JetBrains Mono, ícones SVG, `prefers-reduced-motion`).
- Manter os ids/hooks que o JS já usa (`disk-cards`, `services-summary`, `system-body`, `wakeups-body`, `access-url`, `.access-btn`, `#incident-table tbody`, `#containers-table tbody`, `#net-table tbody`, `#conn-table tbody`, `#proc-table tbody`, `#timers-table tbody`).
- Commits terminam com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; usar `git -c user.name="Leandro" -c user.email="leandrommferreira@gmail.com" commit ...`. Testes: `python3 -m pytest`.
- Deploy: `sudo rsync -a --delete sysscope /opt/sysscope/ && sudo systemctl restart sysscope-collector sysscope-web`.

---

### Task 1: Limpeza de código morto (ponto 6)

**Files:** Delete `sysscope/collector/power.py`, `tests/test_power.py`, `sysscope/collector/fatrace.py`, `tests/test_fatrace.py`; Modify `sysscope/web/static/app.js`

Confirmado (via grep) que `PowerReader`/`power.py` e todas as funções de `fatrace.py` (`event_disk`, `parse_fatrace_line`, `FatraceEvent`, `op_from_types`) NÃO são usadas fora dos próprios módulos e testes — a deteção passou a activity-based e o `fdscan` passou a device-based.

- [ ] **Step 1: Confirmar que nada importa os módulos a remover**

Run:
```bash
grep -rn "collector.power\|collector.fatrace\|PowerReader\|parse_fatrace_line\|FatraceEvent\|op_from_types\|event_disk" sysscope/ | grep -v -E "sysscope/collector/(power|fatrace).py"
```
Expected: sem resultados (ou só linhas dentro dos ficheiros a apagar). Se aparecer uso real noutro sítio, PARAR e reportar.

- [ ] **Step 2: Apagar os módulos mortos e os seus testes**

Run:
```bash
git rm sysscope/collector/power.py tests/test_power.py sysscope/collector/fatrace.py tests/test_fatrace.py
```

- [ ] **Step 3: Corrigir ramos mortos no `app.js`**

Em `sysscope/web/static/app.js`, na lógica de estado do disco (`renderDisks`), o coletor só emite `"active"` ou `"standby"` agora. Substituir a lógica que referencia `"sleeping"`/`"unknown"` por uma limpa:
```javascript
  const isActive = d.power_state === "active";
  const stateLabel = isActive ? "ativo" : "adormecido";
  const stateClass = isActive ? "active" : "standby";
```
e usar `stateClass`/`stateLabel` no markup do cartão (mantendo o resto do visual). Não referenciar mais `"sleeping"`/`"unknown"`.

- [ ] **Step 4: Correr a suite completa**

Run: `python3 -m pytest -q`
Expected: passa (menos os testes removidos; sem falhas de import). `node --check sysscope/web/static/app.js` limpo.

- [ ] **Step 5: Commit** — `chore: remove código morto (hdparm/power, fatrace) e ramos obsoletos no app.js`

---

### Task 2: Backend de padrões (ponto 3)

**Files:** Modify `sysscope/storage/db.py`, `sysscope/web/app.py`; Create `tests/test_incident_summary.py`

**Interfaces:**
- `culprit_name(top_culprit: str | None) -> str` (helper em `db.py`): extrai o nome antes de " (" — ex.: `"bazarr (8 acessos)"` → `"bazarr"`; `None`/`""` → `"desconhecido"`.
- `Database.incident_summary(self, since: float) -> list[dict]`: incidentes com `ts >= since`, agrupados por disco → `[{disk, count, culprits: [{name, count}] ordenado desc}]`, discos ordenados por count desc.
- `GET /api/incidents/summary?hours=24` → chama `incident_summary(now - hours*3600)`.

- [ ] **Step 1: Teste (falha)** — `tests/test_incident_summary.py`:
```python
from sysscope.storage.db import Database, culprit_name


def test_culprit_name():
    assert culprit_name("bazarr (8 acessos)") == "bazarr"
    assert culprit_name("jellyfin (1 acesso)") == "jellyfin"
    assert culprit_name("desconhecido") == "desconhecido"
    assert culprit_name(None) == "desconhecido"
    assert culprit_name("") == "desconhecido"


def test_incident_summary(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    def inc(ts, disk, culprit):
        i = db.create_incident(ts, disk, "atividade")
        db.set_incident_culprit(i, culprit)
    inc(100, "sdc", "bazarr (8 acessos)")
    inc(200, "sdc", "bazarr (2 acessos)")
    inc(300, "sdc", "jellyfin (1 acesso)")
    inc(400, "sde", "jellyfin (5 acessos)")
    inc(50,  "sde", "bazarr (1 acesso)")   # antes do 'since'
    s = db.incident_summary(since=99)
    by_disk = {d["disk"]: d for d in s}
    assert by_disk["sdc"]["count"] == 3
    assert by_disk["sdc"]["culprits"][0] == {"name": "bazarr", "count": 2}
    assert by_disk["sde"]["count"] == 1              # o de ts=50 foi excluído
    assert s[0]["disk"] == "sdc"                     # ordenado por count desc
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_incident_summary.py -v`

- [ ] **Step 3: Implementar** — em `sysscope/storage/db.py` (nível de módulo, junto ao topo após imports):
```python
def culprit_name(top_culprit: str | None) -> str:
    """Extrai o nome do culpado (antes de ' ('); vazio/None -> 'desconhecido'."""
    if not top_culprit:
        return "desconhecido"
    return top_culprit.split(" (")[0]
```
E como método de `Database`:
```python
    def incident_summary(self, since: float) -> list[dict]:
        rows = self._conn.execute(
            "SELECT disk, top_culprit FROM incidents WHERE ts>=?", (since,)
        ).fetchall()
        from collections import Counter
        per_disk: dict[str, Counter] = {}
        for r in rows:
            per_disk.setdefault(r["disk"], Counter())[culprit_name(r["top_culprit"])] += 1
        out = []
        for disk, counter in per_disk.items():
            culprits = [{"name": n, "count": c}
                        for n, c in counter.most_common()]
            out.append({"disk": disk, "count": sum(counter.values()),
                        "culprits": culprits})
        out.sort(key=lambda d: -d["count"])
        return out
```
Em `sysscope/web/app.py` (junto dos endpoints de incidentes), importando `time` no topo se necessário:
```python
    @app.get("/api/incidents/summary")
    def incidents_summary(hours: float = 24.0) -> list:
        import time
        return db.incident_summary(time.time() - hours * 3600)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_incident_summary.py tests/test_db.py tests/test_web.py -v`

- [ ] **Step 5: Commit** — `feat: agregação de padrões de spin-up (por disco e culpado)`

---

### Task 3: Frontend — detalhe de incidente (ponto 2) + padrões (ponto 3)

**Files:** Modify `sysscope/web/static/{index.html,style.css,app.js}`

**Detalhe (ponto 2):** tornar as linhas da tabela de Incidentes clicáveis; ao clicar, abrir um **modal** que faz `fetch("/api/incidents/" + id)` e mostra a lista de `events` (`ts`, `container`/`comm`, `op`, `path`) numa tabela, além do resumo do incidente. Fechar com botão × / clique no fundo / tecla Esc. `cursor:pointer` nas linhas; `aria`-adequado; escapar todas as strings.

**Padrões (ponto 3):** um bloco no topo do painel de Incidentes com o resumo de `/api/incidents/summary?hours=24` — por disco: `sdc — 12× · bazarr (8), jellyfin (4)`, com o nome do disco/mount e chips dos culpados. Atualiza a cada ~15s.

- [ ] **Step 1: `index.html`** — dentro da `<section id="incidents">`, antes da tabela, acrescentar `<div id="incident-patterns" class="io"></div>`. No fim do `<body>` (antes dos `<script>`), acrescentar o container do modal:
```html
    <div id="incident-modal" class="modal-overlay" hidden>
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head">
          <h3 id="modal-title">Detalhe do incidente</h3>
          <button id="modal-close" class="icon-btn" aria-label="Fechar">&times;</button>
        </div>
        <div id="modal-body"></div>
      </div>
    </div>
```

- [ ] **Step 2: `style.css`** — acrescentar (consistente com o tema dark):
```css
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6);
  backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center;
  z-index: 50; padding: 24px; }
.modal-overlay[hidden] { display: none; }
.modal { background: var(--surface); border: 1px solid var(--border-strong);
  border-radius: 16px; max-width: 760px; width: 100%; max-height: 80vh; overflow: auto;
  padding: 20px 24px; box-shadow: 0 20px 60px rgba(0,0,0,.5); }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.icon-btn { background: none; border: none; color: var(--muted); font-size: 22px;
  cursor: pointer; line-height: 1; padding: 4px 8px; border-radius: 8px; }
.icon-btn:hover { color: var(--text); background: var(--surface-2); }
#incident-table tbody tr { cursor: pointer; }
.pattern-row { margin: 4px 0; }
.pattern-row .disk { color: var(--accent-soft); font-weight: 600; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
  background: rgba(139,92,246,.15); color: var(--accent-soft); margin: 0 4px 2px 0; }
```
(Se o tema já definir `--surface`/`--border-strong`/`--surface-2`, reutilizar; senão usar os equivalentes existentes.)

- [ ] **Step 3: `app.js`** — 
(a) em `loadIncidents`, dar às linhas `data-id` e `onclick` para abrir o modal:
```javascript
tr.dataset.id = r.id;
tr.onclick = () => openIncident(r.id);
```
(b) acrescentar as funções:
```javascript
async function openIncident(id) {
  const modal = document.getElementById("incident-modal");
  const body = document.getElementById("modal-body");
  body.innerHTML = "a carregar…";
  modal.hidden = false;
  const data = await fetch("/api/incidents/" + id).then(r => r.json());
  const inc = data.incident || {};
  const evs = data.events || [];
  let html = `<div class="io">${esc(inc.disk || "")} · ${esc(inc.detection || "")} · ${fmtTime(inc.ts)} · culpado: <b>${esc(inc.top_culprit || "—")}</b></div>`;
  if (!evs.length) {
    html += `<p class="io">Sem acessos capturados nesta janela.</p>`;
  } else {
    html += `<table><thead><tr><th>Quando</th><th>Processo</th><th>Op</th><th>Ficheiro</th></tr></thead><tbody>` +
      evs.map(e => `<tr><td>${fmtTime(e.ts)}</td><td>${esc(e.container || e.comm)}</td><td>${esc(e.op)}</td><td title="${esc(e.path)}">${esc(e.path)}</td></tr>`).join("") +
      `</tbody></table>`;
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
```
(c) ligar o fecho do modal e o poll dos padrões, em `init()`:
```javascript
  document.getElementById("modal-close").onclick = closeIncident;
  document.getElementById("incident-modal").onclick = (e) => {
    if (e.target.id === "incident-modal") closeIncident();
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeIncident(); });
  await loadPatterns();
  setInterval(loadPatterns, 15000);
```
Garantir que `fmtTime` já existe (é usado em `loadIncidents`); reutilizar.

- [ ] **Step 4: Verificar** — `node --check sysscope/web/static/app.js`; `python3 -m pytest -q` (sem regressão).

- [ ] **Step 5: Commit** — `feat: modal de detalhe de incidente + bloco de padrões (24h)`

---

### Task 4: Gráficos de throughput por disco (uPlot) (ponto 4)

**Files:** Modify `sysscope/web/static/{index.html,style.css,app.js}`

**Nota:** antes de escrever o código do gráfico, invocar a skill `dataviz` para calibrar cores/eixos/altura (paleta consistente com o tema violeta/dark). O uPlot já está vendorizado (`uplot.iife.min.js`, `uplot.min.css`, incluídos no `index.html`).

Objetivo: por cada disco, um mini-gráfico de linha do throughput de leitura ao longo do tempo (últimos ~10 min), consumindo `GET /api/disks/{disco}/samples?since=<epoch>`. Colocar o gráfico dentro do cartão do disco (ou numa faixa por baixo dos cartões). Atualizar a cada 5s.

- [ ] **Step 1: `index.html`** — garantir que os `<link>`/`<script>` do uPlot estão presentes (já estavam na Fase 1). Nada a acrescentar se já lá estão.

- [ ] **Step 2: `app.js`** — acrescentar uma função que, para cada disco, busca as amostras e desenha/atualiza um uPlot dentro de um contentor no cartão. Esboço (ajustar à estrutura real do cartão gerada em `renderDisks`; guardar as instâncias uPlot num mapa para dar `setData` em vez de recriar):
```javascript
const charts = {};   // disk -> uPlot

async function loadDiskCharts() {
  const since = Date.now() / 1000 - 600;   // 10 min
  for (const d of lastDisks) {
    const el = document.getElementById("chart-" + d.disk);
    if (!el) continue;
    const rows = await fetch(`/api/disks/${d.disk}/samples?since=${since}`).then(r => r.json());
    const xs = rows.map(r => r.ts);
    const rd = rows.map(r => r.read_bps);
    const wr = rows.map(r => r.write_bps);
    const data = [xs, rd, wr];
    if (charts[d.disk]) { charts[d.disk].setData(data); continue; }
    charts[d.disk] = new uPlot({
      width: el.clientWidth || 240, height: 70,
      cursor: { show: false }, legend: { show: false },
      scales: { x: { time: true } },
      axes: [ { show: false }, { show: false } ],
      series: [
        {},
        { stroke: "#a78bfa", width: 1.5, fill: "rgba(139,92,246,.15)" },
        { stroke: "#34d399", width: 1 },
      ],
    }, data, el);
  }
}
```
Em `renderDisks`, incluir no markup do cartão um contentor `<div class="chart" id="chart-${d.disk}"></div>` (com altura fixa via CSS). Em `init()`: `await loadDiskCharts(); setInterval(loadDiskCharts, 5000);` (depois de `loadDiskInfo`). Nota: recriar cartões via `renderDisks` (WebSocket 2s) destrói os contentores — nesse caso limpar `charts` ou reidratar; abordagem simples: em `renderDisks`, se o cartão já existe manter o `<div class="chart">` (ou apagar `charts[disk]` quando o contentor é recriado para forçar recriação). Implementar de forma robusta a este ciclo.

- [ ] **Step 3: `style.css`** — `.card .chart { height: 70px; margin-top: 10px; }` e garantir que o uPlot herda cores legíveis no tema dark (fundo transparente).

- [ ] **Step 4: Verificar** — `node --check`; `python3 -m pytest -q`; e, após deploy, confirmar no browser (ou via curl) que `/api/disks/sde/samples?since=...` devolve pontos e o gráfico não parte a página.

- [ ] **Step 5: Commit** — `feat: mini-gráficos de throughput por disco (uPlot)`

---

### Task 5: Redeploy final + verificação + merge

- [ ] **Step 1: Suite + node** — `python3 -m pytest -q`; `node --check sysscope/web/static/app.js`.
- [ ] **Step 2: Redeploy** — `sudo rsync -a --delete sysscope /opt/sysscope/`; `sudo systemctl restart sysscope-collector sysscope-web`; `sleep 8`.
- [ ] **Step 3: Verificar ao vivo**
```bash
ls -d /opt/sysscope/sysscope/sysscope 2>/dev/null && echo "!!ANINHADO" || echo "sem aninhamento"
systemctl is-active sysscope-collector sysscope-web
for ep in "incidents/summary?hours=24" "disks/sde/samples?since=0"; do echo -n "/api/$ep: "; curl -s "http://127.0.0.1:8787/api/$ep" | head -c 120; echo; done
curl -s http://127.0.0.1:8787/api/disks | python3 -c "import sys,json;print([(x['disk'],x['power_state']) for x in json.load(sys.stdin)])"
```
Esperado: sem aninhamento; ambos ativos; endpoints devolvem JSON; HDDs standby/active (não acordados por nós).
- [ ] **Step 4: Merge + push** — merge da branch `fase4` para `master`, `git push origin master`.

---

## Self-Review
- Ponto 2 (detalhe): Task 3 (modal consome /api/incidents/{id}). ✔
- Ponto 3 (padrões): Tasks 2 (backend) + 3 (frontend). ✔
- Ponto 4 (gráficos): Task 4 (uPlot, com dataviz). ✔
- Ponto 6 (limpeza): Task 1 (remove power.py/fatrace.py + testes + ramos mortos). ✔
- Nunca acordar discos: nada novo toca nos mounts; agregação é read-only. ✔
- Sem mudanças no coletor; web read-only. Visual dark OLED preservado.
- Type consistency: `culprit_name`, `incident_summary`, endpoints `/api/incidents/summary`, ids de modal/gráfico. ✔
