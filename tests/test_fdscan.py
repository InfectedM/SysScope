import os

from sysscope.common.config import Disk
from sysscope.collector.fdscan import OpenFile, scan_open_files

DISKS = [
    Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
    Disk("sdd", "/dev/sdd", "/mnt/HDD2TB", 8, 48),
]


def _make_pid(proc_base, pid, comm, fd_targets):
    """Cria um pid falso em proc_base com comm e fd/<n> -> symlinks para fd_targets."""
    pdir = proc_base / str(pid)
    pdir.mkdir()
    (pdir / "comm").write_text(comm + "\n")
    fddir = pdir / "fd"
    fddir.mkdir()
    for i, target in enumerate(fd_targets):
        os.symlink(target, fddir / str(i))


def test_finds_files_under_target_mount(tmp_path):
    _make_pid(tmp_path, 4821, "jellyfin", ["/media/HDD8TB/Movies/X.mkv"])
    result = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert result == [
        OpenFile(pid=4821, comm="jellyfin", disk="sde",
                  path="/media/HDD8TB/Movies/X.mkv")
    ]


def test_ignores_paths_outside_all_mounts(tmp_path):
    _make_pid(tmp_path, 100, "bash", ["/home/user/foo.txt", "/dev/null"])
    result = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert result == []


def test_exclude_pids_filters_pid(tmp_path):
    _make_pid(tmp_path, 4821, "jellyfin", ["/media/HDD8TB/Movies/X.mkv"])
    result = scan_open_files(DISKS, proc_base=str(tmp_path),
                              exclude_pids=frozenset({4821}))
    assert result == []


def test_broken_symlink_and_unreadable_fd_dir_skip_gracefully(tmp_path):
    # pid com symlink partido (target inexistente é permitido por os.symlink,
    # mas aqui simulamos um fd cujo readlink falha removendo o link depois de
    # o criar não é fácil; em vez disso testamos que um alvo "estranho" sem
    # ficheiro real não rebenta, pois readlink nunca acede ao conteúdo).
    _make_pid(tmp_path, 200, "ghost", ["/media/HDD8TB/does/not/exist.mkv"])

    # pid sem diretório fd/ (processo desapareceu entre listdir e leitura)
    pdir_no_fd = tmp_path / "300"
    pdir_no_fd.mkdir()
    (pdir_no_fd / "comm").write_text("gone\n")
    # sem fd/ dir -> iterdir deve falhar com OSError e ser ignorado

    result = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert result == [
        OpenFile(pid=200, comm="ghost", disk="sde",
                  path="/media/HDD8TB/does/not/exist.mkv")
    ]


def test_dedup_by_pid_and_path(tmp_path):
    # dois fds diferentes do mesmo pid apontando para o mesmo path -> 1 resultado
    pdir = tmp_path / "500"
    pdir.mkdir()
    (pdir / "comm").write_text("bazarr\n")
    fddir = pdir / "fd"
    fddir.mkdir()
    os.symlink("/media/HDD8TB/Movies/dup.mkv", fddir / "3")
    os.symlink("/media/HDD8TB/Movies/dup.mkv", fddir / "7")
    result = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert result == [
        OpenFile(pid=500, comm="bazarr", disk="sde",
                  path="/media/HDD8TB/Movies/dup.mkv")
    ]


def test_non_digit_dirs_ignored(tmp_path):
    (tmp_path / "self").mkdir()
    (tmp_path / "net").mkdir()
    result = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert result == []
