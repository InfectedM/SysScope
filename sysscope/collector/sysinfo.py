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
