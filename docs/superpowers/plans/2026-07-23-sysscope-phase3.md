# SysScope Fase 3 — Plano (atribuição p/ containers + painéis Sistema/Wake-ups/Processos)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** (1) Corrigir a atribuição de spin-up para funcionar com processos em containers (matching por dispositivo, não por caminho). (2) Acrescentar os painéis Sistema, Wake-ups e Processos. (3) Polimento seguro.

**Architecture:** A atribuição passa a determinar o disco de um FD via `/proc/PID/fdinfo` (mnt_id) → `/proc/PID/mountinfo` (dispositivo de origem, ex.: /dev/sde1), agnóstico ao mount namespace do container. Três novos coletores (Sistema/Wake-ups/Processos) correm na cadência lenta existente e escrevem snapshots JSON; novos endpoints + secções no dashboard.

**Tech Stack:** Python 3.13, FastAPI, psutil (já dependência), `/proc`, `systemctl`, `ss`. Sem bpftrace, sem powertop, sem autenticação (fora de âmbito).

## Global Constraints
- Python 3.13; comentários/UI em PT-PT.
- **Nunca acordar discos:** só leituras de `/proc` (incl. `fdinfo`/`mountinfo`/`readlink`), `systemctl`, psutil (CPU/mem/temps), `/sys/class/rtc`, ficheiros de cron. NADA nos mounts dos HDD (`/media/HDD*`, `/mnt/HDD2TB`). `readlink`/leitura de `/proc/*` não acede a conteúdo de ficheiros.
- Degradar com robustez: qualquer fonte em falta ⇒ painel vazio, coletor nunca crasha.
- Commits terminam com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; usar `git -c user.name="Leandro" -c user.email="leandrommferreira@gmail.com" commit ...`. Testes: `python3 -m pytest`.
- Deploy: `sudo rsync -a --delete sysscope /opt/sysscope/ && sudo systemctl restart sysscope-collector sysscope-web`.
- Discos-alvo e devices: sdb=/dev/sdb (part sdb2), sdc=/dev/sdc (sdc1), sdd=/dev/sdd (sdd1), sde=/dev/sde (sde1). `Disk.device` é o disco base (ex.: /dev/sde); o mountinfo mostra a partição (/dev/sde1).

---

### Task 1: ⭐ Atribuição por dispositivo (corrige containers) — `fdscan.py`

**Files:** Rewrite `sysscope/collector/fdscan.py`; Rewrite `tests/test_fdscan.py`

**Problema:** processos em containers têm os HDD montados noutros caminhos (ex.: `/media/HDD8TB`→`/hdd8`), por isso `readlink /proc/PID/fd` devolve `/hdd8/...` e o match por prefixo de mount do host falha → 0 atribuições. Solução: matching por dispositivo via fdinfo(mnt_id)→mountinfo(source).

**Interfaces:**
- `OpenFile(pid: int, comm: str, disk: str, path: str)` — frozen dataclass (inalterado)
- `disk_for_source(source: str, disks: list[Disk]) -> str | None`
- `parse_mountinfo(text: str, disks: list[Disk]) -> dict[int, str]` — {mount_id: nome_disco}
- `scan_open_files(disks, proc_base="/proc", exclude_pids=frozenset()) -> list[OpenFile]`

