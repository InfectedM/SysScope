import os
from sysscope.common.config import Disk
from sysscope.collector.fdscan import (
    OpenFile, disk_for_source, parse_mountinfo, scan_open_files,
)

DISKS = [Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
         Disk("sdb", "/dev/sdb", "/media/HDD3TB", 8, 16)]

MOUNTINFO = (
    "1616 1615 0:50 / / rw,relatime - overlay overlay rw,lowerdir=x\n"
    "1848 1616 8:65 / /hdd8 rw,relatime - fuseblk /dev/sde1 rw,user_id=0\n"
    "1850 1616 8:17 / /hdd3 rw,relatime - fuseblk /dev/sdb2 rw,user_id=0\n"
)


def test_disk_for_source_matches_partition():
    assert disk_for_source("/dev/sde1", DISKS) == "sde"
    assert disk_for_source("/dev/sde", DISKS) == "sde"
    assert disk_for_source("/dev/sdb2", DISKS) == "sdb"
    assert disk_for_source("/dev/sda1", DISKS) is None


def test_parse_mountinfo_maps_target_mounts():
    m = parse_mountinfo(MOUNTINFO, DISKS)
    assert m == {1848: "sde", 1850: "sdb"}   # overlay ignorado


def _mkproc(tmp_path, pid, mountinfo, fds):
    """fds: list of (fdname, mnt_id, target_path)."""
    p = tmp_path / str(pid); (p / "fd").mkdir(parents=True); (p / "fdinfo").mkdir()
    (p / "mountinfo").write_text(mountinfo)
    (p / "comm").write_text("jellyfin\n")
    for name, mnt_id, target in fds:
        os.symlink(target, p / "fd" / name)
        (p / "fdinfo" / name).write_text(f"pos:\t0\nflags:\t0100000\nmnt_id:\t{mnt_id}\n")


def test_scan_attributes_container_fd_by_device(tmp_path):
    # fd aponta para caminho do CONTAINER (/hdd8/...), mnt_id do mount /hdd8 (1848)
    _mkproc(tmp_path, 3181, MOUNTINFO,
            [("20", 1848, "/hdd8/Movies/X.mkv"), ("3", 1616, "/dev/null")])
    res = scan_open_files(DISKS, proc_base=str(tmp_path))
    assert res == [OpenFile(3181, "jellyfin", "sde", "/hdd8/Movies/X.mkv")]


def test_scan_skips_process_without_target_mounts(tmp_path):
    _mkproc(tmp_path, 999, "1616 1615 0:50 / / rw - overlay overlay rw\n",
            [("5", 1616, "/whatever")])
    assert scan_open_files(DISKS, proc_base=str(tmp_path)) == []


def test_scan_exclude_pids(tmp_path):
    _mkproc(tmp_path, 3181, MOUNTINFO, [("20", 1848, "/hdd8/a.mkv")])
    assert scan_open_files(DISKS, proc_base=str(tmp_path),
                           exclude_pids=frozenset({3181})) == []


def test_scan_dedup_same_pid_path(tmp_path):
    _mkproc(tmp_path, 3181, MOUNTINFO,
            [("20", 1848, "/hdd8/a.mkv"), ("21", 1848, "/hdd8/a.mkv")])
    assert len(scan_open_files(DISKS, proc_base=str(tmp_path))) == 1
