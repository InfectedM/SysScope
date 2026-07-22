"""Parsing de `ss -tunpH` (ligações de rede com processo).

Colunas típicas: Netid State Recv-Q Send-Q Local Peer [Process]
O bloco de processo tem a forma: users:(("nome",pid=123,fd=4)).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd

_PROC_RE = re.compile(r'users:\(\("(?P<proc>[^"]+)",pid=(?P<pid>\d+)')


@dataclass(frozen=True)
class Connection:
    proto: str
    state: str
    local: str
    remote: str
    process: str | None
    pid: int | None


def parse_ss(text: str) -> list[Connection]:
    out: list[Connection] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        proto, state = parts[0], parts[1]
        # Local e Peer são os dois tokens com ':' após Recv-Q/Send-Q (índices 4 e 5).
        local, remote = parts[4], parts[5]
        m = _PROC_RE.search(line)
        process = m.group("proc") if m else None
        pid = int(m.group("pid")) if m else None
        out.append(Connection(proto, state, local, remote, process, pid))
    return out


def read_connections(runner: Runner = run_cmd) -> list[Connection]:
    try:
        out = runner(["ss", "-tunpH"])
    except Exception:
        return []
    return parse_ss(out)
