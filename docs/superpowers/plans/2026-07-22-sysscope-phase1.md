# SysScope Fase 1 — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detetar cada spin-up dos HDDs e atribuir o culpado (processo + container + ficheiro), com registo persistente ("flight recorder") e um dashboard web mínimo com o painel de Discos.

**Architecture:** Dois processos. Um *coletor* (root) sonda `/proc/diskstats` + estado de energia (`hdparm -C`) para detetar transições `standby→active`, e lê o stream do `fatrace` para atribuir acessos a ficheiros a processos/containers; ao detetar um spin-up grava um "incidente" com a janela de acessos em redor numa BD SQLite (WAL). Um servidor *web* (utilizador) lê a BD em modo só-leitura e serve um dashboard com estado dos discos ao vivo (WebSocket) e a timeline de incidentes.

**Tech Stack:** Python 3.13, FastAPI + uvicorn, `sqlite3` (stdlib), pytest. Frontend HTML/CSS/JS vanilla + uPlot. Tracers do sistema: `fatrace`, `hdparm`, `smartmontools` (via apt).

## Global Constraints

- **Nunca acordar os discos ao monitorizar.** Fontes permitidas: `/proc/diskstats`, `/sys/block/*/stat`, `hdparm -C` (CHECK POWER MODE, standby-safe), `smartctl -n standby`, `fatrace` (passivo). PROIBIDO: qualquer I/O nos mounts (`stat`, `ls`, leitura de ficheiros), SMART completo em disco adormecido, `updatedb`.
- **Python 3.13**, sem build step no frontend (ficheiros estáticos servidos diretamente).
- **Coletor corre como root; web corre como utilizador** e abre a BD `read_only`. Web faz bind apenas em `127.0.0.1`.
- **BD:** `/var/lib/sysscope/sysscope.db`, SQLite em modo WAL. Escrita só pelo coletor.
- **Discos-alvo (Fase 1):** `sdb`→`/media/HDD3TB` (8:16), `sdc`→`/media/HDD4TB` (8:32), `sdd`→`/mnt/HDD2TB` (8:48), `sde`→`/media/HDD8TB` (8:64). Sector size 512.
- **Idioma:** comentários e strings de UI em Português (PT-PT).
- **Estilo de commits:** `feat:`/`test:`/`chore:`/`docs:`; terminar com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Estrutura de ficheiros (Fase 1)

```
sysscope/
  pyproject.toml
  sysscope/
    __init__.py
    common/
      __init__.py
      config.py           # Disk, Config, default_config, load_config
      run.py              # Runner: wrapper de subprocess injetável
    storage/
      __init__.py
      db.py               # Database: schema, inserts, queries, retenção
    collector/
      __init__.py
      diskstats.py        # parse_diskstats, compute_rates
      power.py            # parse_hdparm_c, is_spun_down, PowerReader
      cgroup.py           # container_from_cgroup, ContainerResolver
      fatrace.py          # FatraceEvent, parse_fatrace_line, event_disk
      disk_collector.py   # DiskCollector: deteção de spin-up
      io_attribution.py   # AttributedEvent, IoAttribution: flight recorder
      main.py             # loop principal do coletor
    web/
      __init__.py
      app.py              # FastAPI: REST + WebSocket + estáticos
      static/
        index.html
        style.css
        app.js
        uplot.min.css
        uplot.iife.min.js
  systemd/
    sysscope-collector.service
    sysscope-web.service
  install.sh
  tests/
    __init__.py
    test_config.py
    test_db.py
    test_diskstats.py
    test_power.py
    test_cgroup.py
    test_fatrace.py
    test_disk_collector.py
    test_io_attribution.py
    test_web.py
```

---

### Task 1: Scaffolding do projeto e módulo de configuração

**Files:**
- Create: `pyproject.toml`, `sysscope/__init__.py`, `sysscope/common/__init__.py`, `sysscope/common/config.py`, `tests/__init__.py`, `tests/test_config.py`, `.gitignore`

**Interfaces:**
- Produces:
  - `Disk(name: str, device: str, mount: str, major: int, minor: int)` — frozen dataclass
  - `Config(disks: list[Disk], db_path: str, web_host: str, web_port: int, sample_interval: float, power_interval: float, idle_threshold: float, incident_window: float, retention_days: int)` — frozen dataclass
  - `default_config() -> Config`
  - `load_config(path: str | None = None) -> Config` — lê TOML se existir, senão devolve `default_config()`

- [ ] **Step 1: Criar `pyproject.toml` e `.gitignore`**

`pyproject.toml`:
```toml
[project]
name = "sysscope"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "psutil>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
*.db
*.db-wal
*.db-shm
```

- [ ] **Step 2: Escrever o teste (falha)**

`tests/test_config.py`:
```python
from sysscope.common.config import Disk, Config, default_config, load_config


def test_default_config_has_four_hdds():
    cfg = default_config()
    names = {d.name for d in cfg.disks}
    assert names == {"sdb", "sdc", "sdd", "sde"}


def test_default_disk_fields():
    cfg = default_config()
    sde = next(d for d in cfg.disks if d.name == "sde")
    assert sde.device == "/dev/sde"
    assert sde.mount == "/media/HDD8TB"
    assert (sde.major, sde.minor) == (8, 64)


def test_default_paths_and_intervals():
    cfg = default_config()
    assert cfg.db_path == "/var/lib/sysscope/sysscope.db"
    assert cfg.web_host == "127.0.0.1"
    assert cfg.web_port == 8787
    assert cfg.sample_interval > 0
    assert cfg.retention_days == 14


def test_load_config_falls_back_to_default(tmp_path):
    cfg = load_config(str(tmp_path / "missing.toml"))
    assert cfg.web_port == 8787


def test_load_config_overrides_from_toml(tmp_path):
    p = tmp_path / "sysscope.toml"
    p.write_text('[web]\nport = 9999\n')
    cfg = load_config(str(p))
    assert cfg.web_port == 9999
```

