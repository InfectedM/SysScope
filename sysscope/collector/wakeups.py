"""Fontes de wake-up: timers systemd, cron e RTC wakealarm."""
from __future__ import annotations

import glob
import json
import os

from sysscope.common.run import Runner, run_cmd

DEFAULT_CRON_GLOBS = ["/etc/crontab", "/etc/cron.d/*"]
DEFAULT_RTC = "/sys/class/rtc/rtc0/wakealarm"


def _us_to_s(v) -> int:
    try:
        return int(v) // 1_000_000 if v else 0
    except (TypeError, ValueError):
        return 0


def parse_timers(json_text: str) -> list[dict]:
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for t in data:
        if not isinstance(t, dict):
            continue
        out.append({
            "unit": t.get("unit", ""),
            "activates": t.get("activates", ""),
            "next": _us_to_s(t.get("next")),
            "last": _us_to_s(t.get("last")),
            "left": _us_to_s(t.get("left")),
        })
    return out


def read_cron(cron_paths: list[str]) -> list[dict]:
    out = []
    for path in cron_paths:
        try:
            with open(path, errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" in line.split(" ")[0]:
                continue
            out.append({"source": os.path.basename(path), "line": line})
    return out


def read_rtc_wakealarm(path: str) -> int | None:
    try:
        with open(path) as f:
            txt = f.read().strip()
    except OSError:
        return None
    if not txt:
        return None
    try:
        return int(txt)
    except ValueError:
        return None


def read_wakeups(runner: Runner = run_cmd,
                 cron_globs: list[str] | None = None,
                 rtc_path: str = DEFAULT_RTC) -> dict:
    try:
        timers_txt = runner(["systemctl", "list-timers", "--all",
                             "-o", "json", "--no-pager"])
    except Exception:
        timers_txt = ""
    globs = cron_globs if cron_globs is not None else DEFAULT_CRON_GLOBS
    cron_paths: list[str] = []
    for g in globs:
        cron_paths.extend(sorted(glob.glob(g)))
    return {
        "timers": parse_timers(timers_txt),
        "cron": read_cron(cron_paths),
        "rtc_wakealarm": read_rtc_wakealarm(rtc_path),
    }
