# SysScope Fase 2 — Plano de Implementação (Serviços + Rede)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acrescentar ao dashboard os painéis **Serviços** (units systemd + containers Docker com BlockIO/NetIO/CPU/mem por container) e **Rede** (throughput por interface + ligações ativas com processo), alimentados por novos coletores.

**Architecture:** O coletor (root) ganha uma cadência secundária mais lenta (~5s) que recolhe `docker stats`, `systemctl list-units -o json`, `/proc/net/dev` e `ss -tunp`, escrevendo *snapshots* JSON (estado atual) e amostras de throughput de rede na mesma BD SQLite. O servidor web ganha endpoints REST novos; o frontend ganha duas secções que fazem *poll* a cada 5s.

**Tech Stack:** Reutiliza tudo da Fase 1 (Python 3.13, FastAPI, SQLite WAL, uPlot já vendorizado). Ferramentas de sistema já presentes: `docker`, `systemctl`, `ss` (iproute2). Sem `bpftrace` (decidido saltar — em FUSE atribuiria ao `ntfs-3g`).

## Global Constraints

- **Python 3.13**; comentários/strings de UI em Português (PT-PT).
- **Nunca acordar os discos:** os novos coletores usam apenas `docker stats`, `systemctl`, `/proc/net/dev`, `ss` e `/proc` — nenhum acede aos mounts dos HDD (`/media/HDD3TB`, `/media/HDD4TB`, `/mnt/HDD2TB`, `/media/HDD8TB`).
- **Degradar com robustez:** se `docker`, `systemctl` ou `ss` falharem/estiverem ausentes, o painel respetivo fica vazio com aviso; o coletor não pode crashar. Reutilizar o wrapper `run_cmd`/`Runner` (Fase 1) — falhas devolvem estado vazio, não exceção.
- **Cadência separada:** a recolha de serviços/rede corre a cada `services_interval` (default 5.0s), independente do `sample_interval` dos discos (2.0s). `docker stats --no-stream` pode demorar ~1-2s — corre na cadência lenta, com timeout.
- **BD:** mesma `/var/lib/sysscope/sysscope.db` (WAL). Coletor escreve; web lê read-only.
- **Commits:** `feat:`/`test:`, terminar com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; usar `git -c user.name="Leandro" -c user.email="leandrommferreira@gmail.com" commit ...`.
- **Deploy:** mesmos serviços systemd; redeploy por `sudo rsync -a --delete sysscope /opt/sysscope/ && sudo systemctl restart sysscope-collector sysscope-web`.

---

## Estrutura de ficheiros (Fase 2)

```
sysscope/
  common/
    config.py             # + services_interval; + net_ifaces (opcional)
    sizes.py              # NOVO: parse_size (human -> bytes)
  storage/
    db.py                 # + net_samples, snapshots (tabelas + métodos)
  collector/
    netdev.py             # NOVO: parse /proc/net/dev + taxas
    docker_stats.py       # NOVO: parse `docker stats`
    systemd_units.py      # NOVO: parse `systemctl list-units -o json`
    connections.py        # NOVO: parse `ss -tunpH`
    services_collector.py # NOVO: cadência lenta -> snapshots + net_samples
    main.py               # + integrar o services_collector
  web/
    app.py                # + /api/services /api/containers /api/network[/samples]
    static/
      index.html          # + secções Serviços e Rede
      app.js              # + render de serviços/rede (poll 5s) + chart de rede
      style.css           # + estilos das novas secções
  tests/
    test_sizes.py
    test_netdev.py
    test_docker_stats.py
    test_systemd_units.py
    test_connections.py
    test_db_phase2.py
    test_web_phase2.py
```

---

### Task 1: Parser de tamanhos humanos (`sizes.py`)

**Files:** Create `sysscope/common/sizes.py`, `tests/test_sizes.py`

**Interfaces:**
- Produces: `parse_size(text: str) -> float` (bytes; aceita "308.9MiB", "1.08GB", "742MB", "126B", "0B", "1.66GB"; devolve `0.0` para "0", "" ou não-parseável)

- [ ] **Step 1: Teste (falha)** — `tests/test_sizes.py`:
```python
from sysscope.common.sizes import parse_size


def test_iec_and_si():
    assert parse_size("1KiB") == 1024
    assert parse_size("1MiB") == 1024 ** 2
    assert parse_size("1GiB") == 1024 ** 3
    assert parse_size("1kB") == 1000
    assert parse_size("1MB") == 1_000_000
    assert parse_size("1GB") == 1_000_000_000


def test_decimals_and_bytes():
    assert parse_size("308.9MiB") == round(308.9 * 1024 ** 2, 6)
    assert parse_size("126B") == 126
    assert parse_size("0B") == 0.0


def test_garbage_is_zero():
    assert parse_size("") == 0.0
    assert parse_size("--") == 0.0
    assert parse_size("N/A") == 0.0
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_sizes.py -v` → ModuleNotFoundError

