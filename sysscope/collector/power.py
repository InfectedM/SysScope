"""Leitura de estado de energia dos discos, sem os acordar.

`hdparm -C` usa o comando ATA CHECK POWER MODE (standby-safe). Em bridges USB
que não suportam SAT passthrough, devolve 'unknown' e o coletor recorre à
inferência por atividade.
"""
from __future__ import annotations

from sysscope.common.run import Runner, run_cmd

_SPUN_DOWN = {"standby", "sleeping"}


def parse_hdparm_c(output: str) -> str:
    low = output.lower()
    if "sleeping" in low:
        return "sleeping"
    if "standby" in low:
        return "standby"
    if "active" in low or "idle" in low:
        return "active"
    return "unknown"


def is_spun_down(state: str) -> bool:
    return state in _SPUN_DOWN


class PowerReader:
    def __init__(self, runner: Runner = run_cmd) -> None:
        self._runner = runner

    def read(self, device: str) -> str:
        try:
            out = self._runner(["hdparm", "-C", device])
        except Exception:
            return "unknown"
        return parse_hdparm_c(out)
