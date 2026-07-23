"""Conversão de tamanhos legíveis (ex.: '308.9MiB') para bytes."""
from __future__ import annotations

import re

# Ordem importa: sufixos IEC (…iB) antes dos SI para o regex apanhar o mais longo.
_UNITS = {
    "b": 1,
    "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4, "pb": 1000 ** 5,
    "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4, "pib": 1024 ** 5,
}
_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-zA-Z]+)?\s*$")


def parse_size(text: str) -> float:
    m = _RE.match(text or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    unit = (m.group(2) or "b").lower()
    factor = _UNITS.get(unit)
    if factor is None:
        return 0.0
    return value * factor
