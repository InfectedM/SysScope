"""Resolução de PID → nome de container Docker via cgroup v2.

Linha típica de /proc/<pid>/cgroup:
  0::/system.slice/docker-<id64>.scope
"""
from __future__ import annotations

import re
from pathlib import Path

from sysscope.common.run import Runner, run_cmd

_DOCKER_RE = re.compile(r"docker-([0-9a-f]{64})\.scope")


def container_id_from_cgroup(text: str) -> str | None:
    m = _DOCKER_RE.search(text)
    return m.group(1) if m else None


class ContainerResolver:
    def __init__(self, runner: Runner = run_cmd, proc_base: str = "/proc") -> None:
        self._runner = runner
        self._proc = Path(proc_base)
        self._by_id: dict[str, str] = {}

    def refresh(self) -> None:
        try:
            out = self._runner(["docker", "ps", "--no-trunc",
                                "--format", "{{.ID}}|{{.Names}}"])
        except Exception:
            return
        mapping: dict[str, str] = {}
        for line in out.splitlines():
            if "|" not in line:
                continue
            cid, name = line.split("|", 1)
            mapping[cid.strip()] = name.strip()
        self._by_id = mapping

    def name_for_pid(self, pid: int) -> str | None:
        try:
            text = (self._proc / str(pid) / "cgroup").read_text()
        except OSError:
            return None
        cid = container_id_from_cgroup(text)
        if cid is None:
            return None
        return self._by_id.get(cid)
