from sysscope.common.config import Disk
from sysscope.collector.fatrace import (
    FatraceEvent, parse_fatrace_line, event_disk, op_from_types,
)

DISKS = [
    Disk("sde", "/dev/sde", "/media/HDD8TB", 8, 64),
    Disk("sdd", "/dev/sdd", "/mnt/HDD2TB", 8, 48),
]


def test_parse_basic_line():
    ev = parse_fatrace_line("jellyfin(4821): R /media/HDD8TB/Movies/X.mkv")
    assert ev == FatraceEvent("jellyfin", 4821, "R", "/media/HDD8TB/Movies/X.mkv")


def test_parse_comm_with_spaces():
    ev = parse_fatrace_line("Media Server(1200): RO /mnt/HDD2TB/a b.txt")
    assert ev.comm == "Media Server"
    assert ev.pid == 1200
    assert ev.path == "/mnt/HDD2TB/a b.txt"


def test_parse_non_matching_returns_none():
    assert parse_fatrace_line("garbage line") is None
    assert parse_fatrace_line("") is None


def test_event_disk_matches_mount():
    assert event_disk("/media/HDD8TB/x", DISKS) == "sde"
    assert event_disk("/mnt/HDD2TB/y", DISKS) == "sdd"
    assert event_disk("/home/user/z", DISKS) is None


def test_op_from_types():
    assert op_from_types("R") == "read"
    assert op_from_types("W") == "write"
    assert op_from_types("RO") == "read"
    assert op_from_types("O") == "open"
    assert op_from_types("C") == "other"
