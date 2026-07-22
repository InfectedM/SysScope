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


def _fatrace_loop(proc: subprocess.Popen, cfg: Config, io: IoAttribution,
                   resolver: ContainerResolver) -> None:
    """Lê o stream do fatrace e regista acessos aos discos-alvo.

    O `proc` é criado e terminado por `run()`, para que o encerramento não
    dependa de uma nova linha chegar a este iterador (que pode bloquear
    indefinidamente num stream fatrace inativo).
    """
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if _stop.is_set():
                break
            try:
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
            except Exception:
                # Não deixar um erro numa linha isolada matar a thread inteira.
                continue
    finally:
        # Garante que nunca ficamos com o processo fatrace órfão, mesmo que
        # o loop acima rebente com uma exceção não prevista.
        if proc.poll() is None:
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

    fatrace_proc = subprocess.Popen(
        ["fatrace", "--timestamp"], stdout=subprocess.PIPE, text=True,
        bufsize=1,
    )
    ft = threading.Thread(
        target=_fatrace_loop, args=(fatrace_proc, cfg, io, resolver), daemon=True,
    )
    ft.start()

    try:
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
    finally:
        # `_stop` já está definido; terminamos o fatrace explicitamente para
        # desbloquear a thread caso esta esteja presa num stream inativo.
        if fatrace_proc.poll() is None:
            fatrace_proc.terminate()
        try:
            fatrace_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            fatrace_proc.kill()
            fatrace_proc.wait()
        ft.join(timeout=2)


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
