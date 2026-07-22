"""Flight recorder: correlaciona acessos a ficheiros com incidentes de spin-up.

Mantém um buffer curto de eventos recentes (para backfill de acessos que
precedem imediatamente o spin-up) e, para cada incidente aberto, acumula os
acessos ao mesmo disco até `window` segundos depois. Ao expirar, persiste os
eventos e calcula o culpado principal.

O `backfill_horizon` controla até quando um evento antigo ainda é elegível
para backfill num novo incidente: como a deteção baseada em energia só
confirma o spin-up até `power_interval` segundos depois do acesso real que
acordou o disco, um horizonte igual apenas a `window` (a janela de captura
pós-deadline) perderia o culpado nesse caso — o evento já teria sido podado
do buffer antes do incidente abrir. Por omissão `backfill_horizon == window`
(comportamento anterior); o chamador deve passar
`power_interval + incident_window` para cobrir a latência de deteção.
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
    def __init__(self, db, window: float, backfill_horizon: float | None = None) -> None:
        self._db = db
        self._window = window
        self._backfill_horizon = backfill_horizon if backfill_horizon is not None else window
        self._recent: deque[AttributedEvent] = deque()
        self._open: list[_OpenIncident] = []

    def record(self, ev: AttributedEvent) -> None:
        self._recent.append(ev)
        cutoff = ev.ts - self._backfill_horizon
        while self._recent and self._recent[0].ts < cutoff:
            self._recent.popleft()
        for inc in self._open:
            if ev.disk == inc.disk and ev.ts <= inc.deadline:
                inc.events.append(ev)

    def open_incident(self, incident_id: int, disk: str, ts: float) -> None:
        backfill = [e for e in self._recent
                    if e.disk == disk and e.ts >= ts - self._backfill_horizon]
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

    def flush_open(self) -> None:
        """Finaliza todos os incidentes ainda abertos (usado no encerramento)."""
        self.finalize_due(float("inf"))
