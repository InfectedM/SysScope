"""Parsing de /proc/diskstats e cálculo de taxas de I/O.

Campos por linha (após major/minor/nome):
  1 reads_completed  3 sectors_read   5 writes_completed  7 sectors_written
Ref: Documentation/admin-guide/iostats.rst do kernel.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiskStat:
    reads: int
    read_sectors: int
    writes: int
    write_sectors: int


@dataclass(frozen=True)
class DiskRates:
    read_iops: float
    write_iops: float
    read_bps: float
    write_bps: float
    active: bool


def parse_diskstats(text: str, names: set[str]) -> dict[str, DiskStat]:
    out: dict[str, DiskStat] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 11:
            continue
        name = parts[2]
        if name not in names:
            continue
        out[name] = DiskStat(
            reads=int(parts[3]),
            read_sectors=int(parts[5]),
            writes=int(parts[7]),
            write_sectors=int(parts[9]),
        )
    return out


def compute_rates(prev: DiskStat, curr: DiskStat, dt: float,
                  sector_size: int = 512) -> DiskRates:
    d_reads = curr.reads - prev.reads
    d_writes = curr.writes - prev.writes
    d_rsec = curr.read_sectors - prev.read_sectors
    d_wsec = curr.write_sectors - prev.write_sectors
    active = (d_reads + d_writes + d_rsec + d_wsec) > 0
    if dt <= 0:
        return DiskRates(0.0, 0.0, 0.0, 0.0, active)
    return DiskRates(
        read_iops=d_reads / dt,
        write_iops=d_writes / dt,
        read_bps=d_rsec * sector_size / dt,
        write_bps=d_wsec * sector_size / dt,
        active=active,
    )
