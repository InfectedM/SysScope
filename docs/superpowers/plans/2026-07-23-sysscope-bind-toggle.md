# SysScope — Toggle de acesso localhost/LAN (Plano)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use `- [ ]` checkboxes.

**Goal:** Permitir escolher no dashboard se o servidor web escuta só em `localhost` ou em toda a rede interna (LAN), com reinício automático para aplicar.

**Architecture:** A escolha é persistida num ficheiro JSON escrito pelo servidor web (que corre como utilizador). No arranque, `main()` lê o modo e faz bind a `127.0.0.1` (localhost) ou `0.0.0.0` (LAN). Um endpoint `POST` grava a escolha e auto-sai; o systemd (`Restart=always`) reinicia com o novo bind. Sem autenticação (LAN de confiança).

**Tech Stack:** Reutiliza Python 3.13 / FastAPI / psutil (já dependência) do projeto.

## Global Constraints
- Python 3.13; comentários/UI em PT-PT.
- Servidor web corre como utilizador e abre a BD **read-only** — a definição NÃO vai para a BD; vai para `/var/lib/sysscope/web_settings.json` (pasta é do utilizador). Escrita atómica (temp + `os.replace`).
- `bind_mode` ∈ {"localhost","lan"}; localhost→host `127.0.0.1`, lan→host `0.0.0.0`. Porta inalterada (`cfg.web_port`, 8787).
- Ficheiro em falta/corrupto ⇒ default `localhost` (nunca crashar; nunca expor à LAN por acidente).
- Sem autenticação (decidido). Reinício automático via `Restart=always` + auto-saída do processo.
- Commits terminam com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; usar `git -c user.name="Leandro" -c user.email="leandrommferreira@gmail.com" commit ...`. Testes com `python3 -m pytest`.

---

### Task 1: Módulo de definições (`web/settings.py`)

**Files:** Create `sysscope/web/settings.py`, `tests/test_settings.py`

**Interfaces:**
- `DEFAULT_SETTINGS_PATH = "/var/lib/sysscope/web_settings.json"`
- `read_bind_mode(path: str) -> str` — "localhost"|"lan"; default "localhost" se ausente/inválido
- `write_bind_mode(path: str, mode: str) -> None` — valida mode (senão `ValueError`), escreve atomicamente
- `host_for_mode(mode: str) -> str` — "127.0.0.1" para localhost, "0.0.0.0" para lan
- `lan_ipv4_addresses() -> list[str]` — IPv4 não-loopback via `psutil.net_if_addrs()`

- [ ] **Step 1: Teste (falha)** — `tests/test_settings.py`:
```python
import json
import pytest
from sysscope.web import settings as s


def test_default_when_missing(tmp_path):
    assert s.read_bind_mode(str(tmp_path / "nope.json")) == "localhost"


def test_roundtrip(tmp_path):
    p = str(tmp_path / "w.json")
    s.write_bind_mode(p, "lan")
    assert s.read_bind_mode(p) == "lan"
    assert json.loads(open(p).read())["bind_mode"] == "lan"


def test_corrupt_file_defaults_localhost(tmp_path):
    p = tmp_path / "bad.json"; p.write_text("{lixo")
    assert s.read_bind_mode(str(p)) == "localhost"


def test_invalid_stored_value_defaults_localhost(tmp_path):
    p = tmp_path / "x.json"; p.write_text('{"bind_mode": "0.0.0.0"}')
    assert s.read_bind_mode(str(p)) == "localhost"


def test_write_rejects_invalid_mode(tmp_path):
    with pytest.raises(ValueError):
        s.write_bind_mode(str(tmp_path / "z.json"), "wan")


def test_host_for_mode():
    assert s.host_for_mode("localhost") == "127.0.0.1"
    assert s.host_for_mode("lan") == "0.0.0.0"
    assert s.host_for_mode("qualquer") == "127.0.0.1"  # fail-safe


def test_lan_addresses_is_list_without_loopback():
    addrs = s.lan_ipv4_addresses()
    assert isinstance(addrs, list)
    assert "127.0.0.1" not in addrs
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_settings.py -v`

- [ ] **Step 3: Implementar** `sysscope/web/settings.py`:
```python
"""Definições do servidor web persistidas (modo de bind localhost/LAN).

Guardado num ficheiro JSON que o servidor web (utilizador) pode escrever, já
que a BD é aberta em read-only. Fail-safe: qualquer problema ⇒ 'localhost'
(nunca expor à LAN por acidente).
"""
from __future__ import annotations

import json
import os
import socket

import psutil

DEFAULT_SETTINGS_PATH = "/var/lib/sysscope/web_settings.json"
_VALID = {"localhost", "lan"}


def read_bind_mode(path: str) -> str:
    try:
        with open(path) as f:
            mode = json.load(f).get("bind_mode")
    except (OSError, ValueError):
        return "localhost"
    return mode if mode in _VALID else "localhost"


def write_bind_mode(path: str, mode: str) -> None:
    if mode not in _VALID:
        raise ValueError(f"bind_mode inválido: {mode!r}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump({"bind_mode": mode}, f)
    os.replace(tmp, path)


def host_for_mode(mode: str) -> str:
    return "0.0.0.0" if mode == "lan" else "127.0.0.1"


def lan_ipv4_addresses() -> list[str]:
    out: list[str] = []
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.address != "127.0.0.1":
                    out.append(a.address)
    except Exception:
        return []
    return sorted(set(out))
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_settings.py -v`