- [ ] **Step 3: Implementar** `sysscope/common/sizes.py`:
```python
"""Conversão de tamanhos legíveis (ex.: '308.9MiB') para bytes."""
from __future__ import annotations

import re

# Ordem importa: sufixos IEC (…iB) antes dos SI para o regex apanhar o mais longo.
_UNITS = {
    "b": 1,
    "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4, "pb": 1000 ** 5,
    "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4, "pib": 1024 ** 5,
}
_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]+)?\s*$")


def parse_size(text: str) -> float:
    m = _RE.match(text or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    factor = _UNITS.get(unit)
    if factor is None:
        return 0.0
    return value * factor
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_sizes.py -v` → PASS

- [ ] **Step 5: Commit** — `feat: parser de tamanhos humanos (sizes.py)`

---

### Task 2: Tabelas e métodos de BD da Fase 2

**Files:** Modify `sysscope/storage/db.py`; Create `tests/test_db_phase2.py`

**Interfaces (adicionar a `Database`):**
- `insert_net_sample(self, ts: float, iface: str, rx_bps: float, tx_bps: float) -> None`
- `latest_net_status(self) -> list[dict]` (última amostra por interface)
- `recent_net_samples(self, iface: str, since: float) -> list[dict]`
- `put_snapshot(self, kind: str, ts: float, payload: str) -> None` (upsert por `kind`)
- `get_snapshot(self, kind: str) -> dict | None` (`{ts, payload}` ou None)
- Estender `purge_older_than` para limpar `net_samples`.

- [ ] **Step 1: Teste (falha)** — `tests/test_db_phase2.py`:
```python
from sysscope.storage.db import Database


def mk(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema(); return db


def test_net_samples_latest_and_recent(tmp_path):
    db = mk(tmp_path)
    db.insert_net_sample(10.0, "eno1", 100, 200)
    db.insert_net_sample(20.0, "eno1", 300, 400)
    latest = db.latest_net_status()
    e = next(r for r in latest if r["iface"] == "eno1")
    assert e["rx_bps"] == 300 and e["tx_bps"] == 400
    assert len(db.recent_net_samples("eno1", since=15.0)) == 1


def test_snapshot_upsert(tmp_path):
    db = mk(tmp_path)
    db.put_snapshot("services", 1.0, '{"a":1}')
    db.put_snapshot("services", 2.0, '{"a":2}')
    snap = db.get_snapshot("services")
    assert snap["ts"] == 2.0 and snap["payload"] == '{"a":2}'
    assert db.get_snapshot("inexistente") is None


def test_purge_covers_net_samples(tmp_path):
    db = mk(tmp_path)
    db.insert_net_sample(10.0, "eno1", 1, 1)
    db.insert_net_sample(1000.0, "eno1", 1, 1)
    db.purge_older_than(500.0)
    assert len(db.recent_net_samples("eno1", 0.0)) == 1
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_db_phase2.py -v`

- [ ] **Step 3: Implementar** — no `_SCHEMA` de `sysscope/storage/db.py`, acrescentar:
```sql
CREATE TABLE IF NOT EXISTS net_samples (
    ts REAL NOT NULL,
    iface TEXT NOT NULL,
    rx_bps REAL NOT NULL,
    tx_bps REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_net_iface_ts ON net_samples(iface, ts);

CREATE TABLE IF NOT EXISTS snapshots (
    kind TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    payload TEXT NOT NULL
);
```
E adicionar os métodos à classe `Database` (a seguir aos existentes):
```python
    def insert_net_sample(self, ts, iface, rx_bps, tx_bps) -> None:
        self._conn.execute(
            "INSERT INTO net_samples VALUES (?,?,?,?)", (ts, iface, rx_bps, tx_bps))
        self._conn.commit()

    def latest_net_status(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT s.* FROM net_samples s
               JOIN (SELECT iface, MAX(ts) mts FROM net_samples GROUP BY iface) m
               ON s.iface=m.iface AND s.ts=m.mts""").fetchall()
        return [dict(r) for r in rows]

    def recent_net_samples(self, iface, since) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM net_samples WHERE iface=? AND ts>? ORDER BY ts",
            (iface, since)).fetchall()
        return [dict(r) for r in rows]

    def put_snapshot(self, kind, ts, payload) -> None:
        self._conn.execute(
            "INSERT INTO snapshots (kind, ts, payload) VALUES (?,?,?) "
            "ON CONFLICT(kind) DO UPDATE SET ts=excluded.ts, payload=excluded.payload",
            (kind, ts, payload))
        self._conn.commit()

    def get_snapshot(self, kind) -> dict | None:
        r = self._conn.execute(
            "SELECT ts, payload FROM snapshots WHERE kind=?", (kind,)).fetchone()
        return dict(r) if r else None
```
E em `purge_older_than`, acrescentar antes do `commit`:
```python
        self._conn.execute("DELETE FROM net_samples WHERE ts<?", (cutoff_ts,))
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_db_phase2.py tests/test_db.py -v`