- [ ] **Step 1: Teste (falha)** — `tests/test_fdscan.py` (substituir):
```python
import os
from sysscope.common.config import Disk
from sysscope.collector.fdscan import (
    OpenFile, disk_for_source, parse_mountinfo, scan_open_files,
)

DISKS = [Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
         Disk("sdb", "/dev/sdb", "/media/HDD3TB", 8, 16)]

MOUNTINFO = (
    "1616 1615 0:50 / / rw,relatime - overlay overlay rw,lowerdir=x\n"
    "1848 1616 8:65 / /hdd8 rw,relatime - fuseblk /dev/sde1 rw,user_id=0\n"
    "1850 1616 8:17 / /hdd3 rw,relatime - fuseblk /dev/sdb2 rw,user_id=0\n"
)


def test_disk_for_source_matches_partition():
    assert disk_for_source("/dev/sde1", DISKS) == "sde"
    assert disk_for_source("/dev/sde", DISKS) == "sde"
    assert disk_for_source("/dev/sdb2", DISKS) == "sdb"
    assert disk_for_source("/dev/sda1", DISKS) is None


def test_parse_mountinfo_maps_target_mounts():
    m = parse_mountinfo(MOUNTINFO, DISKS)
    assert m == {1848: "sde", 1850: "sdb"}   # overlay ignorado


def _mkproc(tmp_path, pid, mountinfo, fds):
    """fds: list of (fdname, mnt_id, target_path)."""
    p = tmp_path / str(pid); (p / "fd").mkdir(parents=True); (p / "fdinfo").mkdir()
    (p / "mountinfo").write_text(mountinfo)
    (p / "comm").write_text("jellyfin\n")
    for name, mnt_id, target in fds:
        os.symlink(target, p / "fd" / name)
        (p / "fdinfo" / name).write_text(f"pos:\t0\nflags:\t0100000\nmnt_id:\t{mnt_id}\n")


def test_scan_attributes_container_fd_by_device(tmp_path):
    # fd aponta para caminho do CONTAINER (/hdd8/...), mnt_id do mount /hdd8 (1848)
    _mkproc(tmp_path, 3181, MOUNTINFO,
            [("20", 1848, "/hdd8/Movies/X.mkv"), ("3", 1616, "/dev/null")])
    res = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert res == [OpenFile(3181, "jellyfin", "sde", "/hdd8/Movies/X.mkv")]


def test_scan_skips_process_without_target_mounts(tmp_path):
    _mkproc(tmp_path, 999, "1616 1615 0:50 / / rw - overlay overlay rw\n",
            [("5", 1616, "/whatever")])
    assert scan_open_files(DISKS, proc_base=str(tmp_path)) == []


def test_scan_exclude_pids(tmp_path):
    _mkproc(tmp_path, 3181, MOUNTINFO, [("20", 1848, "/hdd8/a.mkv")])
    assert scan_open_files(DISKS, proc_base=str(tmp_path),
                           exclude_pids=frozenset({3181})) == []


def test_scan_dedup_same_pid_path(tmp_path):
    _mkproc(tmp_path, 3181, MOUNTINFO,
            [("20", 1848, "/hdd8/a.mkv"), ("21", 1848, "/hdd8/a.mkv")])
    assert len(scan_open_files(DISKS, proc_base=str(tmp_path))) == 1
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_fdscan.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/fdscan.py` (substituir todo o ficheiro):
```python
"""Atribuição agnóstica ao filesystem E ao namespace via /proc/*/fd + dispositivo.

Processos em containers veem os HDD noutros caminhos (ex.: /media/HDD8TB→/hdd8),
por isso readlink de /proc/PID/fd devolve o caminho do container e o match por
prefixo de mount do host falha. A solução determina o disco por DISPOSITIVO: para
cada fd, lê-se mnt_id em /proc/PID/fdinfo/<fd> e cruza-se com /proc/PID/mountinfo
para obter o dispositivo de origem (ex.: /dev/sde1), mapeado ao disco-alvo.
Só leituras de /proc (readlink + ficheiros de texto) — não acede ao conteúdo dos
ficheiros, logo não acorda os discos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sysscope.common.config import Disk


@dataclass(frozen=True)
class OpenFile:
    pid: int
    comm: str
    disk: str
    path: str


def disk_for_source(source: str, disks: list[Disk]) -> str | None:
    """Mapeia um dispositivo de origem (ex.: /dev/sde1) ao nome do disco-alvo."""
    for d in disks:
        dev = d.device
        if source == dev or (source.startswith(dev) and source[len(dev):].isdigit()):
            return d.name
    return None


def parse_mountinfo(text: str, disks: list[Disk]) -> dict[int, str]:
    """{mount_id: nome_disco} para mounts cujo dispositivo é um disco-alvo."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if "-" not in parts:
            continue
        try:
            mount_id = int(parts[0])
            sep = parts.index("-")
            source = parts[sep + 2]
        except (ValueError, IndexError):
            continue
        disk = disk_for_source(source, disks)
        if disk is not None:
            out[mount_id] = disk
    return out


def _fd_mnt_id(fdinfo_text: str) -> int | None:
    for line in fdinfo_text.splitlines():
        if line.startswith("mnt_id:"):
            try:
                return int(line.split()[1])
            except (ValueError, IndexError):
                return None
    return None


def scan_open_files(disks: list[Disk], proc_base: str = "/proc",
                    exclude_pids: frozenset[int] = frozenset()) -> list[OpenFile]:
    out: dict[tuple[int, str], OpenFile] = {}
    base = Path(proc_base)
    try:
        pid_dirs = [d for d in base.iterdir() if d.name.isdigit()]
    except OSError:
        return []
    for pdir in pid_dirs:
        pid = int(pdir.name)
        if pid in exclude_pids:
            continue
        try:
            mount_to_disk = parse_mountinfo((pdir / "mountinfo").read_text(), disks)
        except OSError:
            continue
        if not mount_to_disk:
            continue  # o processo não vê nenhum disco-alvo
        try:
            fds = list((pdir / "fd").iterdir())
        except OSError:
            continue
        comm = None
        for fd in fds:
            try:
                mnt_id = _fd_mnt_id((pdir / "fdinfo" / fd.name).read_text())
            except OSError:
                continue
            disk = mount_to_disk.get(mnt_id) if mnt_id is not None else None
            if disk is None:
                continue
            try:
                path = os.readlink(fd)  # caminho no namespace do processo (contexto)
            except OSError:
                path = "?"
            if comm is None:
                try:
                    comm = (pdir / "comm").read_text().strip()
                except OSError:
                    comm = "?"
            out[(pid, path)] = OpenFile(pid=pid, comm=comm, disk=disk, path=path)
    return list(out.values())
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_fdscan.py -v`

