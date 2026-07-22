"""Parsing de `systemctl list-units --type=service --all -o json`."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from sysscope.common.run import Runner, run_cmd


@dataclass(frozen=True)
class Unit:
    name: str
    active: str
    sub: str
    description: str


def parse_units(json_text: str) -> list[Unit]:
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[Unit] = []
    for u in data:
        try:
            out.append(Unit(u["unit"], u["active"], u["sub"], u.get("description", "")))
        except (KeyError, TypeError):
            continue
    return out


def summarize(units: list[Unit]) -> dict:
    counts = Counter(u.active for u in units)
    return {
        "total": len(units),
        "active": counts.get("active", 0),
        "failed": [u.name for u in units if u.active == "failed"],
        "counts": dict(counts),
    }


def read_units(runner: Runner = run_cmd) -> list[Unit]:
    try:
        out = runner(["systemctl", "list-units", "--type=service", "--all",
                      "-o", "json", "--no-pager"])
    except Exception:
        return []
    return parse_units(out)