- [ ] **Step 5: Commit** — `feat: BD da Fase 2 (net_samples + snapshots)`

---

### Task 3: Parser de `/proc/net/dev` e taxas (`netdev.py`)

**Files:** Create `sysscope/collector/netdev.py`, `tests/test_netdev.py`

**Interfaces:**
- `NetStat(rx_bytes: int, tx_bytes: int)` — frozen dataclass
- `parse_net_dev(text: str, skip_loopback: bool = True) -> dict[str, NetStat]`
- `net_rates(prev: NetStat, curr: NetStat, dt: float) -> tuple[float, float]` (rx_bps, tx_bps; seguro com dt<=0 → (0,0))

- [ ] **Step 1: Teste (falha)** — `tests/test_netdev.py`:
```python
from sysscope.collector.netdev import NetStat, parse_net_dev, net_rates

SAMPLE = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
    "    lo:  12345      10    0    0    0     0          0         0    12345      10    0    0    0     0       0          0\n"
    "  eno1: 1000000    500    0    0    0     0          0         0  2000000     600    0    0    0     0       0          0\n"
)


def test_parse_skips_loopback_by_default():
    d = parse_net_dev(SAMPLE)
    assert "lo" not in d
    assert d["eno1"] == NetStat(rx_bytes=1000000, tx_bytes=2000000)


def test_parse_can_include_loopback():
    d = parse_net_dev(SAMPLE, skip_loopback=False)
    assert d["lo"].rx_bytes == 12345


def test_net_rates():
    prev = NetStat(1000, 2000); curr = NetStat(3000, 6000)
    rx, tx = net_rates(prev, curr, dt=2.0)
    assert rx == 1000.0 and tx == 2000.0


def test_net_rates_zero_dt():
    assert net_rates(NetStat(1, 1), NetStat(2, 2), 0.0) == (0.0, 0.0)
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_netdev.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/netdev.py`:
```python
"""Parsing de /proc/net/dev e cálculo de throughput por interface.

Formato por linha: `iface: rx_bytes rx_packets ... (8 campos) tx_bytes ...`
Campo 0 (após ':') = rx_bytes; campo 8 = tx_bytes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetStat:
    rx_bytes: int
    tx_bytes: int


def parse_net_dev(text: str, skip_loopback: bool = True) -> dict[str, NetStat]:
    out: dict[str, NetStat] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if skip_loopback and name == "lo":
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            out[name] = NetStat(rx_bytes=int(parts[0]), tx_bytes=int(parts[8]))
        except ValueError:
            continue
    return out


def net_rates(prev: NetStat, curr: NetStat, dt: float) -> tuple[float, float]:
    if dt <= 0:
        return (0.0, 0.0)
    return ((curr.rx_bytes - prev.rx_bytes) / dt,
            (curr.tx_bytes - prev.tx_bytes) / dt)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_netdev.py -v`

- [ ] **Step 5: Commit** — `feat: parser de /proc/net/dev + throughput`

---

### Task 4: Parser de `docker stats` (`docker_stats.py`)

**Files:** Create `sysscope/collector/docker_stats.py`, `tests/test_docker_stats.py`

**Interfaces:**
- `ContainerStat(name: str, cpu_pct: float, mem_used: float, mem_limit: float, net_rx: float, net_tx: float, blk_read: float, blk_write: float)` — frozen dataclass
- `parse_docker_stats(text: str) -> list[ContainerStat]` (uma linha por container, formato `Name|CPU%|Mem|Net|Blk`)
- `read_container_stats(runner: Runner = run_cmd) -> list[ContainerStat]` (corre `docker stats --no-stream`; `[]` em falha)