- [ ] **Step 3: Correr o teste (verificar falha)**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'sysscope.common.config'`

- [ ] **Step 4: Implementar `sysscope/common/config.py`**

```python
"""Configuração do SysScope: discos-alvo, caminhos e intervalos."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Disk:
    name: str      # "sde"
    device: str    # "/dev/sde"
    mount: str     # "/media/HDD8TB"
    major: int
    minor: int


@dataclass(frozen=True)
class Config:
    disks: list[Disk]
    db_path: str
    web_host: str
    web_port: int
    sample_interval: float   # segundos entre amostras de diskstats
    power_interval: float    # segundos entre sondagens hdparm -C
    idle_threshold: float    # segundos sem I/O para considerar "possivelmente adormecido"
    incident_window: float   # segundos de acessos a guardar em redor de um spin-up
    retention_days: int


def default_config() -> Config:
    return Config(
        disks=[
            Disk("sdb", "/dev/sdb", "/media/HDD3TB", 8, 16),
            Disk("sdc", "/dev/sdc", "/media/HDD4TB", 8, 32),
            Disk("sdd", "/dev/sdd", "/mnt/HDD2TB", 8, 48),
            Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
        ],
        db_path="/var/lib/sysscope/sysscope.db",
        web_host="127.0.0.1",
        web_port=8787,
        sample_interval=2.0,
        power_interval=10.0,
        idle_threshold=120.0,
        incident_window=6.0,
        retention_days=14,
    )


def load_config(path: str | None = None) -> Config:
    """Carrega config de um TOML; campos ausentes usam os defaults."""
    cfg = default_config()
    if path is None or not Path(path).exists():
        return cfg
    data = tomllib.loads(Path(path).read_text())
    web = data.get("web", {})
    storage = data.get("storage", {})
    sampling = data.get("sampling", {})
    return replace(
        cfg,
        db_path=storage.get("db_path", cfg.db_path),
        web_host=web.get("host", cfg.web_host),
        web_port=web.get("port", cfg.web_port),
        sample_interval=sampling.get("sample_interval", cfg.sample_interval),
        power_interval=sampling.get("power_interval", cfg.power_interval),
        idle_threshold=sampling.get("idle_threshold", cfg.idle_threshold),
        incident_window=sampling.get("incident_window", cfg.incident_window),
        retention_days=storage.get("retention_days", cfg.retention_days),
    )
```

- [ ] **Step 5: Correr os testes (passam)**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore sysscope/ tests/
git commit -m "feat: scaffolding e módulo de config

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Camada de base de dados (SQLite WAL)

**Files:**
- Create: `sysscope/storage/__init__.py`, `sysscope/storage/db.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: nada.
- Produces: classe `Database` com:
  - `__init__(self, path: str, read_only: bool = False)`
  - `init_schema(self) -> None`
  - `insert_disk_sample(self, ts: float, disk: str, power_state: str, read_bps: float, write_bps: float, read_iops: float, write_iops: float) -> None`
  - `create_incident(self, ts: float, disk: str, detection: str) -> int` (devolve `incident_id`)
  - `set_incident_culprit(self, incident_id: int, top_culprit: str) -> None`
  - `insert_io_event(self, ts: float, disk: str, pid: int, comm: str, container: str | None, op: str, path: str, source: str, incident_id: int) -> None`
  - `latest_disk_status(self) -> list[dict]` (última amostra por disco)
  - `recent_disk_samples(self, disk: str, since: float) -> list[dict]`
  - `list_incidents(self, limit: int = 50) -> list[dict]`
  - `incident_events(self, incident_id: int) -> list[dict]`
  - `purge_older_than(self, cutoff_ts: float) -> int`
  - `close(self) -> None`

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_db.py`:
```python
from sysscope.storage.db import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    return db


def test_insert_and_latest_status(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(100.0, "sde", "standby", 0, 0, 0, 0)
    db.insert_disk_sample(102.0, "sde", "active", 1000, 0, 5, 0)
    rows = db.latest_disk_status()
    sde = next(r for r in rows if r["disk"] == "sde")
    assert sde["power_state"] == "active"
    assert sde["read_bps"] == 1000


def test_incident_lifecycle(tmp_path):
    db = make_db(tmp_path)
    inc = db.create_incident(200.0, "sdc", "power")
    assert isinstance(inc, int)
    db.insert_io_event(200.1, "sdc", 4821, "bazarr", "bazarr", "open",
                       "/media/HDD4TB/x.mkv", "fatrace", inc)
    db.set_incident_culprit(inc, "bazarr (1 acesso)")
    incidents = db.list_incidents()
    assert incidents[0]["top_culprit"] == "bazarr (1 acesso)"
    events = db.incident_events(inc)
    assert events[0]["comm"] == "bazarr"
    assert events[0]["path"] == "/media/HDD4TB/x.mkv"


def test_recent_samples_filtered_by_since(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(10.0, "sdd", "active", 1, 1, 1, 1)
    db.insert_disk_sample(50.0, "sdd", "active", 2, 2, 2, 2)
    rows = db.recent_disk_samples("sdd", since=40.0)
    assert len(rows) == 1 and rows[0]["ts"] == 50.0


def test_purge_older_than(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(10.0, "sde", "active", 1, 1, 1, 1)
    db.insert_disk_sample(1000.0, "sde", "active", 1, 1, 1, 1)
    removed = db.purge_older_than(500.0)
    assert removed == 1
    assert len(db.recent_disk_samples("sde", 0.0)) == 1


def test_read_only_cannot_write(tmp_path):
    p = str(tmp_path / "ro.db")
    Database(p).init_schema()
    ro = Database(p, read_only=True)
    import sqlite3
    try:
        ro.insert_disk_sample(1.0, "sde", "active", 0, 0, 0, 0)
        assert False, "escrita devia falhar em read_only"
    except sqlite3.OperationalError:
        pass
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/storage/db.py`**

```python
"""Camada de persistência SQLite (modo WAL)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS disk_samples (
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    power_state TEXT NOT NULL,
    read_bps REAL NOT NULL,
    write_bps REAL NOT NULL,
    read_iops REAL NOT NULL,
    write_iops REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_disk_ts ON disk_samples(disk, ts);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    detection TEXT NOT NULL,
    top_culprit TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(ts);

CREATE TABLE IF NOT EXISTS io_events (
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    pid INTEGER NOT NULL,
    comm TEXT NOT NULL,
    container TEXT,
    op TEXT NOT NULL,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    incident_id INTEGER,
    FOREIGN KEY(incident_id) REFERENCES incidents(id)
);
CREATE INDEX IF NOT EXISTS idx_events_incident ON io_events(incident_id);
"""


class Database:
    def __init__(self, path: str, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if read_only:
            uri = f"file:{path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert_disk_sample(self, ts, disk, power_state, read_bps, write_bps,
                           read_iops, write_iops) -> None:
        self._conn.execute(
            "INSERT INTO disk_samples VALUES (?,?,?,?,?,?,?)",
            (ts, disk, power_state, read_bps, write_bps, read_iops, write_iops),
        )
        self._conn.commit()

    def create_incident(self, ts, disk, detection) -> int:
        cur = self._conn.execute(
            "INSERT INTO incidents (ts, disk, detection) VALUES (?,?,?)",
            (ts, disk, detection),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def set_incident_culprit(self, incident_id, top_culprit) -> None:
        self._conn.execute(
            "UPDATE incidents SET top_culprit=? WHERE id=?",
            (top_culprit, incident_id),
        )
        self._conn.commit()

    def insert_io_event(self, ts, disk, pid, comm, container, op, path,
                        source, incident_id) -> None:
        self._conn.execute(
            "INSERT INTO io_events VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, disk, pid, comm, container, op, path, source, incident_id),
        )
        self._conn.commit()

    def latest_disk_status(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT s.* FROM disk_samples s
               JOIN (SELECT disk, MAX(ts) AS mts FROM disk_samples GROUP BY disk) m
               ON s.disk = m.disk AND s.ts = m.mts"""
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_disk_samples(self, disk, since) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM disk_samples WHERE disk=? AND ts>? ORDER BY ts",
            (disk, since),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_incidents(self, limit=50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM incidents ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def incident_events(self, incident_id) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM io_events WHERE incident_id=? ORDER BY ts",
            (incident_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def purge_older_than(self, cutoff_ts) -> int:
        cur = self._conn.execute("DELETE FROM disk_samples WHERE ts<?", (cutoff_ts,))
        n = cur.rowcount
        self._conn.execute(
            "DELETE FROM io_events WHERE incident_id IN "
            "(SELECT id FROM incidents WHERE ts<?)", (cutoff_ts,))
        self._conn.execute("DELETE FROM incidents WHERE ts<?", (cutoff_ts,))
        self._conn.commit()
        return n

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/storage/ tests/test_db.py
git commit -m "feat: camada de BD SQLite (WAL) com amostras e incidentes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Parser de diskstats e cálculo de taxas

**Files:**
- Create: `sysscope/collector/__init__.py`, `sysscope/collector/diskstats.py`, `tests/test_diskstats.py`

**Interfaces:**
- Produces:
  - `DiskStat(reads: int, read_sectors: int, writes: int, write_sectors: int)` — frozen dataclass
  - `parse_diskstats(text: str, names: set[str]) -> dict[str, DiskStat]`
  - `DiskRates(read_iops: float, write_iops: float, read_bps: float, write_bps: float, active: bool)` — frozen dataclass
  - `compute_rates(prev: DiskStat, curr: DiskStat, dt: float, sector_size: int = 512) -> DiskRates`

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_diskstats.py`:
```python
from sysscope.collector.diskstats import (
    DiskStat, parse_diskstats, compute_rates,
)

SAMPLE = (
    "   8      16 sdb 156217 4110 35707470 759161 9560 2325778 18682704 125081 0 605244 884242 0 0 0 0 0 0\n"
    "   8      64 sde 734588 14168 177605984 1125714 56817 11179124 89887528 327691 0 987104 1453405 0 0 0 0 0 0\n"
    "   7       0 loop0 0 0 0 0 0 0 0 0 0 0 0\n"
)


def test_parse_selects_named_disks():
    stats = parse_diskstats(SAMPLE, {"sdb", "sde"})
    assert set(stats) == {"sdb", "sde"}
    assert stats["sde"].reads == 734588
    assert stats["sde"].read_sectors == 177605984
    assert stats["sde"].writes == 56817
    assert stats["sde"].write_sectors == 89887528


def test_parse_ignores_unnamed():
    stats = parse_diskstats(SAMPLE, {"sde"})
    assert set(stats) == {"sde"}


def test_compute_rates_basic():
    prev = DiskStat(reads=100, read_sectors=1000, writes=10, write_sectors=200)
    curr = DiskStat(reads=110, read_sectors=1200, writes=10, write_sectors=200)
    r = compute_rates(prev, curr, dt=2.0, sector_size=512)
    assert r.read_iops == 5.0            # 10 reads / 2s
    assert r.read_bps == 200 * 512 / 2.0  # 200 setores * 512 / 2s
    assert r.write_iops == 0.0
    assert r.active is True


def test_compute_rates_idle_is_inactive():
    s = DiskStat(reads=5, read_sectors=50, writes=5, write_sectors=50)
    r = compute_rates(s, s, dt=2.0)
    assert r.active is False
    assert r.read_bps == 0.0


def test_compute_rates_zero_dt_is_safe():
    prev = DiskStat(1, 1, 1, 1)
    curr = DiskStat(2, 2, 2, 2)
    r = compute_rates(prev, curr, dt=0.0)
    assert r.read_bps == 0.0 and r.active is True
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_diskstats.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/collector/diskstats.py`**

```python
"""Parsing de /proc/diskstats e cálculo de taxas de I/O.

Campos por linha (após major/minor/nome):
  1 reads_completed  3 sectors_read   5 writes_completed  7 sectors_written
Ref: Documentation/admin-guide/iostats.rst do kernel.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiskStat:
    reads: int
    read_sectors: int
    writes: int
    write_sectors: int


@dataclass(frozen=True)
class DiskRates:
    read_iops: float
    write_iops: float
    read_bps: float
    write_bps: float
    active: bool


def parse_diskstats(text: str, names: set[str]) -> dict[str, DiskStat]:
    out: dict[str, DiskStat] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 11:
            continue
        name = parts[2]
        if name not in names:
            continue
        out[name] = DiskStat(
            reads=int(parts[3]),
            read_sectors=int(parts[5]),
            writes=int(parts[7]),
            write_sectors=int(parts[9]),
        )
    return out


def compute_rates(prev: DiskStat, curr: DiskStat, dt: float,
                  sector_size: int = 512) -> DiskRates:
    d_reads = curr.reads - prev.reads
    d_writes = curr.writes - prev.writes
    d_rsec = curr.read_sectors - prev.read_sectors
    d_wsec = curr.write_sectors - prev.write_sectors
    active = (d_reads + d_writes + d_rsec + d_wsec) > 0
    if dt <= 0:
        return DiskRates(0.0, 0.0, 0.0, 0.0, active)
    return DiskRates(
        read_iops=d_reads / dt,
        write_iops=d_writes / dt,
        read_bps=d_rsec * sector_size / dt,
        write_bps=d_wsec * sector_size / dt,
        active=active,
    )
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_diskstats.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/collector/__init__.py sysscope/collector/diskstats.py tests/test_diskstats.py
git commit -m "feat: parser de diskstats e cálculo de taxas

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Estado de energia dos discos (`hdparm -C`) com fallback

**Files:**
- Create: `sysscope/common/run.py`, `sysscope/collector/power.py`, `tests/test_power.py`

**Interfaces:**
- Produces:
  - `run.py`: `Runner = Callable[[list[str]], str]`; `run_cmd(argv: list[str], timeout: float = 5.0) -> str` (stdout; lança `RunError` se código≠0)
  - `power.py`:
    - `parse_hdparm_c(output: str) -> str` → `"active" | "standby" | "sleeping" | "unknown"`
    - `is_spun_down(state: str) -> bool` (True para `standby`/`sleeping`)
    - `PowerReader(runner: Runner)` com `read(self, device: str) -> str` (devolve estado; `"unknown"` em falha)

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_power.py`:
```python
from sysscope.collector.power import parse_hdparm_c, is_spun_down, PowerReader

ACTIVE = "/dev/sde:\n drive state is:  active/idle\n"
STANDBY = "/dev/sdb:\n drive state is:  standby\n"
SLEEP = "/dev/sdc:\n drive state is:  sleeping\n"
UNKNOWN = "/dev/sdd:\n drive state is:  unknown\n"


def test_parse_states():
    assert parse_hdparm_c(ACTIVE) == "active"
    assert parse_hdparm_c(STANDBY) == "standby"
    assert parse_hdparm_c(SLEEP) == "sleeping"
    assert parse_hdparm_c(UNKNOWN) == "unknown"


def test_is_spun_down():
    assert is_spun_down("standby") is True
    assert is_spun_down("sleeping") is True
    assert is_spun_down("active") is False
    assert is_spun_down("unknown") is False


def test_power_reader_ok():
    pr = PowerReader(runner=lambda argv: STANDBY)
    assert pr.read("/dev/sdb") == "standby"


def test_power_reader_failure_returns_unknown():
    def boom(argv):
        raise RuntimeError("hdparm em falta")
    pr = PowerReader(runner=boom)
    assert pr.read("/dev/sdb") == "unknown"
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_power.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/common/run.py`**

```python
"""Wrapper injetável de subprocess."""
from __future__ import annotations

import subprocess
from typing import Callable

Runner = Callable[[list[str]], str]


class RunError(RuntimeError):
    pass


def run_cmd(argv: list[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RunError(f"{argv[0]}: {e}") from e
    if proc.returncode != 0:
        raise RunError(f"{argv[0]} saiu com {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout
```

- [ ] **Step 4: Implementar `sysscope/collector/power.py`**

```python
"""Leitura de estado de energia dos discos, sem os acordar.

`hdparm -C` usa o comando ATA CHECK POWER MODE (standby-safe). Em bridges USB
que não suportam SAT passthrough, devolve 'unknown' e o coletor recorre à
inferência por atividade.
"""
from __future__ import annotations

from sysscope.common.run import Runner, run_cmd

_SPUN_DOWN = {"standby", "sleeping"}


def parse_hdparm_c(output: str) -> str:
    low = output.lower()
    if "sleeping" in low:
        return "sleeping"
    if "standby" in low:
        return "standby"
    if "active" in low or "idle" in low:
        return "active"
    return "unknown"


def is_spun_down(state: str) -> bool:
    return state in _SPUN_DOWN


class PowerReader:
    def __init__(self, runner: Runner = run_cmd) -> None:
        self._runner = runner

    def read(self, device: str) -> str:
        try:
            out = self._runner(["hdparm", "-C", device])
        except Exception:
            return "unknown"
        return parse_hdparm_c(out)
```

- [ ] **Step 5: Correr os testes (passam)**

Run: `python -m pytest tests/test_power.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add sysscope/common/run.py sysscope/collector/power.py tests/test_power.py
git commit -m "feat: leitura standby-safe do estado de energia (hdparm -C)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Mapeamento PID → container Docker (cgroup)

**Files:**
- Create: `sysscope/collector/cgroup.py`, `tests/test_cgroup.py`

**Interfaces:**
- Produces:
  - `container_id_from_cgroup(text: str) -> str | None` (id completo de 64 hex, ou None)
  - `ContainerResolver(runner: Runner, proc_base: str = "/proc")` com:
    - `refresh(self) -> None` (corre `docker ps` e preenche `{id: name}`)
    - `name_for_pid(self, pid: int) -> str | None`

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_cgroup.py`:
```python
from sysscope.collector.cgroup import container_id_from_cgroup, ContainerResolver

CGROUP = "0::/system.slice/docker-5cc6d74a8b6cf71e46a3c54d3ca111f48effe94193d3e5b3ff572bf81636d09e.scope\n"
FULL = "5cc6d74a8b6cf71e46a3c54d3ca111f48effe94193d3e5b3ff572bf81636d09e"


def test_container_id_from_cgroup():
    assert container_id_from_cgroup(CGROUP) == FULL


def test_container_id_none_for_non_docker():
    assert container_id_from_cgroup("0::/user.slice/session-1.scope") is None


def test_resolver_maps_pid_to_name(tmp_path):
    proc = tmp_path / "proc" / "3181"
    proc.mkdir(parents=True)
    (proc / "cgroup").write_text(CGROUP)

    def fake_docker(argv):
        # docker ps --no-trunc --format '{{.ID}}|{{.Names}}'
        return f"{FULL}|jellyfin\ndeadbeef...|radarr\n"

    r = ContainerResolver(runner=fake_docker, proc_base=str(tmp_path / "proc"))
    r.refresh()
    assert r.name_for_pid(3181) == "jellyfin"


def test_resolver_returns_none_for_unknown_pid(tmp_path):
    (tmp_path / "proc").mkdir()
    r = ContainerResolver(runner=lambda a: "", proc_base=str(tmp_path / "proc"))
    r.refresh()
    assert r.name_for_pid(9999) is None
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_cgroup.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/collector/cgroup.py`**

```python
"""Resolução de PID → nome de container Docker via cgroup v2.

Linha típica de /proc/<pid>/cgroup:
  0::/system.slice/docker-<id64>.scope
"""
from __future__ import annotations

import re
from pathlib import Path

from sysscope.common.run import Runner, run_cmd

_DOCKER_RE = re.compile(r"docker-([0-9a-f]{64})\.scope")


def container_id_from_cgroup(text: str) -> str | None:
    m = _DOCKER_RE.search(text)
    return m.group(1) if m else None


class ContainerResolver:
    def __init__(self, runner: Runner = run_cmd, proc_base: str = "/proc") -> None:
        self._runner = runner
        self._proc = Path(proc_base)
        self._by_id: dict[str, str] = {}

    def refresh(self) -> None:
        try:
            out = self._runner(["docker", "ps", "--no-trunc",
                                "--format", "{{.ID}}|{{.Names}}"])
        except Exception:
            return
        mapping: dict[str, str] = {}
        for line in out.splitlines():
            if "|" not in line:
                continue
            cid, name = line.split("|", 1)
            mapping[cid.strip()] = name.strip()
        self._by_id = mapping

    def name_for_pid(self, pid: int) -> str | None:
        try:
            text = (self._proc / str(pid) / "cgroup").read_text()
        except OSError:
            return None
        cid = container_id_from_cgroup(text)
        if cid is None:
            return None
        return self._by_id.get(cid)
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_cgroup.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/collector/cgroup.py tests/test_cgroup.py
git commit -m "feat: resolução PID->container via cgroup

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Parser de linhas do `fatrace`

**Files:**
- Create: `sysscope/collector/fatrace.py`, `tests/test_fatrace.py`

**Interfaces:**
- Consumes: `Disk` de `sysscope.common.config`.
- Produces:
  - `FatraceEvent(comm: str, pid: int, types: str, path: str)` — frozen dataclass
  - `parse_fatrace_line(line: str) -> FatraceEvent | None`
  - `event_disk(path: str, disks: list[Disk]) -> str | None`
  - `op_from_types(types: str) -> str` (mapeia flags → `"read"|"write"|"open"|"other"`)

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_fatrace.py`:
```python
from sysscope.common.config import Disk
from sysscope.collector.fatrace import (
    FatraceEvent, parse_fatrace_line, event_disk, op_from_types,
)

DISKS = [
    Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
    Disk("sdd", "/dev/sdd", "/mnt/HDD2TB", 8, 48),
]


def test_parse_basic_line():
    ev = parse_fatrace_line("jellyfin(4821): R /media/HDD8TB/Movies/X.mkv")
    assert ev == FatraceEvent("jellyfin", 4821, "R", "/media/HDD8TB/Movies/X.mkv")


def test_parse_comm_with_spaces():
    ev = parse_fatrace_line("Media Server(1200): RO /mnt/HDD2TB/a b.txt")
    assert ev.comm == "Media Server"
    assert ev.pid == 1200
    assert ev.path == "/mnt/HDD2TB/a b.txt"


def test_parse_non_matching_returns_none():
    assert parse_fatrace_line("garbage line") is None
    assert parse_fatrace_line("") is None


def test_event_disk_matches_mount():
    assert event_disk("/media/HDD8TB/x", DISKS) == "sde"
    assert event_disk("/mnt/HDD2TB/y", DISKS) == "sdd"
    assert event_disk("/home/user/z", DISKS) is None


def test_op_from_types():
    assert op_from_types("R") == "read"
    assert op_from_types("W") == "write"
    assert op_from_types("RO") == "read"
    assert op_from_types("O") == "open"
    assert op_from_types("C") == "other"
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_fatrace.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/collector/fatrace.py`**

```python
"""Parsing do stream do fatrace.

Formato de linha: `comm(pid): <TIPOS> <path>`
Tipos fanotify: O=open, R=read, W=write, C=close, D=delete, +=create.
Corremos `fatrace` global e filtramos por prefixo de mount.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sysscope.common.config import Disk

_LINE_RE = re.compile(r"^(?P<comm>.+)\((?P<pid>\d+)\): (?P<types>[A-Z+<>]+) (?P<path>/.*)$")


@dataclass(frozen=True)
class FatraceEvent:
    comm: str
    pid: int
    types: str
    path: str


def parse_fatrace_line(line: str) -> FatraceEvent | None:
    m = _LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None
    return FatraceEvent(
        comm=m.group("comm"),
        pid=int(m.group("pid")),
        types=m.group("types"),
        path=m.group("path"),
    )


def event_disk(path: str, disks: list[Disk]) -> str | None:
    best: str | None = None
    best_len = -1
    for d in disks:
        if path == d.mount or path.startswith(d.mount + "/"):
            if len(d.mount) > best_len:
                best, best_len = d.name, len(d.mount)
    return best


def op_from_types(types: str) -> str:
    if "W" in types:
        return "write"
    if "R" in types:
        return "read"
    if "O" in types:
        return "open"
    return "other"
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_fatrace.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/collector/fatrace.py tests/test_fatrace.py
git commit -m "feat: parser de eventos do fatrace + filtro por mount

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Detetor de spin-up (`DiskCollector`)

**Files:**
- Create: `sysscope/collector/disk_collector.py`, `tests/test_disk_collector.py`

**Interfaces:**
- Consumes: `Config`, `Disk`, `DiskStat`, `parse_diskstats`, `compute_rates`, `PowerReader`, `is_spun_down`.
- Produces:
  - `DiskCollector(config, power_reader, on_spinup, on_sample, diskstats_reader, clock)` onde:
    - `diskstats_reader: Callable[[], str]` (devolve conteúdo de /proc/diskstats)
    - `on_sample: Callable[[float, str, str, DiskRates], None]` (ts, disco, power_state, taxas)
    - `on_spinup: Callable[[float, str, str], None]` (ts, disco, detection: `"power"|"inferido"`)
    - `clock: Callable[[], float]`
  - `poll(self) -> None` — uma iteração
- Lógica de deteção:
  - Sonda power a cada `power_interval` (contador interno). Estado autoritativo.
  - Transição `spun_down → not spun_down` no estado de energia ⇒ `on_spinup(..., "power")`.
  - Fallback (estado `unknown`): se houve inatividade ≥ `idle_threshold` e agora `rates.active`, ⇒ `on_spinup(..., "inferido")`.
  - Regista `last_active_ts` por disco.
  - Sempre chama `on_sample`.

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_disk_collector.py`:
```python
from sysscope.common.config import Config, Disk
from sysscope.collector.disk_collector import DiskCollector

DISKS = [Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64)]


def make_cfg(**kw):
    base = dict(disks=DISKS, db_path=":x:", web_host="127.0.0.1", web_port=1,
                sample_interval=1.0, power_interval=1.0, idle_threshold=100.0,
                incident_window=6.0, retention_days=14)
    base.update(kw)
    return Config(**base)


def stats(reads):
    # linha de diskstats de sde com `reads` leituras
    return (f"   8      64 sde {reads} 0 {reads*8} 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_power_transition_triggers_spinup():
    clock = Clock()
    states = iter(["standby", "active"])
    power = type("P", (), {"read": lambda self, dev: next(states)})()
    reads = iter([stats(10), stats(20)])
    spinups, samples = [], []
    dc = DiskCollector(
        make_cfg(), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append((d, det)),
        on_sample=lambda ts, d, ps, r: samples.append((d, ps)),
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll()                 # standby, baseline
    clock.t += 1.0
    dc.poll()                 # active -> spin-up
    assert spinups == [("sde", "power")]
    assert len(samples) == 2


def test_no_spinup_when_staying_active():
    clock = Clock()
    power = type("P", (), {"read": lambda self, dev: "active"})()
    reads = iter([stats(10), stats(20), stats(30)])
    spinups = []
    dc = DiskCollector(
        make_cfg(), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append(d),
        on_sample=lambda *a: None,
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll(); clock.t += 1; dc.poll(); clock.t += 1; dc.poll()
    assert spinups == []


def test_inferred_spinup_when_power_unknown():
    clock = Clock()
    power = type("P", (), {"read": lambda self, dev: "unknown"})()
    # sem atividade por muito tempo, depois atividade
    reads = iter([stats(10), stats(10), stats(50)])
    spinups = []
    dc = DiskCollector(
        make_cfg(idle_threshold=1.5), power_reader=power,
        on_spinup=lambda ts, d, det: spinups.append((d, det)),
        on_sample=lambda *a: None,
        diskstats_reader=lambda: next(reads), clock=clock,
    )
    dc.poll()               # baseline, last_active=1000
    clock.t += 2.0          # 2s sem atividade (> idle_threshold)
    dc.poll()               # ainda sem atividade
    clock.t += 2.0
    dc.poll()               # atividade após inatividade -> inferido
    assert spinups == [("sde", "inferido")]
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_disk_collector.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/collector/disk_collector.py`**

```python
"""Deteção de spin-up por disco, combinando estado de energia e atividade."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sysscope.common.config import Config
from sysscope.collector.diskstats import (
    DiskStat, parse_diskstats, compute_rates, DiskRates,
)
from sysscope.collector.power import is_spun_down


@dataclass
class _DiskState:
    prev_stat: DiskStat | None = None
    prev_ts: float | None = None
    power_state: str = "unknown"
    was_spun_down: bool = False
    last_active_ts: float | None = None
    power_countdown: float = 0.0


class DiskCollector:
    def __init__(self, config: Config, power_reader,
                 on_spinup: Callable[[float, str, str], None],
                 on_sample: Callable[[float, str, str, DiskRates], None],
                 diskstats_reader: Callable[[], str],
                 clock: Callable[[], float]) -> None:
        self._cfg = config
        self._power = power_reader
        self._on_spinup = on_spinup
        self._on_sample = on_sample
        self._read_diskstats = diskstats_reader
        self._clock = clock
        self._names = {d.name for d in config.disks}
        self._dev_by_name = {d.name: d.device for d in config.disks}
        self._state: dict[str, _DiskState] = {n: _DiskState() for n in self._names}

    def poll(self) -> None:
        now = self._clock()
        stats = parse_diskstats(self._read_diskstats(), self._names)
        for name, st in self._state.items():
            curr = stats.get(name)
            if curr is None:
                continue

            # --- estado de energia (throttled) ---
            st.power_countdown -= self._cfg.sample_interval
            if st.power_countdown <= 0:
                new_power = self._power.read(self._dev_by_name[name])
                st.power_countdown = self._cfg.power_interval
                spun = is_spun_down(new_power)
                if st.was_spun_down and not spun:
                    self._on_spinup(now, name, "power")
                if new_power != "unknown":
                    st.was_spun_down = spun
                st.power_state = new_power

            # --- taxas ---
            if st.prev_stat is not None and st.prev_ts is not None:
                dt = now - st.prev_ts
                rates = compute_rates(st.prev_stat, curr, dt)
            else:
                rates = DiskRates(0, 0, 0, 0, False)

            # --- fallback inferido (só quando power é unknown) ---
            if st.power_state == "unknown" and rates.active:
                if (st.last_active_ts is not None
                        and now - st.last_active_ts >= self._cfg.idle_threshold):
                    self._on_spinup(now, name, "inferido")

            if rates.active:
                st.last_active_ts = now
            elif st.last_active_ts is None:
                st.last_active_ts = now

            self._on_sample(now, name, st.power_state, rates)
            st.prev_stat = curr
            st.prev_ts = now
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_disk_collector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/collector/disk_collector.py tests/test_disk_collector.py
git commit -m "feat: detetor de spin-up (power + inferência)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Flight recorder de atribuição (`IoAttribution`)

**Files:**
- Create: `sysscope/collector/io_attribution.py`, `tests/test_io_attribution.py`

**Interfaces:**
- Consumes: `Database`, `Disk`.
- Produces:
  - `AttributedEvent(ts: float, disk: str, pid: int, comm: str, container: str | None, op: str, path: str, source: str)` — dataclass
  - `IoAttribution(db, window: float)` com:
    - `record(self, ev: AttributedEvent) -> None` (buffer recente + anexa a incidentes abertos)
    - `open_incident(self, incident_id: int, disk: str, ts: float) -> None` (faz backfill do buffer)
    - `finalize_due(self, now: float) -> None` (persiste eventos e escreve `top_culprit` dos incidentes vencidos)
  - `top_culprit(events: list[AttributedEvent]) -> str` (agrega por container/comm)

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_io_attribution.py`:
```python
from sysscope.storage.db import Database
from sysscope.collector.io_attribution import (
    AttributedEvent, IoAttribution, top_culprit,
)


def ev(ts, disk="sde", comm="bazarr", container="bazarr", path="/media/HDD8TB/x"):
    return AttributedEvent(ts, disk, 1, comm, container, "read", path, "fatrace")


def test_top_culprit_prefers_container():
    evs = [ev(1, comm="mono", container="bazarr"),
           ev(2, comm="mono", container="bazarr"),
           ev(3, comm="ffprobe", container="jellyfin")]
    assert top_culprit(evs) == "bazarr (2 acessos)"


def test_top_culprit_singular():
    assert top_culprit([ev(1)]) == "bazarr (1 acesso)"


def test_top_culprit_empty():
    assert top_culprit([]) == "desconhecido"


def test_backfill_and_finalize(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    io.record(ev(99.0))                 # antes do spin-up (dentro da janela)
    inc = db.create_incident(100.0, "sde", "power")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0))                # depois do spin-up
    io.record(ev(101.0, disk="sdd"))    # outro disco -> ignorado
    io.finalize_due(now=200.0)          # já passou a deadline
    events = db.incident_events(inc)
    assert len(events) == 2
    assert db.list_incidents()[0]["top_culprit"] == "bazarr (2 acessos)"


def test_not_finalized_before_deadline(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    inc = db.create_incident(100.0, "sde", "power")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0))
    io.finalize_due(now=102.0)          # deadline = 105, ainda não
    assert db.list_incidents()[0]["top_culprit"] is None
    assert db.incident_events(inc) == []
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_io_attribution.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/collector/io_attribution.py`**

```python
"""Flight recorder: correlaciona acessos a ficheiros com incidentes de spin-up.

Mantém um buffer curto de eventos recentes (para backfill de acessos que
precedem imediatamente o spin-up) e, para cada incidente aberto, acumula os
acessos ao mesmo disco até `window` segundos depois. Ao expirar, persiste os
eventos e calcula o culpado principal.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass


@dataclass
class AttributedEvent:
    ts: float
    disk: str
    pid: int
    comm: str
    container: str | None
    op: str
    path: str
    source: str


def top_culprit(events: list[AttributedEvent]) -> str:
    if not events:
        return "desconhecido"
    counts = Counter(e.container or e.comm for e in events)
    name, n = counts.most_common(1)[0]
    unidade = "acesso" if n == 1 else "acessos"
    return f"{name} ({n} {unidade})"


@dataclass
class _OpenIncident:
    incident_id: int
    disk: str
    ts: float
    deadline: float
    events: list[AttributedEvent]


class IoAttribution:
    def __init__(self, db, window: float) -> None:
        self._db = db
        self._window = window
        self._recent: deque[AttributedEvent] = deque()
        self._open: list[_OpenIncident] = []

    def record(self, ev: AttributedEvent) -> None:
        self._recent.append(ev)
        cutoff = ev.ts - self._window
        while self._recent and self._recent[0].ts < cutoff:
            self._recent.popleft()
        for inc in self._open:
            if ev.disk == inc.disk and ev.ts <= inc.deadline:
                inc.events.append(ev)

    def open_incident(self, incident_id: int, disk: str, ts: float) -> None:
        backfill = [e for e in self._recent
                    if e.disk == disk and e.ts >= ts - self._window]
        self._open.append(_OpenIncident(
            incident_id=incident_id, disk=disk, ts=ts,
            deadline=ts + self._window, events=list(backfill),
        ))

    def finalize_due(self, now: float) -> None:
        still_open: list[_OpenIncident] = []
        for inc in self._open:
            if now < inc.deadline:
                still_open.append(inc)
                continue
            for e in inc.events:
                self._db.insert_io_event(
                    e.ts, e.disk, e.pid, e.comm, e.container, e.op,
                    e.path, e.source, inc.incident_id)
            self._db.set_incident_culprit(inc.incident_id, top_culprit(inc.events))
        self._open = still_open
```

- [ ] **Step 4: Correr os testes (passam)**

Run: `python -m pytest tests/test_io_attribution.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/collector/io_attribution.py tests/test_io_attribution.py
git commit -m "feat: flight recorder de atribuição de spin-up

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Loop principal do coletor (`main.py`)

**Files:**
- Create: `sysscope/collector/main.py`

**Interfaces:**
- Consumes: tudo o anterior.
- Produces: `main() -> None` (ponto de entrada); função `run(config, db, ...)` isolável.

Este task é de integração (subprocessos reais). Não há teste unitário TDD; verificação por smoke test manual no fim.

- [ ] **Step 1: Implementar `sysscope/collector/main.py`**

```python
"""Loop principal do coletor SysScope (corre como root).

Arranca uma thread que lê o stream do `fatrace` e alimenta o flight recorder,
e um loop de sondagem que lê diskstats + estado de energia para detetar
spin-ups. Ao detetar um spin-up, cria o incidente e abre a janela de captura.
"""
from __future__ import annotations

import signal
import subprocess
import threading
import time

from sysscope.common.config import load_config, Config
from sysscope.storage.db import Database
from sysscope.collector.power import PowerReader
from sysscope.collector.cgroup import ContainerResolver
from sysscope.collector.disk_collector import DiskCollector
from sysscope.collector.io_attribution import IoAttribution, AttributedEvent
from sysscope.collector.fatrace import parse_fatrace_line, event_disk, op_from_types

_stop = threading.Event()


def _read_diskstats() -> str:
    with open("/proc/diskstats") as f:
        return f.read()


def _fatrace_loop(cfg: Config, io: IoAttribution, resolver: ContainerResolver) -> None:
    """Lê o stream do fatrace e regista acessos aos discos-alvo."""
    proc = subprocess.Popen(
        ["fatrace", "--timestamp"], stdout=subprocess.PIPE, text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if _stop.is_set():
            break
        # `fatrace --timestamp` prefixa "HH:MM:SS.ffffff "; retiramos o prefixo.
        payload = line.split(" ", 1)[1] if line[:2].isdigit() else line
        ev = parse_fatrace_line(payload)
        if ev is None:
            continue
        disk = event_disk(ev.path, cfg.disks)
        if disk is None:
            continue
        io.record(AttributedEvent(
            ts=time.time(), disk=disk, pid=ev.pid, comm=ev.comm,
            container=resolver.name_for_pid(ev.pid),
            op=op_from_types(ev.types), path=ev.path, source="fatrace",
        ))
    proc.terminate()


def run(cfg: Config, db: Database) -> None:
    resolver = ContainerResolver()
    resolver.refresh()
    io = IoAttribution(db, window=cfg.incident_window)

    def on_spinup(ts: float, disk: str, detection: str) -> None:
        inc = db.create_incident(ts, disk, detection)
        io.open_incident(inc, disk, ts)

    def on_sample(ts, disk, power_state, rates) -> None:
        db.insert_disk_sample(ts, disk, power_state, rates.read_bps,
                              rates.write_bps, rates.read_iops, rates.write_iops)

    collector = DiskCollector(
        cfg, PowerReader(), on_spinup, on_sample,
        diskstats_reader=_read_diskstats, clock=time.time,
    )

    ft = threading.Thread(target=_fatrace_loop, args=(cfg, io, resolver), daemon=True)
    ft.start()

    last_refresh = 0.0
    last_purge = 0.0
    while not _stop.is_set():
        now = time.time()
        collector.poll()
        io.finalize_due(now)
        if now - last_refresh > 30:
            resolver.refresh()
            last_refresh = now
        if now - last_purge > 3600:
            db.purge_older_than(now - cfg.retention_days * 86400)
            last_purge = now
        _stop.wait(cfg.sample_interval)


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *a: _stop.set())
    signal.signal(signal.SIGINT, lambda *a: _stop.set())
    cfg = load_config("/etc/sysscope/sysscope.toml")
    db = Database(cfg.db_path)
    db.init_schema()
    try:
        run(cfg, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test manual (coletor escreve amostras)**

Run:
```bash
sudo apt-get install -y fatrace hdparm smartmontools
sudo python -c "
from sysscope.common.config import default_config
from sysscope.collector.main import run
from sysscope.storage.db import Database
import threading, time, dataclasses
cfg = dataclasses.replace(default_config(), db_path='/tmp/ss_smoke.db', sample_interval=1.0)
db = Database(cfg.db_path); db.init_schema()
t = threading.Thread(target=run, args=(cfg, db), daemon=True); t.start()
time.sleep(5)
import sysscope.collector.main as m; m._stop.set(); time.sleep(1)
print('amostras:', len(db.recent_disk_samples('sde', 0.0)))
"
```
Expected: imprime `amostras:` com um número > 0 (ex.: 4–5).

- [ ] **Step 3: Commit**

```bash
git add sysscope/collector/main.py
git commit -m "feat: loop principal do coletor (fatrace + deteção de spin-up)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Servidor web FastAPI (REST + WebSocket)

**Files:**
- Create: `sysscope/web/__init__.py`, `sysscope/web/app.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: `Database` (read_only), `load_config`.
- Produces:
  - `create_app(db: Database, static_dir: str) -> FastAPI`
  - Endpoints:
    - `GET /api/disks` → `[{disk, power_state, read_bps, write_bps, read_iops, write_iops, ts}]`
    - `GET /api/disks/{disk}/samples?since=<float>` → lista de amostras
    - `GET /api/incidents?limit=<int>` → lista de incidentes
    - `GET /api/incidents/{id}` → `{incident, events}`
    - `WS /ws` → envia `/api/disks` a cada 2 s
    - `GET /` → serve `index.html`
  - `main() -> None` (arranca uvicorn)

- [ ] **Step 1: Escrever o teste (falha)**

`tests/test_web.py`:
```python
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def seeded_db(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.insert_disk_sample(100.0, "sde", "active", 1000, 0, 5, 0)
    inc = db.create_incident(100.0, "sde", "power")
    db.insert_io_event(100.1, "sde", 1, "bazarr", "bazarr", "read",
                       "/media/HDD8TB/x", "fatrace", inc)
    db.set_incident_culprit(inc, "bazarr (1 acesso)")
    return db, inc


def client(tmp_path):
    db, inc = seeded_db(tmp_path)
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    app = create_app(ro, static_dir=str(tmp_path))
    return TestClient(app), inc


def test_disks_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/disks")
    assert r.status_code == 200
    assert r.json()[0]["disk"] == "sde"
    assert r.json()[0]["power_state"] == "active"


def test_incidents_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/incidents")
    assert r.status_code == 200
    assert r.json()[0]["top_culprit"] == "bazarr (1 acesso)"


def test_incident_detail(tmp_path):
    c, inc = client(tmp_path)
    r = c.get(f"/api/incidents/{inc}")
    assert r.status_code == 200
    body = r.json()
    assert body["incident"]["disk"] == "sde"
    assert body["events"][0]["comm"] == "bazarr"


def test_samples_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/disks/sde/samples?since=0")
    assert r.status_code == 200
    assert len(r.json()) == 1
```

- [ ] **Step 2: Correr o teste (falha)**

Run: `python -m pytest tests/test_web.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `sysscope/web/app.py`**

```python
"""Servidor web do SysScope: REST + WebSocket + ficheiros estáticos."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sysscope.common.config import load_config
from sysscope.storage.db import Database


def create_app(db: Database, static_dir: str) -> FastAPI:
    app = FastAPI(title="SysScope")

    @app.get("/api/disks")
    def disks() -> list[dict]:
        return db.latest_disk_status()

    @app.get("/api/disks/{disk}/samples")
    def samples(disk: str, since: float = 0.0) -> list[dict]:
        return db.recent_disk_samples(disk, since)

    @app.get("/api/incidents")
    def incidents(limit: int = 50) -> list[dict]:
        return db.list_incidents(limit)

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: int) -> dict:
        items = db.list_incidents(1000)
        match = next((i for i in items if i["id"] == incident_id), None)
        return {"incident": match, "events": db.incident_events(incident_id)}

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        try:
            while True:
                await sock.send_json({"disks": db.latest_disk_status()})
                await asyncio.sleep(2.0)
        except WebSocketDisconnect:
            return

    static_path = Path(static_dir)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_path / "index.html")

    if (static_path / "app.js").exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    return app


def main() -> None:
    import uvicorn
    cfg = load_config("/etc/sysscope/sysscope.toml")
    db = Database(cfg.db_path, read_only=True)
    static_dir = str(Path(__file__).parent / "static")
    app = create_app(db, static_dir)
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr os testes (passam)**

Nota: cria `sysscope/web/__init__.py` vazio. O teste passa `static_dir=tmp_path` (sem `app.js`), por isso o mount é ignorado e `GET /` não é testado (não há `index.html`); os testes cobrem só os endpoints REST.

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sysscope/web/__init__.py sysscope/web/app.py tests/test_web.py
git commit -m "feat: servidor web FastAPI (REST + WebSocket)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Frontend do dashboard (painel de Discos)

**Files:**
- Create: `sysscope/web/static/index.html`, `sysscope/web/static/style.css`, `sysscope/web/static/app.js`
- Download: `sysscope/web/static/uplot.iife.min.js`, `sysscope/web/static/uplot.min.css`

**Nota de design:** antes de escrever o CSS/JS, invocar as skills `frontend-design` e `dataviz` para calibrar a paleta (tema violeta aprovado), tipografia (fonte Outfit) e os gráficos de série temporal. O código abaixo é a base funcional a refinar com essas skills.

- [ ] **Step 1: Obter uPlot (vendorizado)**

Run:
```bash
mkdir -p sysscope/web/static
curl -sL https://unpkg.com/uplot@1.6.31/dist/uPlot.iife.min.js -o sysscope/web/static/uplot.iife.min.js
curl -sL https://unpkg.com/uplot@1.6.31/dist/uPlot.min.css -o sysscope/web/static/uplot.min.css
test -s sysscope/web/static/uplot.iife.min.js && echo "uPlot OK"
```
Expected: imprime `uPlot OK`.

- [ ] **Step 2: Criar `sysscope/web/static/index.html`**

```html
<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SysScope</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/uplot.min.css">
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>Sys<span>Scope</span></h1>
    <p class="sub">Monitorização de spin-up dos discos</p>
  </header>

  <main>
    <section id="disks" class="panel">
      <h2>Discos</h2>
      <div id="disk-cards" class="cards"></div>
    </section>

    <section id="incidents" class="panel">
      <h2>Incidentes de spin-up</h2>
      <table id="incident-table">
        <thead><tr><th>Quando</th><th>Disco</th><th>Deteção</th><th>Culpado</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
  </main>

  <script src="/static/uplot.iife.min.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Criar `sysscope/web/static/style.css`**

```css
:root {
  --bg: #0f0e17;
  --panel: #1a1826;
  --accent: #8b5cf6;
  --accent-soft: #a78bfa;
  --text: #e7e5f0;
  --muted: #9d99b3;
  --active: #34d399;
  --standby: #6b7280;
  --border: #2a2740;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Outfit", system-ui, sans-serif;
}
header { max-width: 1100px; margin: 0 auto; padding: 32px 24px 8px; }
h1 { font-size: 30px; font-weight: 700; margin: 0; letter-spacing: -0.5px; }
h1 span { color: var(--accent); }
.sub { color: var(--muted); margin: 4px 0 0; }
main { max-width: 1100px; margin: 0 auto; padding: 16px 24px 64px; }
.panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 16px; padding: 20px 24px; margin-top: 24px;
}
.panel h2 { font-size: 18px; font-weight: 600; margin: 0 0 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
.card { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.card .name { font-weight: 600; font-size: 16px; }
.card .state { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; margin-top: 8px; }
.state.active { background: rgba(52,211,153,.15); color: var(--active); }
.state.standby, .state.sleeping { background: rgba(107,114,128,.2); color: var(--standby); }
.state.unknown { background: rgba(139,92,246,.15); color: var(--accent-soft); }
.card .io { color: var(--muted); font-size: 13px; margin-top: 10px; line-height: 1.6; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }
td .culprit { color: var(--accent-soft); font-weight: 600; }
```

- [ ] **Step 4: Criar `sysscope/web/static/app.js`**

```javascript
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
```

- [ ] **Step 5: Smoke test manual (dashboard carrega)**

Run:
```bash
python -c "
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app
from pathlib import Path
db = Database('/tmp/ss_web.db'); db.init_schema()
db.insert_disk_sample(1.0,'sde','active',1000,0,5,0)
app = create_app(db, str(Path('sysscope/web/static')))
c = TestClient(app)
r = c.get('/')
assert r.status_code == 200 and 'SysScope' in r.text, r.status_code
print('dashboard OK')
"
```
Expected: imprime `dashboard OK`.

- [ ] **Step 6: Commit**

```bash
git add sysscope/web/static/
git commit -m "feat: dashboard frontend com painel de discos e incidentes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Instalação e serviços systemd

**Files:**
- Create: `systemd/sysscope-collector.service`, `systemd/sysscope-web.service`, `install.sh`, `README.md`

**Interfaces:** nenhuma (deploy). Verificação manual no fim.

- [ ] **Step 1: Criar `systemd/sysscope-collector.service`**

```ini
[Unit]
Description=SysScope collector (root)
After=docker.service
Wants=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/sysscope
ExecStart=/opt/sysscope/.venv/bin/python -m sysscope.collector.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Criar `systemd/sysscope-web.service`**

```ini
[Unit]
Description=SysScope web dashboard
After=sysscope-collector.service

[Service]
Type=simple
User=infectedserver
WorkingDirectory=/opt/sysscope
ExecStart=/opt/sysscope/.venv/bin/python -m sysscope.web.app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Criar `install.sh`**

```bash
#!/usr/bin/env bash
# Instalador do SysScope: dependências de tracing, venv e serviços systemd.
set -euo pipefail

DEST=/opt/sysscope
USER_NAME=${SUDO_USER:-$(whoami)}

echo "==> A instalar dependências de sistema (tracers)"
sudo apt-get update
sudo apt-get install -y fatrace hdparm smartmontools python3-venv

echo "==> A copiar o projeto para $DEST"
sudo mkdir -p "$DEST"
sudo cp -r sysscope pyproject.toml "$DEST/"

echo "==> A criar o virtualenv"
sudo python3 -m venv "$DEST/.venv"
sudo "$DEST/.venv/bin/pip" install -q --upgrade pip
sudo "$DEST/.venv/bin/pip" install -q fastapi "uvicorn[standard]" psutil

echo "==> A criar diretórios de dados"
sudo mkdir -p /var/lib/sysscope /etc/sysscope
sudo chown "$USER_NAME" /var/lib/sysscope

echo "==> A instalar serviços systemd"
sudo sed "s/^User=infectedserver/User=$USER_NAME/" systemd/sysscope-web.service \
  | sudo tee /etc/systemd/system/sysscope-web.service >/dev/null
sudo cp systemd/sysscope-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sysscope-collector.service sysscope-web.service

echo "==> Feito. Dashboard em http://127.0.0.1:8787"
```

Nota: o coletor (root) cria a BD; o serviço web (utilizador) precisa de a ler. Por isso `chown` de `/var/lib/sysscope` para o utilizador e a BD é criada com permissões de leitura. Se o serviço web falhar a abrir a BD, correr `sudo chmod 644 /var/lib/sysscope/sysscope.db*`.

- [ ] **Step 4: Criar `README.md`**

```markdown
# SysScope

Monitorização de spin-up dos discos num media server Debian. Deteta quando cada
HDD acorda e atribui o processo/container/ficheiro responsável ("flight
recorder"), com dashboard web.

## Instalação

    ./install.sh

Dashboard: http://127.0.0.1:8787

## Serviços

- `sysscope-collector.service` (root) — recolha e tracing
- `sysscope-web.service` (utilizador) — dashboard

## Logs

    journalctl -u sysscope-collector -f
    journalctl -u sysscope-web -f

## Testes

    python -m pytest
```

- [ ] **Step 5: Correr toda a suite de testes**

Run: `python -m pytest -v`
Expected: PASS (todos os testes das tasks 1–10 passam).

- [ ] **Step 6: Instalação e verificação end-to-end**

Run:
```bash
chmod +x install.sh && ./install.sh
sleep 8
systemctl is-active sysscope-collector sysscope-web
curl -s http://127.0.0.1:8787/api/disks | head -c 300
```
Expected: ambos os serviços `active`; o `curl` devolve JSON com os discos.

- [ ] **Step 7: Commit**

```bash
git add systemd/ install.sh README.md
git commit -m "feat: instalador, serviços systemd e README

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (cobertura vs. spec)

- **Regra de ouro (não acordar discos):** `_read_diskstats` lê `/proc/diskstats`; `PowerReader` usa `hdparm -C`; `fatrace` é passivo. Nenhum acesso aos mounts. ✔
- **Deteção de spin-up (power + inferência):** Task 7. ✔
- **Atribuição (fatrace + cgroup + flight recorder):** Tasks 5, 6, 8, 9. ✔
- **Persistência com incidentes + retenção:** Task 2 + purga no Task 9/main. ✔
- **Dashboard web (Discos + incidentes, WebSocket ao vivo, Outfit/violeta):** Tasks 10, 11. ✔
- **Deploy systemd nativo com separação de privilégios:** Task 12. ✔
- **Fora de âmbito confirmado (Fase 2):** bpftrace (confirmação de bloco), painéis Serviços/Wake-ups/Rede/Processos/Sistema. Documentado no início.
- **Type consistency:** `DiskRates`, `AttributedEvent`, `Database.*`, `on_spinup(ts, disk, detection)`, `on_sample(ts, disk, power_state, rates)` consistentes entre tasks. ✔
- **Nota:** os testes de `test_web.py` cobrem REST; o `GET /` é validado por smoke test (Task 11 Step 5) por precisar dos estáticos reais.
```