- [ ] **Step 5: Suite completa** — `python3 -m pytest -q` (tudo passa; nada mais consome `fdscan`).

- [ ] **Step 6: Redeploy + verificação (crítico — para apanhar spin-ups desta noite)**
```bash
sudo rsync -a --delete sysscope /opt/sysscope/
sudo systemctl restart sysscope-collector
sleep 3
# Prova em /proc real (sem acordar HDD): que processos têm FDs nos HDD agora?
sudo python3 -c "
from sysscope.common.config import default_config
from sysscope.collector.fdscan import scan_open_files
for f in scan_open_files(default_config().disks):
    print(f.pid, f.comm, f.disk, f.path)
" | head -20
systemctl is-active sysscope-collector
```
Esperado: se algum container estiver a aceder aos HDD agora, aparece (pid/comm/disk/caminho, ex.: `... jellyfin sde /hdd8/...`). Se os discos estiverem parados, pode não haver nada nesse instante — o importante é: sem erros, serviço `active`, e o matching por device a resolver o disco. NÃO ler ficheiros dos mounts.

- [ ] **Step 7: Commit** — `fix: atribuição por dispositivo (funciona com processos em containers)`

---

### Task 2: Coletor Sistema — `sysinfo.py`

**Files:** Create `sysscope/collector/sysinfo.py`, `tests/test_sysinfo.py`

**Interfaces:**
- `read_system(clock=time.time) -> dict` com chaves: `cpu_percent` (float), `load` ([1m,5m,15m]), `mem_total`, `mem_used`, `mem_percent`, `swap_total`, `swap_used`, `uptime_seconds`, `temps` ({label: celsius}), `cpu_count`.
- Usa psutil; nunca lança (try/except → campos a 0/{} em falha).

