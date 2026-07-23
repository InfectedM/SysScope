"""Atribuição agnóstica ao filesystem E ao namespace via /proc/*/fd + dispositivo.

Processos em containers veem os HDD noutros caminhos (ex.: /media/HDD8TB→/hdd8),
por isso readlink de /proc/PID/fd devolve o caminho do container e o match por
prefixo de mount do host falha. A solução determina o disco por DISPOSITIVO: para
cada fd, lê-se mnt_id em /proc/PID/fdinfo/<fd> e cruza-se com /proc/PID/mountinfo
para obter o dispositivo de origem (ex.: /dev/sde1), mapeado ao disco-alvo.
Só leituras de /proc (readlink + ficheiros de texto) — não acede ao conteúdo dos
ficheiros, logo não acorda os discos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sysscope.common.config import Disk


@dataclass(frozen=True)
class OpenFile:
    pid: int
    comm: str
    disk: str
    path: str


def disk_for_source(source: str, disks: list[Disk]) -> str | None:
    """Mapeia um dispositivo de origem (ex.: /dev/sde1) ao nome do disco-alvo."""
    for d in disks:
        dev = d.device
        if source == dev or (source.startswith(dev) and source[len(dev):].isdigit()):
            return d.name
    return None


def parse_mountinfo(text: str, disks: list[Disk]) -> dict[int, str]:
    """{mount_id: nome_disco} para mounts cujo dispositivo é um disco-alvo."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if "-" not in parts:
            continue
        try:
            mount_id = int(parts[0])
            sep = parts.index("-")
            source = parts[sep + 2]
        except (ValueError, IndexError):
            continue
        disk = disk_for_source(source, disks)
        if disk is not None:
            out[mount_id] = disk
    return out


def _fd_mnt_id(fdinfo_text: str) -> int | None:
    for line in fdinfo_text.splitlines():
        if line.startswith("mnt_id:"):
            try:
                return int(line.split()[1])
            except (ValueError, IndexError):
                return None
    return None


def scan_open_files(disks: list[Disk], proc_base: str = "/proc",
                    exclude_pids: frozenset[int] = frozenset()) -> list[OpenFile]:
    out: dict[tuple[int, str], OpenFile] = {}
    base = Path(proc_base)
    try:
        pid_dirs = [d for d in base.iterdir() if d.name.isdigit()]
    except OSError:
        return []
    for pdir in pid_dirs:
        pid = int(pdir.name)
        if pid in exclude_pids:
            continue
        try:
            mount_to_disk = parse_mountinfo((pdir / "mountinfo").read_text(), disks)
        except OSError:
            continue
        if not mount_to_disk:
            continue  # o processo não vê nenhum disco-alvo
        try:
            fds = list((pdir / "fd").iterdir())
        except OSError:
            continue
        comm = None
        for fd in fds:
            try:
                mnt_id = _fd_mnt_id((pdir / "fdinfo" / fd.name).read_text())
            except OSError:
                continue
            disk = mount_to_disk.get(mnt_id) if mnt_id is not None else None
            if disk is None:
                continue
            try:
                path = os.readlink(fd)  # caminho no namespace do processo (contexto)
            except OSError:
                path = "?"
            if comm is None:
                try:
                    comm = (pdir / "comm").read_text().strip()
                except OSError:
                    comm = "?"
            out[(pid, path)] = OpenFile(pid=pid, comm=comm, disk=disk, path=path)
    return list(out.values())
