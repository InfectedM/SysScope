"""Cadência lenta: serviços (systemd+docker), ligações e throughput de rede."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Callable

from sysscope.common.config import Config
from sysscope.common.run import Runner, run_cmd
from sysscope.storage.db import Database
from sysscope.collector.docker_stats import read_container_stats
from sysscope.collector.systemd_units import read_units, summarize
from sysscope.collector.connections import read_connections
from sysscope.collector.netdev import parse_net_dev, net_rates, NetStat
from sysscope.collector.sysinfo import read_system
from sysscope.collector.wakeups import read_wakeups
from sysscope.collector.procstat import read_top_processes
from sysscope.collector.fdscan import scan_open_files
from sysscope.collector.cgroup import ContainerResolver


def _read_net_dev() -> str:
    with open("/proc/net/dev") as f:
        return f.read()


class ServicesCollector:
    def __init__(self, config: Config, db: Database,
                 clock: Callable[[], float],
                 runner: Runner = run_cmd,
                 net_reader: Callable[[], str] = _read_net_dev,
                 scan_fn=scan_open_files) -> None:
        self._cfg = config
        self._db = db
        self._clock = clock
        self._runner = runner
        self._net_reader = net_reader
        self._scan_fn = scan_fn
        self._resolver = ContainerResolver(runner)
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

        self._db.put_snapshot("system", now, json.dumps(read_system()))
        self._db.put_snapshot("wakeups", now, json.dumps(read_wakeups(self._runner)))
        self._db.put_snapshot("processes", now, json.dumps(read_top_processes()))

        # Quem está a usar cada disco agora (FDs abertos) + info de mount.
        self._resolver.refresh()
        users_by_disk: dict[str, dict[str, int]] = {}
        for of in self._scan_fn(self._cfg.disks, exclude_pids=frozenset({os.getpid()})):
            name = self._resolver.name_for_pid(of.pid) or of.comm
            users_by_disk.setdefault(of.disk, {})
            users_by_disk[of.disk][name] = users_by_disk[of.disk].get(name, 0) + 1
        info: dict[str, dict] = {}
        for d in self._cfg.disks:
            users = [{"name": n, "files": c}
                     for n, c in sorted(users_by_disk.get(d.name, {}).items(),
                                        key=lambda kv: -kv[1])]
            info[d.name] = {"mount": d.mount, "device": d.device, "users": users}
        self._db.put_snapshot("disk_info", now, json.dumps(info))
