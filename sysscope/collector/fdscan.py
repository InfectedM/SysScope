"""Atribuição agnóstica ao filesystem via varrimento de /proc/*/fd.

Funciona com FUSE/NTFS (onde o fatrace/fanotify falha). Usa apenas os.readlink
nos symlinks de /proc/<pid>/fd, que NÃO acede ao conteúdo dos ficheiros e por
isso não acorda os discos.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from sysscope.common.config import Disk
from sysscope.collector.fatrace import event_disk


@dataclass(frozen=True)
class OpenFile:
    pid: int
    comm: str
    disk: str
    path: str


def scan_open_files(disks: list[Disk], proc_base: str = "/proc",
                    exclude_pids: frozenset[int] = frozenset()) -> list[OpenFile]:
    """Devolve ficheiros abertos por processos que caem nos mounts dos discos-alvo.

    Deduplica por (pid, path). Ignora fds ilegíveis e PIDs em exclude_pids.
    """
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
        fddir = pdir / "fd"
        try:
            fds = list(fddir.iterdir())
        except OSError:
            continue  # processo desapareceu ou sem permissão
        comm = None
        for fd in fds:
            try:
                target = os.readlink(fd)  # não acede ao conteúdo -> não acorda o disco
            except OSError:
                continue
            disk = event_disk(target, disks)
            if disk is None:
                continue
            if comm is None:
                try:
                    comm = (pdir / "comm").read_text().strip()
                except OSError:
                    comm = "?"
            out[(pid, target)] = OpenFile(pid=pid, comm=comm, disk=disk, path=target)
    return list(out.values())
