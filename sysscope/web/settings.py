"""Definições do servidor web persistidas (modo de bind localhost/LAN).

Guardado num ficheiro JSON que o servidor web (utilizador) pode escrever, já
que a BD é aberta em read-only. Fail-safe: qualquer problema ⇒ 'localhost'
(nunca expor à LAN por acidente).
"""
from __future__ import annotations

import json
import os
import socket

import psutil

DEFAULT_SETTINGS_PATH = "/var/lib/sysscope/web_settings.json"
_VALID = {"localhost", "lan"}


def read_bind_mode(path: str) -> str:
    try:
        with open(path) as f:
            mode = json.load(f).get("bind_mode")
    except (OSError, ValueError):
        return "localhost"
    return mode if mode in _VALID else "localhost"


def write_bind_mode(path: str, mode: str) -> None:
    if mode not in _VALID:
        raise ValueError(f"bind_mode inválido: {mode!r}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump({"bind_mode": mode}, f)
    os.replace(tmp, path)


def host_for_mode(mode: str) -> str:
    return "0.0.0.0" if mode == "lan" else "127.0.0.1"


def lan_ipv4_addresses() -> list[str]:
    out: list[str] = []
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.address != "127.0.0.1":
                    out.append(a.address)
    except Exception:
        return []
    return sorted(set(out))