- [ ] **Step 1: Teste (falha)** — `tests/test_docker_stats.py`:
```python
from sysscope.collector.docker_stats import (
    ContainerStat, parse_docker_stats, read_container_stats,
)

SAMPLE = (
    "radarr|0.11%|202.1MiB / 19.21GiB|182MB / 99.3MB|742MB / 1.08GB\n"
    "bazarr|0.20%|308.9MiB / 19.21GiB|133MB / 14.5MB|839MB / 318MB\n"
)


def test_parse_basic():
    stats = parse_docker_stats(SAMPLE)
    assert len(stats) == 2
    r = stats[0]
    assert r.name == "radarr"
    assert r.cpu_pct == 0.11
    assert r.mem_used == round(202.1 * 1024 ** 2, 6)
    assert r.blk_read == 742 * 1000 ** 2
    assert r.blk_write == 1.08 * 1000 ** 3


def test_parse_ignores_malformed_lines():
    assert parse_docker_stats("linha-má\n\n") == []


def test_read_returns_empty_on_failure():
    def boom(argv):
        raise RuntimeError("docker em falta")
    assert read_container_stats(runner=boom) == []
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_docker_stats.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/docker_stats.py`:
```python
"""Parsing de `docker stats --no-stream` por container."""
from __future__ import annotations

from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd
from sysscope.common.sizes import parse_size

_FORMAT = "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}"


@dataclass(frozen=True)
class ContainerStat:
    name: str
    cpu_pct: float
    mem_used: float
    mem_limit: float
    net_rx: float
    net_tx: float
    blk_read: float
    blk_write: float


def _pair(text: str) -> tuple[float, float]:
    left, _, right = text.partition("/")
    return parse_size(left.strip()), parse_size(right.strip())


def parse_docker_stats(text: str) -> list[ContainerStat]:
    out: list[ContainerStat] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        name, cpu, mem, net, blk = parts
        try:
            cpu_pct = float(cpu.strip().rstrip("%"))
        except ValueError:
            continue
        mem_used, mem_limit = _pair(mem)
        net_rx, net_tx = _pair(net)
        blk_read, blk_write = _pair(blk)
        out.append(ContainerStat(name.strip(), cpu_pct, mem_used, mem_limit,
                                 net_rx, net_tx, blk_read, blk_write))
    return out


def read_container_stats(runner: Runner = run_cmd) -> list[ContainerStat]:
    try:
        out = runner(["docker", "stats", "--no-stream", "--format", _FORMAT])
    except Exception:
        return []
    return parse_docker_stats(out)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_docker_stats.py -v`

- [ ] **Step 5: Commit** — `feat: parser de docker stats (BlockIO por container)`

---

### Task 5: Parser de units systemd (`systemd_units.py`)

**Files:** Create `sysscope/collector/systemd_units.py`, `tests/test_systemd_units.py`

**Interfaces:**
- `Unit(name: str, active: str, sub: str, description: str)` — frozen dataclass
- `parse_units(json_text: str) -> list[Unit]`
- `summarize(units: list[Unit]) -> dict` (`{"total": n, "active": n, "failed": [nomes], "counts": {estado: n}}`)
- `read_units(runner: Runner = run_cmd) -> list[Unit]` (`systemctl list-units --type=service --all -o json --no-pager`; `[]` em falha)

- [ ] **Step 1: Teste (falha)** — `tests/test_systemd_units.py`:
```python
import json
from sysscope.collector.systemd_units import (
    Unit, parse_units, summarize, read_units,
)

SAMPLE = json.dumps([
    {"unit": "a.service", "active": "active", "sub": "running", "description": "A"},
    {"unit": "b.service", "active": "failed", "sub": "failed", "description": "B"},
    {"unit": "c.service", "active": "inactive", "sub": "dead", "description": "C"},
])


def test_parse():
    units = parse_units(SAMPLE)
    assert len(units) == 3
    assert units[0] == Unit("a.service", "active", "running", "A")


def test_summarize():
    s = summarize(parse_units(SAMPLE))
    assert s["total"] == 3
    assert s["active"] == 1
    assert s["failed"] == ["b.service"]
    assert s["counts"]["inactive"] == 1


def test_parse_bad_json():
    assert parse_units("não é json") == []


def test_read_empty_on_failure():
    def boom(argv):
        raise RuntimeError("systemctl em falta")
    assert read_units(runner=boom) == []
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_systemd_units.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/systemd_units.py`:
```python
"""Parsing de `systemctl list-units --type=service --all -o json`."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd


@dataclass(frozen=True)
class Unit:
    name: str
    active: str
    sub: str
    description: str


def parse_units(json_text: str) -> list[Unit]:
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[Unit] = []
    for u in data:
        try:
            out.append(Unit(u["unit"], u["active"], u["sub"], u.get("description", "")))
        except (KeyError, TypeError):
            continue
    return out


def summarize(units: list[Unit]) -> dict:
    counts = Counter(u.active for u in units)
    return {
        "total": len(units),
        "active": counts.get("active", 0),
        "failed": [u.name for u in units if u.active == "failed"],
        "counts": dict(counts),
    }


def read_units(runner: Runner = run_cmd) -> list[Unit]:
    try:
        out = runner(["systemctl", "list-units", "--type=service", "--all",
                      "-o", "json", "--no-pager"])
    except Exception:
        return []
    return parse_units(out)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_systemd_units.py -v`

