"""Loop principal do coletor SysScope (corre como root).

O loop de sondagem lê diskstats + estado de energia para detetar spin-ups.
Ao detetar um spin-up, cria o incidente e abre a janela de captura. A
atribuição de I/O é feita por varrimento de /proc/*/fd (agnóstico ao
filesystem, funciona também com discos FUSE/NTFS onde o fatrace/fanotify
falha) sempre que há atividade num disco-alvo ou um incidente ainda aberto.
"""
from __future__ import annotations

import os
import signal
import threading
import time

from sysscope.common.config import load_config, Config
from sysscope.storage.db import Database
from sysscope.collector.power import PowerReader
from sysscope.collector.cgroup import ContainerResolver
from sysscope.collector.disk_collector import DiskCollector
from sysscope.collector.io_attribution import IoAttribution, AttributedEvent
from sysscope.collector.fdscan import scan_open_files

_stop = threading.Event()


def _read_diskstats() -> str:
    with open("/proc/diskstats") as f:
        return f.read()


def run(cfg: Config, db: Database) -> None:
    resolver = ContainerResolver()
    resolver.refresh()
    io = IoAttribution(db, window=cfg.incident_window,
                        backfill_horizon=cfg.power_interval + cfg.incident_window)

    def on_spinup(ts: float, disk: str, detection: str) -> None:
        inc = db.create_incident(ts, disk, detection)
        io.open_incident(inc, disk, ts)

    active_disks: set[str] = set()

    def on_sample(ts, disk, power_state, rates) -> None:
        db.insert_disk_sample(ts, disk, power_state, rates.read_bps,
                              rates.write_bps, rates.read_iops, rates.write_iops)
        if rates.active:
            active_disks.add(disk)

    collector = DiskCollector(
        cfg, PowerReader(), on_spinup, on_sample,
        diskstats_reader=_read_diskstats, clock=time.time,
    )

    from sysscope.collector.services_collector import ServicesCollector
    services = ServicesCollector(cfg, db, clock=time.time)
    services_countdown = 0.0

    exclude_pids = frozenset({os.getpid()})

    try:
        last_refresh = 0.0
        last_purge = 0.0
        while not _stop.is_set():
            now = time.time()
            active_disks.clear()
            collector.poll()
            services_countdown -= cfg.sample_interval
            if services_countdown <= 0:
                services.poll()
                services_countdown = cfg.services_interval
            scan_needed = bool(active_disks) or io.has_open_incidents()
            if scan_needed:
                for of in scan_open_files(cfg.disks, exclude_pids=exclude_pids):
                    io.record(AttributedEvent(
                        ts=now, disk=of.disk, pid=of.pid, comm=of.comm,
                        container=resolver.name_for_pid(of.pid),
                        op="aberto", path=of.path, source="procfd",
                    ))
            io.finalize_due(now)
            if now - last_refresh > 30:
                resolver.refresh()
                last_refresh = now
            if now - last_purge > 3600:
                db.purge_older_than(now - cfg.retention_days * 86400)
                last_purge = now
            _stop.wait(cfg.sample_interval)
    finally:
        # Persiste incidentes ainda abertos antes de terminar (SIGTERM pode
        # chegar entre um spin-up e a sua deadline de captura).
        io.flush_open()


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
