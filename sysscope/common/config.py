"""Configuração do SysScope: discos-alvo, caminhos e intervalos."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Disk:
    name: str      # "sde"
    device: str    # "/dev/sde"
    mount: str     # "/media/HDD8TB"
    major: int
    minor: int


@dataclass(frozen=True)
class Config:
    disks: list[Disk]
    db_path: str
    web_host: str
    web_port: int
    sample_interval: float   # segundos entre amostras de diskstats
    power_interval: float    # segundos entre sondagens hdparm -C
    idle_threshold: float    # segundos sem I/O para considerar "possivelmente adormecido"
    incident_window: float   # segundos de acessos a guardar em redor de um spin-up
    retention_days: int


def default_config() -> Config:
    return Config(
        disks=[
            Disk("sdb", "/dev/sdb", "/media/HDD3TB", 8, 16),
            Disk("sdc", "/dev/sdc", "/media/HDD4TB", 8, 32),
            Disk("sdd", "/dev/sdd", "/mnt/HDD2TB", 8, 48),
            Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
        ],
        db_path="/var/lib/sysscope/sysscope.db",
        web_host="127.0.0.1",
        web_port=8787,
        sample_interval=2.0,
        power_interval=10.0,
        idle_threshold=120.0,
        incident_window=6.0,
        retention_days=14,
    )


def load_config(path: str | None = None) -> Config:
    """Carrega config de um TOML; campos ausentes usam os defaults."""
    cfg = default_config()
    if path is None or not Path(path).exists():
        return cfg
    data = tomllib.loads(Path(path).read_text())
    web = data.get("web", {})
    storage = data.get("storage", {})
    sampling = data.get("sampling", {})
    return replace(
        cfg,
        db_path=storage.get("db_path", cfg.db_path),
        web_host=web.get("host", cfg.web_host),
        web_port=web.get("port", cfg.web_port),
        sample_interval=sampling.get("sample_interval", cfg.sample_interval),
        power_interval=sampling.get("power_interval", cfg.power_interval),
        idle_threshold=sampling.get("idle_threshold", cfg.idle_threshold),
        incident_window=sampling.get("incident_window", cfg.incident_window),
        retention_days=storage.get("retention_days", cfg.retention_days),
    )