- [ ] **Step 5: Commit** — `feat: módulo de definições de bind (localhost/LAN)`

---

### Task 2: Endpoints e arranque com bind configurável (`web/app.py`)

**Files:** Modify `sysscope/web/app.py`; Create `tests/test_web_settings.py`

**Interfaces:**
- `create_app(db, static_dir, settings_path=DEFAULT_SETTINGS_PATH, restart_fn=None)` — `restart_fn` injetável (default: agenda auto-saída); usado para tornar o POST testável.
- `GET /api/settings` → `{"bind_mode": str, "port": int, "lan_urls": [str]}` (lan_urls = `http://<ip>:<port>` para cada IPv4 LAN)
- `POST /api/settings/bind` body `{"bind_mode": "localhost"|"lan"}` → grava e chama `restart_fn()`; devolve `{"ok": true, "bind_mode": mode, "restarting": true}`; mode inválido → HTTP 400.
- `main()` lê o modo de `DEFAULT_SETTINGS_PATH` e faz `uvicorn.run(host=host_for_mode(mode), port=cfg.web_port)`.

- [ ] **Step 1: Teste (falha)** — `tests/test_web_settings.py`:
```python
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app
from sysscope.web import settings as s


def mk(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    calls = []
    app = create_app(ro, static_dir=str(tmp_path),
                     settings_path=str(tmp_path / "web_settings.json"),
                     restart_fn=lambda: calls.append(1))
    return TestClient(app), calls, str(tmp_path / "web_settings.json")


def test_get_settings_default(tmp_path):
    c, _, _ = mk(tmp_path)
    body = c.get("/api/settings").json()
    assert body["bind_mode"] == "localhost"
    assert body["port"] == 8787
    assert isinstance(body["lan_urls"], list)


def test_post_bind_lan_writes_and_restarts(tmp_path):
    c, calls, path = mk(tmp_path)
    r = c.post("/api/settings/bind", json={"bind_mode": "lan"})
    assert r.status_code == 200 and r.json()["bind_mode"] == "lan"
    assert calls == [1]                       # restart agendado
    assert s.read_bind_mode(path) == "lan"    # persistido


def test_post_bind_invalid_is_400(tmp_path):
    c, calls, _ = mk(tmp_path)
    r = c.post("/api/settings/bind", json={"bind_mode": "wan"})
    assert r.status_code == 400
    assert calls == []
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_web_settings.py -v`

- [ ] **Step 3: Implementar** — em `sysscope/web/app.py`:
  - No topo: `import os`, `import threading`, e `from sysscope.web.settings import (DEFAULT_SETTINGS_PATH, read_bind_mode, write_bind_mode, host_for_mode, lan_ipv4_addresses)` e `from fastapi import HTTPException`, `from pydantic import BaseModel`.
  - Alterar a assinatura para `def create_app(db, static_dir, settings_path: str = DEFAULT_SETTINGS_PATH, restart_fn=None):` e, no início do corpo:
```python
    def _default_restart() -> None:
        # Sai ~0.8s depois de responder; o systemd (Restart=always) reinicia
        # o serviço, que relê o bind_mode no arranque.
        threading.Timer(0.8, lambda: os._exit(0)).start()

    do_restart = restart_fn or _default_restart

    class _BindBody(BaseModel):
        bind_mode: str
```
  - Acrescentar os endpoints (antes do bloco de estáticos):
```python
    @app.get("/api/settings")
    def get_settings() -> dict:
        mode = read_bind_mode(settings_path)
        port = getattr(app.state, "web_port", 8787)
        urls = [f"http://{ip}:{port}" for ip in lan_ipv4_addresses()]
        return {"bind_mode": mode, "port": port, "lan_urls": urls}

    @app.post("/api/settings/bind")
    def set_bind(body: _BindBody) -> dict:
        try:
            write_bind_mode(settings_path, body.bind_mode)
        except ValueError:
            raise HTTPException(status_code=400, detail="bind_mode inválido")
        do_restart()
        return {"ok": True, "bind_mode": body.bind_mode, "restarting": True}
```
  - Guardar a porta para o `GET /api/settings`: em `main()`, após criar `app`, fazer `app.state.web_port = cfg.web_port` (e default 8787 no getattr acima cobre os testes).
  - Reescrever `main()`:
```python
def main() -> None:
    import uvicorn
    cfg = load_config("/etc/sysscope/sysscope.toml")
    db = Database(cfg.db_path, read_only=True)
    static_dir = str(Path(__file__).parent / "static")
    app = create_app(db, static_dir)
    app.state.web_port = cfg.web_port
    mode = read_bind_mode(DEFAULT_SETTINGS_PATH)
    uvicorn.run(app, host=host_for_mode(mode), port=cfg.web_port)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_web_settings.py tests/test_web.py -v`

- [ ] **Step 5: Commit** — `feat: endpoints de definições de acesso + bind configurável`

---

### Task 3: systemd (Restart=always), controlo no frontend, redeploy

**Files:** Modify `systemd/sysscope-web.service`, `sysscope/web/static/{index.html,app.js,style.css}`

- [ ] **Step 1: `systemd/sysscope-web.service`** — mudar `Restart=on-failure` para `Restart=always` (para o auto-reinício após o `os._exit(0)` funcionar).

- [ ] **Step 2: `index.html`** — no `<header>`, após o `<p class="sub">`, acrescentar o controlo de acesso:
```html
    <div id="access-control">
      <span class="access-label">Acesso:</span>
      <button data-mode="localhost" class="access-btn">Apenas localhost</button>
      <button data-mode="lan" class="access-btn">Rede interna (LAN)</button>
      <span id="access-url" class="access-url"></span>
    </div>
```

- [ ] **Step 3: `style.css`** — acrescentar:
```css
#access-control { margin-top: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.access-label { color: var(--muted); font-size: 13px; }
.access-btn { background: var(--panel); color: var(--muted); border: 1px solid var(--border);
  border-radius: 8px; padding: 5px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.access-btn.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.access-url { color: var(--accent-soft); font-size: 13px; }
```

- [ ] **Step 4: `app.js`** — acrescentar e chamar em `init()`:
```javascript
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
  if (mode === "localhost" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    if (!confirm("Vais desligar o acesso LAN. Esta página (aberta por IP) vai deixar de responder. Continuar?")) return;
  }
  await fetch("/api/settings/bind", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bind_mode: mode }),
  });
  document.getElementById("access-url").textContent = "a reiniciar…";
  setTimeout(() => location.reload(), 2500);
}
```
E em `init()`, acrescentar `await loadAccess();`.

- [ ] **Step 5: Smoke test + redeploy + verificação**

Run:
```bash
python3 -m pytest -q            # tudo passa
node --check sysscope/web/static/app.js
sudo cp systemd/sysscope-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo rsync -a --delete sysscope /opt/sysscope/
sudo systemctl restart sysscope-web
sleep 4
echo "modo atual:"; curl -s http://127.0.0.1:8787/api/settings
echo; echo "mudar para LAN:"; curl -s -X POST http://127.0.0.1:8787/api/settings/bind -H 'Content-Type: application/json' -d '{"bind_mode":"lan"}'
sleep 4   # aguarda auto-restart
echo; echo "escuta em 0.0.0.0?"; ss -ltnH 'sport = :8787'
echo "acesso por IP LAN:"; IP=$(python3 -c "import psutil,socket;print(next((a.address for x in psutil.net_if_addrs().values() for a in x if a.family==socket.AF_INET and a.address!='127.0.0.1'), ''))"); echo "http://$IP:8787"; curl -s "http://$IP:8787/api/settings" | head -c 80
echo; echo "voltar a localhost:"; curl -s -X POST http://127.0.0.1:8787/api/settings/bind -H 'Content-Type: application/json' -d '{"bind_mode":"localhost"}'; sleep 4
ss -ltnH 'sport = :8787'
systemctl is-active sysscope-web sysscope-collector
```
Expected: `/api/settings` mostra `localhost` primeiro; após POST lan + restart, `ss` mostra `0.0.0.0:8787` e o IP da LAN responde; após POST localhost + restart, `ss` mostra `127.0.0.1:8787`; ambos os serviços `active`. Confirmar que os HDDs continuam em standby (`curl /api/disks`), sem os acordar, e sem ler ficheiros dos mounts.

- [ ] **Step 6: Commit** — `feat: controlo de acesso localhost/LAN no dashboard + Restart=always`

---

## Self-Review
- Persistência user-writable (não na BD read-only): ✔ Task 1.
- Fail-safe para localhost em ficheiro ausente/corrupto/inválido: ✔ Task 1 (testado).
- Bind configurável no arranque + endpoints + restart injetável/testável: ✔ Task 2.
- Auto-reinício real via `Restart=always` + `os._exit`: ✔ Task 3.
- Frontend com toggle, URL da LAN e aviso LAN→localhost: ✔ Task 3.
- Sem autenticação (decidido); nunca acorda discos (só psutil/rede/procfs, nada nos mounts): ✔.
- Type consistency: `read_bind_mode/write_bind_mode/host_for_mode/lan_ipv4_addresses`, `create_app(..., settings_path, restart_fn)` consistentes entre tasks. ✔
