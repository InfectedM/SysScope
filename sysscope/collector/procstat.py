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
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
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
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            continue
    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    return procs[:limit]
