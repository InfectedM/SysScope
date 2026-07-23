"""Deteção de spin-up por atividade de I/O (independente do hdparm).

Os HDD são USB e o `hdparm -C` não é fiável (reporta 'standby' mesmo com o disco
a ler), por isso a deteção usa apenas /proc/diskstats: quando um disco passa de
inativo (sem I/O há >= idle_threshold) para ativo, considera-se um spin-up. O
estado apresentado deriva da atividade real.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sysscope.common.config import Config
from sysscope.collector.diskstats import (
    DiskStat, parse_diskstats, compute_rates, DiskRates,
)

# Janela (s) em que um disco recentemente ativo continua a mostrar-se "ativo",
# para evitar oscilação durante leituras em rajada (ex.: streaming).
_DISPLAY_RECENT = 20.0


@dataclass
class _DiskState:
    prev_stat: DiskStat | None = None
    prev_ts: float | None = None
    last_active_ts: float | None = None
    seen: bool = False


class DiskCollector:
    def __init__(self, config: Config,
                 on_spinup: Callable[[float, str, str], None],
                 on_sample: Callable[[float, str, str, DiskRates], None],
                 diskstats_reader: Callable[[], str],
                 clock: Callable[[], float]) -> None:
        self._cfg = config
        self._on_spinup = on_spinup
        self._on_sample = on_sample
        self._read_diskstats = diskstats_reader
        self._clock = clock
        self._names = {d.name for d in config.disks}
        self._state: dict[str, _DiskState] = {n: _DiskState() for n in self._names}

    def poll(self) -> None:
        now = self._clock()
        stats = parse_diskstats(self._read_diskstats(), self._names)
        for name, st in self._state.items():
            curr = stats.get(name)
            if curr is None:
                continue

            if st.prev_stat is not None and st.prev_ts is not None:
                rates = compute_rates(st.prev_stat, curr, now - st.prev_ts)
            else:
                rates = DiskRates(0, 0, 0, 0, False)

            # Deteção de spin-up: transição inativo -> ativo (não dispara no arranque).
            if not st.seen:
                st.seen = True
                st.last_active_ts = now
            elif (rates.active and st.last_active_ts is not None
                    and (now - st.last_active_ts) >= self._cfg.idle_threshold):
                self._on_spinup(now, name, "atividade")

            if rates.active:
                st.last_active_ts = now

            recent = (st.last_active_ts is not None
                      and (now - st.last_active_ts) < _DISPLAY_RECENT)
            state = "active" if recent else "standby"

            self._on_sample(now, name, state, rates)
            st.prev_stat = curr
            st.prev_ts = now