- [ ] **Step 5: Commit** — `feat: parser de units systemd (json)`

---

### Task 6: Parser de ligações `ss` (`connections.py`)

**Files:** Create `sysscope/collector/connections.py`, `tests/test_connections.py`

**Interfaces:**
- `Connection(proto: str, state: str, local: str, remote: str, process: str | None, pid: int | None)` — frozen dataclass
- `parse_ss(text: str) -> list[Connection]`
- `read_connections(runner: Runner = run_cmd) -> list[Connection]` (`ss -tunpH`; `[]` em falha)

- [ ] **Step 1: Teste (falha)** — `tests/test_connections.py`:
```python
from sysscope.collector.connections import Connection, parse_ss, read_connections

SAMPLE = (
    'tcp   ESTAB 0 0 192.168.1.72:8989 172.19.0.7:49510 users:(("sonarr",pid=1234,fd=20))\n'
    'udp   UNCONN 0 0 192.168.1.72%wlp1s0:68 192.168.1.254:67 \n'
    'tcp   ESTAB 0 0 192.168.1.72:443 2.80.171.105:53504 users:(("jellyfin",pid=3181,fd=44))\n'
)


def test_parse_with_process():
    conns = parse_ss(SAMPLE)
    assert len(conns) == 3
    c = conns[0]
    assert c.proto == "tcp" and c.state == "ESTAB"
    assert c.local == "192.168.1.72:8989" and c.remote == "172.19.0.7:49510"
    assert c.process == "sonarr" and c.pid == 1234


def test_parse_without_process():
    c = parse_ss(SAMPLE)[1]
    assert c.proto == "udp" and c.process is None and c.pid is None


def test_read_empty_on_failure():
    def boom(argv):
        raise RuntimeError("ss em falta")
    assert read_connections(runner=boom) == []
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_connections.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/connections.py`:
```python
"""Parsing de `ss -tunpH` (ligações de rede com processo).

Colunas típicas: Netid State Recv-Q Send-Q Local Peer [Process]
O bloco de processo tem a forma: users:(("nome",pid=123,fd=4)).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd

_PROC_RE = re.compile(r'users:\(\("(?P<proc>[^"]+)",pid=(?P<pid>\d+)')


@dataclass(frozen=True)
class Connection:
    proto: str
    state: str
    local: str
    remote: str
    process: str | None
    pid: int | None


def parse_ss(text: str) -> list[Connection]:
    out: list[Connection] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        proto, state = parts[0], parts[1]
        # Local e Peer são os dois tokens com ':' após Recv-Q/Send-Q (índices 4 e 5).
        local, remote = parts[4], parts[5]
        m = _PROC_RE.search(line)
        process = m.group("proc") if m else None
        pid = int(m.group("pid")) if m else None
        out.append(Connection(proto, state, local, remote, process, pid))
    return out


def read_connections(runner: Runner = run_cmd) -> list[Connection]:
    try:
        out = runner(["ss", "-tunpH"])
    except Exception:
        return []
    return parse_ss(out)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_connections.py -v`

- [ ] **Step 5: Commit** — `feat: parser de ligações ss`

---

### Task 7: Coletor de serviços/rede + integração no loop

**Files:** Create `sysscope/collector/services_collector.py`; Modify `sysscope/common/config.py`, `sysscope/collector/main.py`

**Interfaces:**
- `config.py`: acrescentar campo `services_interval: float` ao `Config` e default `5.0` em `default_config()` e no `load_config` (ler `sampling.services_interval`).
- `services_collector.py`:
  - `ServicesCollector(config, db, clock, runner=run_cmd)` com `poll(self) -> None` que:
    - lê `docker stats`, `systemctl`, `ss`, `/proc/net/dev`;
    - escreve `put_snapshot("containers", ts, json)`, `put_snapshot("services", ts, json)`, `put_snapshot("connections", ts, json)`;
    - calcula taxas de rede vs. leitura anterior e faz `insert_net_sample(...)` por interface.
  - Guarda estado interno (amostra anterior de netdev + ts) para as taxas.
- `main.py`: instanciar `ServicesCollector` e chamar `poll()` na cadência `services_interval` (contador decrementado por `sample_interval`, como o power).

**Interfaces consumidas:** `read_container_stats`, `read_units`+`summarize`, `read_connections`, `parse_net_dev`+`net_rates` (com um `net_reader` que lê `/proc/net/dev`).

- [ ] **Step 1: Teste (falha)** — `tests/test_services_collector.py`:
```python
import json
from dataclasses import replace
from sysscope.common.config import default_config
from sysscope.storage.db import Database
from sysscope.collector.services_collector import ServicesCollector

NETDEV1 = "  eno1: 1000 5 0 0 0 0 0 0 2000 6 0 0 0 0 0 0\n"
NETDEV2 = "  eno1: 3000 5 0 0 0 0 0 0 6000 6 0 0 0 0 0 0\n"


def fake_runner(argv):
    if argv[0] == "docker":
        return "radarr|0.1%|10MiB / 1GiB|1MB / 2MB|3MB / 4MB\n"
    if argv[0] == "systemctl":
        return json.dumps([{"unit": "x.service", "active": "active", "sub": "running", "description": ""}])
    if argv[0] == "ss":
        return 'tcp ESTAB 0 0 1.2.3.4:80 5.6.7.8:9 users:(("radarr",pid=1,fd=2))\n'
    raise RuntimeError("desconhecido")


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def make(tmp_path, netdev_reader):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    cfg = replace(default_config(), db_path=str(tmp_path / "t.db"))
    clock = Clock()
    sc = ServicesCollector(cfg, db, clock=clock, runner=fake_runner,
                           net_reader=netdev_reader)
    return db, sc, clock


def test_snapshots_written(tmp_path):
    db, sc, clock = make(tmp_path, lambda: NETDEV1)
    sc.poll()
    assert json.loads(db.get_snapshot("containers")["payload"])[0]["name"] == "radarr"
    assert db.get_snapshot("services")["payload"]  # non-empty
    assert json.loads(db.get_snapshot("connections")["payload"])[0]["process"] == "radarr"


def test_net_rates_across_two_polls(tmp_path):
    readers = iter([NETDEV1, NETDEV2])
    db, sc, clock = make(tmp_path, lambda: next(readers))
    sc.poll()                 # baseline
    clock.t += 2.0
    sc.poll()                 # (3000-1000)/2 = 1000 rx_bps
    e = next(r for r in db.latest_net_status() if r["iface"] == "eno1")
    assert e["rx_bps"] == 1000.0 and e["tx_bps"] == 2000.0
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_services_collector.py -v`

- [ ] **Step 3: Implementar** — em `sysscope/common/config.py` acrescentar `services_interval: float` ao dataclass `Config`, `services_interval=5.0` em `default_config()`, e `services_interval=sampling.get("services_interval", cfg.services_interval)` no `replace(...)` de `load_config`.

Criar `sysscope/collector/services_collector.py`:
```python
"""Cadência lenta: serviços (systemd+docker), ligações e throughput de rede."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Callable

from sysscope.common.config import Config
from sysscope.common.run import Runner, run_cmd
from sysscope.storage.db import Database
from sysscope.collector.docker_stats import read_container_stats
from sysscope.collector.systemd_units import read_units, summarize
from sysscope.collector.connections import read_connections
from sysscope.collector.netdev import parse_net_dev, net_rates, NetStat


def _read_net_dev() -> str:
    with open("/proc/net/dev") as f:
        return f.read()


class ServicesCollector:
    def __init__(self, config: Config, db: Database,
                 clock: Callable[[], float],
                 runner: Runner = run_cmd,
                 net_reader: Callable[[], str] = _read_net_dev) -> None:
        self._cfg = config
        self._db = db
        self._clock = clock
        self._runner = runner
        self._net_reader = net_reader
        self._prev_net: dict[str, NetStat] = {}
        self._prev_net_ts: float | None = None

    def poll(self) -> None:
        now = self._clock()

        containers = [asdict(c) for c in read_container_stats(self._runner)]
        self._db.put_snapshot("containers", now, json.dumps(containers))

        units = read_units(self._runner)
        self._db.put_snapshot("services", now, json.dumps(summarize(units)))

        conns = [asdict(c) for c in read_connections(self._runner)]
        self._db.put_snapshot("connections", now, json.dumps(conns))

        curr = parse_net_dev(self._net_reader())
        if self._prev_net_ts is not None:
            dt = now - self._prev_net_ts
            for iface, cs in curr.items():
                prev = self._prev_net.get(iface)
                if prev is None:
                    continue
                rx, tx = net_rates(prev, cs, dt)
                self._db.insert_net_sample(now, iface, rx, tx)
        self._prev_net = curr
        self._prev_net_ts = now
```

