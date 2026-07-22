"""Wrapper injetável de subprocess."""
from __future__ import annotations

import subprocess
from typing import Callable

Runner = Callable[[list[str]], str]


class RunError(RuntimeError):
    pass


def run_cmd(argv: list[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RunError(f"{argv[0]}: {e}") from e
    if proc.returncode != 0:
        raise RunError(f"{argv[0]} saiu com {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout
