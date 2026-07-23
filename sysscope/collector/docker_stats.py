"""Parsing de `docker stats --no-stream` por container."""
from __future__ import annotations

from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd
from sysscope.common.sizes import parse_size

_FORMAT = "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}"


@dataclass(frozen=True)
class ContainerStat:
    name: str
    cpu_pct: float
    mem_used: float
    mem_limit: float
    net_rx: float
    net_tx: float
    blk_read: float
    blk_write: float


def _pair(text: str) -> tuple[float, float]:
    left, _, right = text.partition("/")
    return parse_size(left.strip()), parse_size(right.strip())


def parse_docker_stats(text: str) -> list[ContainerStat]:
    out: list[ContainerStat] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        name, cpu, mem, net, blk = parts
        try:
            cpu_pct = float(cpu.strip().rstrip("%"))
        except ValueError:
            continue
        mem_used, mem_limit = _pair(mem)
        net_rx, net_tx = _pair(net)
        blk_read, blk_write = _pair(blk)
        out.append(ContainerStat(name.strip(), cpu_pct, mem_used, mem_limit,
                                 net_rx, net_tx, blk_read, blk_write))
    return out


def read_container_stats(runner: Runner = run_cmd) -> list[ContainerStat]:
    try:
        out = runner(["docker", "stats", "--no-stream", "--format", _FORMAT])
    except Exception:
        return []
    return parse_docker_stats(out)