Em `sysscope/collector/main.py`, dentro de `run(cfg, db)`:
```python
    from sysscope.collector.services_collector import ServicesCollector
    services = ServicesCollector(cfg, db, clock=time.time)
    services_countdown = 0.0
```
e no corpo do loop (a seguir ao bloco dos discos):
```python
        services_countdown -= cfg.sample_interval
        if services_countdown <= 0:
            services.poll()
            services_countdown = cfg.services_interval
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_services_collector.py -v`

- [ ] **Step 5: Smoke test manual (escreve snapshots reais)**

Run:
```bash
sudo python3 -c "
from sysscope.common.config import default_config
from sysscope.collector.services_collector import ServicesCollector
from sysscope.storage.db import Database
import time, dataclasses
cfg=dataclasses.replace(default_config(), db_path='/tmp/ss_p2.db')
db=Database(cfg.db_path); db.init_schema()
sc=ServicesCollector(cfg, db, clock=time.time)
sc.poll(); time.sleep(2); sc.poll()
import json
print('containers:', len(json.loads(db.get_snapshot('containers')['payload'])))
print('services failed:', json.loads(db.get_snapshot('services')['payload'])['failed'])
print('net ifaces:', [r['iface'] for r in db.latest_net_status()])
"
```
Expected: imprime nº de containers > 0, lista de serviços falhados, e interfaces de rede.

- [ ] **Step 6: Commit** — `feat: coletor de serviços/rede + integração no loop`

---

### Task 8: Endpoints web da Fase 2

**Files:** Modify `sysscope/web/app.py`; Create `tests/test_web_phase2.py`

**Interfaces (novos endpoints em `create_app`):**
- `GET /api/services` → o payload do snapshot `services` (dict) ou `{}`
- `GET /api/containers` → lista do snapshot `containers` ou `[]`
- `GET /api/network` → `{"interfaces": latest_net_status(), "connections": <snapshot connections ou []>}`
- `GET /api/network/samples?iface=<i>&since=<f>` → `recent_net_samples`

- [ ] **Step 1: Teste (falha)** — `tests/test_web_phase2.py`:
```python
import json
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def client(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.put_snapshot("services", 1.0, json.dumps({"total": 5, "active": 4, "failed": ["z.service"], "counts": {}}))
    db.put_snapshot("containers", 1.0, json.dumps([{"name": "radarr", "cpu_pct": 0.1}]))
    db.put_snapshot("connections", 1.0, json.dumps([{"proto": "tcp", "process": "sonarr"}]))
    db.insert_net_sample(1.0, "eno1", 100, 200)
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    return TestClient(create_app(ro, static_dir=str(tmp_path)))


def test_services(tmp_path):
    r = client(tmp_path).get("/api/services")
    assert r.status_code == 200 and r.json()["failed"] == ["z.service"]


def test_containers(tmp_path):
    r = client(tmp_path).get("/api/containers")
    assert r.json()[0]["name"] == "radarr"


def test_network(tmp_path):
    r = client(tmp_path).get("/api/network")
    body = r.json()
    assert body["interfaces"][0]["iface"] == "eno1"
    assert body["connections"][0]["process"] == "sonarr"


def test_network_samples(tmp_path):
    r = client(tmp_path).get("/api/network/samples?iface=eno1&since=0")
    assert len(r.json()) == 1
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_web_phase2.py -v`

- [ ] **Step 3: Implementar** — em `sysscope/web/app.py`, dentro de `create_app`, acrescentar (antes do bloco de estáticos), importando `json` no topo do ficheiro:
```python
    @app.get("/api/services")
    def services() -> dict:
        snap = db.get_snapshot("services")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/containers")
    def containers() -> list:
        snap = db.get_snapshot("containers")
        return json.loads(snap["payload"]) if snap else []

    @app.get("/api/network")
    def network() -> dict:
        conns = db.get_snapshot("connections")
        return {
            "interfaces": db.latest_net_status(),
            "connections": json.loads(conns["payload"]) if conns else [],
        }

    @app.get("/api/network/samples")
    def network_samples(iface: str, since: float = 0.0) -> list:
        return db.recent_net_samples(iface, since)
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_web_phase2.py tests/test_web.py -v`

