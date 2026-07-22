"""Parsing de /proc/net/dev e cálculo de throughput por interface.

Formato por linha: `iface: rx_bytes rx_packets ... (8 campos) tx_bytes ...`
Campo 0 (após ':') = rx_bytes; campo 8 = tx_bytes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetStat:
    rx_bytes: int
    tx_bytes: int


def parse_net_dev(text: str, skip_loopback: bool = True) -> dict[str, NetStat]:
    out: dict[str, NetStat] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if skip_loopback and name == "lo":
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            out[name] = NetStat(rx_bytes=int(parts[0]), tx_bytes=int(parts[8]))
        except ValueError:
            continue
    return out


def net_rates(prev: NetStat, curr: NetStat, dt: float) -> tuple[float, float]:
    if dt <= 0:
        return (0.0, 0.0)
    return ((curr.rx_bytes - prev.rx_bytes) / dt,
            (curr.tx_bytes - prev.tx_bytes) / dt)
