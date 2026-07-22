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
