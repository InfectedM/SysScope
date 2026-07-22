"""Parsing do stream do fatrace.

Formato de linha: `comm(pid): <TIPOS> <path>`
Tipos fanotify: O=open, R=read, W=write, C=close, D=delete, +=create.
Corremos `fatrace` global e filtramos por prefixo de mount.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sysscope.common.config import Disk

_LINE_RE = re.compile(r"^(?P<comm>.+)\((?P<pid>\d+)\): (?P<types>[A-Z+<>]+) (?P<path>/.*)$")


@dataclass(frozen=True)
class FatraceEvent:
    comm: str
    pid: int
    types: str
    path: str


def parse_fatrace_line(line: str) -> FatraceEvent | None:
    m = _LINE_RE.match(line.rstrip("\n"))
    if not m:
        return None
    return FatraceEvent(
        comm=m.group("comm"),
        pid=int(m.group("pid")),
        types=m.group("types"),
        path=m.group("path"),
    )


def event_disk(path: str, disks: list[Disk]) -> str | None:
    best: str | None = None
    best_len = -1
    for d in disks:
        if path == d.mount or path.startswith(d.mount + "/"):
            if len(d.mount) > best_len:
                best, best_len = d.name, len(d.mount)
    return best


def op_from_types(types: str) -> str:
    if "W" in types:
        return "write"
    if "R" in types:
        return "read"
    if "O" in types:
        return "open"
    return "other"