- [ ] **Step 1: Teste (falha)** — `tests/test_sysinfo.py`:
```python
from sysscope.collector import sysinfo


def test_read_system_shape():
    d = sysinfo.read_system()
    for k in ("cpu_percent", "load", "mem_total", "mem_used", "mem_percent",
              "swap_total", "swap_used", "uptime_seconds", "temps", "cpu_count"):
        assert k in d
    assert isinstance(d["load"], list) and len(d["load"]) == 3
    assert isinstance(d["temps"], dict)
    assert d["mem_total"] > 0
    assert d["cpu_count"] >= 1
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_sysinfo.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/sysinfo.py`:
```python
"""Métricas de saúde do sistema (CPU, memória, temperaturas, uptime)."""
from __future__ import annotations

import os
import time

import psutil


def read_system(clock=time.time) -> dict:
    try:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        try:
            load = list(os.getloadavg())
        except OSError:
            load = [0.0, 0.0, 0.0]
        temps: dict[str, float] = {}
        try:
            for chip, entries in psutil.sensors_temperatures().items():
                for e in entries:
                    label = f"{chip}/{e.label}" if e.label else chip
                    if e.current is not None:
                        temps[label] = round(e.current, 1)
        except Exception:
            temps = {}
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "load": load,
            "mem_total": vm.total,
            "mem_used": vm.total - vm.available,
            "mem_percent": vm.percent,
            "swap_total": sw.total,
            "swap_used": sw.used,
            "uptime_seconds": uptime,
            "temps": temps,
            "cpu_count": psutil.cpu_count() or 1,
        }
    except Exception:
        return {"cpu_percent": 0.0, "load": [0.0, 0.0, 0.0], "mem_total": 0,
                "mem_used": 0, "mem_percent": 0.0, "swap_total": 0, "swap_used": 0,
                "uptime_seconds": 0.0, "temps": {}, "cpu_count": 1}
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_sysinfo.py -v`

- [ ] **Step 5: Commit** — `feat: coletor de métricas de sistema (sysinfo)`

---

### Task 3: Coletor Wake-ups — `wakeups.py`

**Files:** Create `sysscope/collector/wakeups.py`, `tests/test_wakeups.py`

**Interfaces:**
- `parse_timers(json_text: str) -> list[dict]` — de `systemctl list-timers -o json`; cada item `{unit, activates, next, last, left}` (next/last em segundos; micros→segundos; 0 se ausente/None).
- `read_cron(cron_paths: list[str]) -> list[dict]` — linhas de cron não-comentadas de `/etc/crontab` e `/etc/cron.d/*`; cada `{source, line}`.
- `read_rtc_wakealarm(path: str) -> int | None` — conteúdo de `/sys/class/rtc/rtc0/wakealarm` (epoch) ou None se vazio/ausente.
- `read_wakeups(runner=run_cmd) -> dict` — `{timers:[...], cron:[...], rtc_wakealarm: int|None}`; nunca lança.

- [ ] **Step 1: Teste (falha)** — `tests/test_wakeups.py`:
```python
import json
from sysscope.collector import wakeups

TIMERS = json.dumps([
    {"next": 1784770740000000, "last": 1784768940128735, "left": 1800000000,
     "unit": "phpsessionclean.timer", "activates": "phpsessionclean.service"},
    {"next": None, "last": None, "left": None,
     "unit": "x.timer", "activates": "x.service"},
])


def test_parse_timers_micros_to_seconds():
    t = wakeups.parse_timers(TIMERS)
    assert t[0]["unit"] == "phpsessionclean.timer"
    assert t[0]["next"] == 1784770740          # micros -> segundos
    assert t[0]["activates"] == "phpsessionclean.service"
    assert t[1]["next"] == 0                    # None -> 0


def test_parse_timers_bad_json():
    assert wakeups.parse_timers("nope") == []


def test_read_cron(tmp_path):
    ct = tmp_path / "crontab"
    ct.write_text("# comentário\nSHELL=/bin/sh\n0 3 * * * root /x.sh\n\n")
    res = wakeups.read_cron([str(ct), str(tmp_path / "missing")])
    lines = [r["line"] for r in res]
    assert "0 3 * * * root /x.sh" in lines
    assert "# comentário" not in lines
    assert "" not in lines


def test_read_rtc(tmp_path):
    p = tmp_path / "wakealarm"; p.write_text("1784800000\n")
    assert wakeups.read_rtc_wakealarm(str(p)) == 1784800000
    empty = tmp_path / "empty"; empty.write_text("\n")
    assert wakeups.read_rtc_wakealarm(str(empty)) is None
    assert wakeups.read_rtc_wakealarm(str(tmp_path / "none")) is None
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_wakeups.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/wakeups.py`:
```python
"""Fontes de wake-up: timers systemd, cron e RTC wakealarm."""
from __future__ import annotations

import glob
import json
import os

from sysscope.common.run import Runner, run_cmd

DEFAULT_CRON_GLOBS = ["/etc/crontab", "/etc/cron.d/*"]
DEFAULT_RTC = "/sys/class/rtc/rtc0/wakealarm"


def _us_to_s(v) -> int:
    try:
        return int(v) // 1_000_000 if v else 0
    except (TypeError, ValueError):
        return 0


def parse_timers(json_text: str) -> list[dict]:
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for t in data:
        if not isinstance(t, dict):
            continue
        out.append({
            "unit": t.get("unit", ""),
            "activates": t.get("activates", ""),
            "next": _us_to_s(t.get("next")),
            "last": _us_to_s(t.get("last")),
            "left": _us_to_s(t.get("left")),
        })
    return out


def read_cron(cron_paths: list[str]) -> list[dict]:
    out = []
    for path in cron_paths:
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" in line.split(" ")[0]:
                continue
            out.append({"source": os.path.basename(path), "line": line})
    return out


def read_rtc_wakealarm(path: str) -> int | None:
    try:
        with open(path) as f:
            txt = f.read().strip()
    except OSError:
        return None
    if not txt:
        return None
    try:
        return int(txt)
    except ValueError:
        return None


def read_wakeups(runner: Runner = run_cmd,
                 cron_globs: list[str] | None = None,
                 rtc_path: str = DEFAULT_RTC) -> dict:
    try:
        timers_txt = runner(["systemctl", "list-timers", "--all",
                             "-o", "json", "--no-pager"])
    except Exception:
        timers_txt = ""
    globs = cron_globs if cron_globs is not None else DEFAULT_CRON_GLOBS
    cron_paths: list[str] = []
    for g in globs:
        cron_paths.extend(sorted(glob.glob(g)))
    return {
        "timers": parse_timers(timers_txt),
        "cron": read_cron(cron_paths),
        "rtc_wakealarm": read_rtc_wakealarm(rtc_path),
    }
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_wakeups.py -v`