- [ ] **Step 5: Commit** — `feat: endpoints web de serviços e rede`

---

### Task 9: Painéis do frontend (Serviços + Rede)

**Files:** Modify `sysscope/web/static/index.html`, `sysscope/web/static/style.css`, `sysscope/web/static/app.js`

**Nota de design:** manter o tema aprovado (Outfit/violeta/1100px, PT-PT). As novas secções seguem o mesmo estilo de cartões/tabelas das existentes. Formatar bytes/bps com os helpers já existentes (`fmtBytes`). Escapar strings com o helper `esc` já existente.

- [ ] **Step 1: Acrescentar secções ao `index.html`** (a seguir à secção de incidentes, antes dos `<script>`):
```html
    <section id="services" class="panel">
      <h2>Serviços</h2>
      <div id="services-summary" class="io"></div>
      <table id="containers-table">
        <thead><tr><th>Container</th><th>CPU</th><th>Memória</th><th>Rede (R/T)</th><th>Disco (R/W)</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>

    <section id="network" class="panel">
      <h2>Rede</h2>
      <table id="net-table">
        <thead><tr><th>Interface</th><th>↓ RX</th><th>↑ TX</th></tr></thead>
        <tbody></tbody>
      </table>
      <h3 style="font-size:15px;margin:16px 0 8px;color:var(--muted)">Ligações ativas</h3>
      <table id="conn-table">
        <thead><tr><th>Proto</th><th>Estado</th><th>Local</th><th>Remoto</th><th>Processo</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
```

- [ ] **Step 2: Acrescentar estilos ao `style.css`** (mínimos, reutilizam os existentes):
```css
#containers-table td:nth-child(2), #net-table td { font-variant-numeric: tabular-nums; }
h3 { font-weight: 600; }
```

- [ ] **Step 3: Acrescentar render + poll ao `app.js`** (no fim, antes de `init()` chamar as novas funções):
```javascript
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
```
E em `init()`, acrescentar após `loadIncidents()`:
```javascript
  await loadServices();
  await loadNetwork();
  setInterval(loadServices, 5000);
  setInterval(loadNetwork, 5000);
```

- [ ] **Step 4: Smoke test + redeploy**

Run:
```bash
python3 -c "
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app
from pathlib import Path
import json
db=Database('/tmp/ss_p2web.db'); db.init_schema()
db.put_snapshot('services',1.0,json.dumps({'total':1,'active':1,'failed':[],'counts':{}}))
app=create_app(db, str(Path('sysscope/web/static')))
c=TestClient(app)
assert c.get('/').status_code==200
assert c.get('/api/services').json()['total']==1
print('web fase 2 OK')
"
sudo rsync -a --delete sysscope /opt/sysscope/
sudo systemctl restart sysscope-collector sysscope-web
sleep 8
curl -s http://127.0.0.1:8787/api/containers | head -c 200; echo
systemctl is-active sysscope-collector sysscope-web
```
Expected: `web fase 2 OK`; `curl` devolve JSON de containers; ambos os serviços `active`.

- [ ] **Step 5: Commit** — `feat: painéis de serviços e rede no dashboard`

---

## Self-Review (cobertura vs. âmbito)

- **Serviços (systemd):** Tasks 5, 7, 8, 9. ✔
- **Docker BlockIO por container:** Tasks 1, 4, 7, 8, 9. ✔
- **Rede — throughput por interface:** Tasks 3, 7, 8, 9. ✔
- **Rede — ligações com processo:** Tasks 6, 7, 8, 9. ✔
- **Nunca acordar discos:** nenhum coletor novo acede aos mounts (docker/systemctl/ss//proc/net/dev). ✔
- **Degrada sem docker/ss/systemctl:** todos os `read_*` devolvem vazio em falha. ✔
- **bpftrace:** fora de âmbito (decidido saltar). ✔
- **Type consistency:** `ContainerStat`, `Unit`, `Connection`, `NetStat`, `ServicesCollector`, métodos `put_snapshot/get_snapshot/insert_net_sample/latest_net_status/recent_net_samples` consistentes entre tasks. ✔
- **Nota:** `services_collector` e a integração em `main.py` não têm teste unitário do loop de `main` (padrão pré-existente); cobertos por teste do `ServicesCollector` + smoke test.