- [ ] **Step 5: Commit** — `feat: coletor de wake-ups (timers/cron/RTC)`

---

### Task 4: Coletor Processos — `procstat.py`

**Files:** Create `sysscope/collector/procstat.py`, `tests/test_procstat.py`

**Interfaces:**
- `read_top_processes(limit: int = 15) -> list[dict]` — top processos por CPU, cada `{pid, name, cpu_percent, mem_bytes, read_bytes, write_bytes}`. Usa psutil; nunca lança. `read_bytes`/`write_bytes` a 0 se indisponíveis. (Ler /proc/PID/io são contadores — não acorda discos.)

- [ ] **Step 1: Teste (falha)** — `tests/test_procstat.py`:
```python
from sysscope.collector import procstat


def test_read_top_processes_shape():
    procs = procstat.read_top_processes(limit=5)
    assert isinstance(procs, list)
    assert len(procs) <= 5
    if procs:
        p = procs[0]
        for k in ("pid", "name", "cpu_percent", "mem_bytes",
                  "read_bytes", "write_bytes"):
            assert k in p
    # ordenado por cpu desc
    cpus = [p["cpu_percent"] for p in procs]
    assert cpus == sorted(cpus, reverse=True)
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_procstat.py -v`

- [ ] **Step 3: Implementar** `sysscope/collector/procstat.py`:
```python
"""Top de processos por CPU (com memória e I/O)."""
from __future__ import annotations

import psutil


def read_top_processes(limit: int = 15) -> list[dict]:
    procs: list[dict] = []
    try:
        it = list(psutil.process_iter(["pid", "name"]))
    except Exception:
        return []
    # Primeira passagem inicializa os contadores de cpu_percent.
    for p in it:
        try:
            p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for p in it:
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_info().rss
            try:
                io = p.io_counters()
                rb, wb = io.read_bytes, io.write_bytes
            except (psutil.AccessDenied, AttributeError, NotImplementedError):
                rb = wb = 0
            procs.append({
                "pid": p.pid,
                "name": p.info["name"] or "?",
                "cpu_percent": round(cpu, 1),
                "mem_bytes": mem,
                "read_bytes": rb,
                "write_bytes": wb,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    return procs[:limit]
```
Nota: `read_top_processes` chama `cpu_percent(None)` duas vezes; entre as duas passagens o valor é ~0 na 1ª chamada (baseline). Para valores reais o coletor chama isto periodicamente (cadência lenta), por isso o valor reflete o intervalo entre polls — aceitável para um painel de contexto.

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_procstat.py -v`

- [ ] **Step 5: Commit** — `feat: coletor de top de processos`

---

### Task 5: Integração no coletor + endpoints web

**Files:** Modify `sysscope/collector/services_collector.py`, `sysscope/web/app.py`; Create `tests/test_web_phase3.py`

- [ ] **Step 1: Teste (falha)** — `tests/test_web_phase3.py`:
```python
import json
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def client(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.put_snapshot("system", 1.0, json.dumps({"cpu_percent": 12.5, "mem_total": 100}))
    db.put_snapshot("wakeups", 1.0, json.dumps({"timers": [{"unit": "a.timer"}], "cron": [], "rtc_wakealarm": None}))
    db.put_snapshot("processes", 1.0, json.dumps([{"pid": 1, "name": "init", "cpu_percent": 0.0}]))
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    return TestClient(create_app(ro, static_dir=str(tmp_path)))


def test_system(tmp_path):
    assert client(tmp_path).get("/api/system").json()["cpu_percent"] == 12.5


def test_wakeups(tmp_path):
    assert client(tmp_path).get("/api/wakeups").json()["timers"][0]["unit"] == "a.timer"


def test_processes(tmp_path):
    assert client(tmp_path).get("/api/processes").json()[0]["name"] == "init"
```

- [ ] **Step 2: Correr (falha)** — `python3 -m pytest tests/test_web_phase3.py -v`

- [ ] **Step 3: Implementar** — em `sysscope/collector/services_collector.py`, importar os novos coletores e, no fim de `poll()`, escrever os snapshots:
```python
from sysscope.collector.sysinfo import read_system
from sysscope.collector.wakeups import read_wakeups
from sysscope.collector.procstat import read_top_processes
```
e no fim de `poll()` (após o bloco de rede):
```python
        self._db.put_snapshot("system", now, json.dumps(read_system()))
        self._db.put_snapshot("wakeups", now, json.dumps(read_wakeups(self._runner)))
        self._db.put_snapshot("processes", now, json.dumps(read_top_processes()))
```
Em `sysscope/web/app.py`, acrescentar (junto dos endpoints da Fase 2):
```python
    @app.get("/api/system")
    def system() -> dict:
        snap = db.get_snapshot("system")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/wakeups")
    def wakeups_ep() -> dict:
        snap = db.get_snapshot("wakeups")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/processes")
    def processes() -> list:
        snap = db.get_snapshot("processes")
        return json.loads(snap["payload"]) if snap else []
```

- [ ] **Step 4: Correr (passa)** — `python3 -m pytest tests/test_web_phase3.py tests/test_web.py -v`

- [ ] **Step 5: Smoke test (snapshots reais)**
```bash
sudo python3 -c "
from sysscope.common.config import default_config
from sysscope.collector.services_collector import ServicesCollector
from sysscope.storage.db import Database
import time, dataclasses, json
cfg=dataclasses.replace(default_config(), db_path='/tmp/ss_p3.db')
db=Database(cfg.db_path); db.init_schema()
ServicesCollector(cfg, db, clock=time.time).poll()
print('system cpu%:', json.loads(db.get_snapshot('system')['payload'])['cpu_percent'])
print('timers:', len(json.loads(db.get_snapshot('wakeups')['payload'])['timers']))
print('top proc:', json.loads(db.get_snapshot('processes')['payload'])[0]['name'])
"
```
Esperado: imprime cpu%, nº de timers, e o processo top.

- [ ] **Step 6: Commit** — `feat: integra sistema/wake-ups/processos + endpoints web`

---

### Task 6: Painéis no frontend + polimento + redeploy final

**Files:** Modify `sysscope/web/static/{index.html,style.css,app.js}`, `install.sh`

- [ ] **Step 1: `index.html`** — acrescentar três secções após a de Rede:
```html
    <section id="system" class="panel">
      <h2>Sistema</h2>
      <div id="system-body" class="cards"></div>
    </section>
    <section id="processes" class="panel">
      <h2>Processos (top CPU)</h2>
      <table id="proc-table">
        <thead><tr><th>PID</th><th>Nome</th><th>CPU</th><th>Memória</th><th>Disco (R/W)</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
    <section id="wakeups" class="panel">
      <h2>Wake-ups</h2>
      <div id="wakeups-body" class="io"></div>
      <table id="timers-table">
        <thead><tr><th>Timer</th><th>Ativa</th><th>Próximo</th><th>Último</th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
```

- [ ] **Step 2: `style.css`** — mudar o seletor global `h3` para `#network h3` (corrige nit); acrescentar:
```css
.metric { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.metric .k { color: var(--muted); font-size: 12px; }
.metric .v { font-size: 20px; font-weight: 600; margin-top: 4px; }
#proc-table td, #timers-table td { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 3: `app.js`** — reforçar `esc()` para escapar também aspas simples e acrescentar os renders. Alterar `esc`:
```javascript
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
```
Acrescentar funções e chamá-las em `init()` (e num `setInterval` de 5s):
```javascript
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
    tr.innerHTML = `<td>${p.pid}</td><td>${esc(p.name)}</td><td>${(p.cpu_percent ?? 0).toFixed(1)}%</td>` +
      `<td>${fmtBytes(p.mem_bytes || 0)}</td><td>${fmtBytes(p.read_bytes || 0)} / ${fmtBytes(p.write_bytes || 0)}</td>`;
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
    tr.innerHTML = `<td>${esc(t.unit)}</td><td>${esc(t.activates)}</td>` +
      `<td>${fmtWhen(t.next)}</td><td>${fmtWhen(t.last)}</td>`;
    tb.appendChild(tr);
  }
}
```
E em `init()`, após `loadNetwork()`:
```javascript
  await loadSystem(); await loadProcesses(); await loadWakeups();
  setInterval(loadSystem, 5000);
  setInterval(loadProcesses, 5000);
  setInterval(loadWakeups, 15000);
```

- [ ] **Step 4: `install.sh`** — trocar `cp -r sysscope pyproject.toml "$DEST/"` por deploy que remove ficheiros obsoletos:
```bash
sudo rsync -a --delete sysscope "$DEST/"
sudo cp pyproject.toml "$DEST/"
```
(o `rsync` já está nas dependências apt.)

- [ ] **Step 5: Verificar + redeploy + confirmação final**
```bash
python3 -m pytest -q
node --check sysscope/web/static/app.js
sudo rsync -a --delete sysscope /opt/sysscope/
sudo systemctl restart sysscope-collector sysscope-web
sleep 8
for ep in system processes wakeups containers network disks settings; do
  echo -n "/api/$ep: "; curl -s "http://127.0.0.1:8787/api/$ep" | head -c 120; echo
done
curl -s http://127.0.0.1:8787/ | grep -cE "Sistema|Processos|Wake-ups"
systemctl is-active sysscope-collector sysscope-web
curl -s http://127.0.0.1:8787/api/disks | python3 -c "import sys,json;print([(x['disk'],x['power_state']) for x in json.load(sys.stdin)])"
```
Esperado: todos os endpoints devolvem JSON; a página serve as 3 novas secções; ambos os serviços `active`; HDDs em standby/unknown (não acordados). NÃO ler ficheiros dos mounts.

- [ ] **Step 6: Commit** — `feat: painéis Sistema/Processos/Wake-ups + polimento (esc, h3, rsync)`

---

## Self-Review
- Atribuição por dispositivo (containers): Task 1 (device-based, testado com fake /proc + mountinfo/fdinfo). ✔
- Painéis Sistema/Wake-ups/Processos: Tasks 2-6. ✔
- Nunca acordar discos: só /proc (incl. fdinfo/mountinfo), systemctl, psutil, /sys/rtc, cron — nada nos mounts. ✔
- Degrada sem systemctl/psutil: todos os `read_*` têm try/except → vazio. ✔
- Polimento: esc() com aspas simples, h3 scoped, install.sh rsync --delete. ✔
- Fora de âmbito (confirmado): token de auth, bpftrace, powertop. 
- bind toggle e Fases 1-2 intactos (apenas adições).
- Type consistency: `OpenFile`, `parse_mountinfo`, `disk_for_source`, `read_system/read_wakeups/read_top_processes`, snapshots "system"/"wakeups"/"processes". ✔
