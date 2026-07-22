from sysscope.collector.diskstats import (
    DiskStat, parse_diskstats, compute_rates,
)

SAMPLE = (
    "   8      16 sdb 156217 4110 35707470 759161 9560 2325778 18682704 125081 0 605244 884242 0 0 0 0 0 0\n"
    "   8      64 sde 734588 14168 177605984 1125714 56817 11179124 89887528 327691 0 987104 1453405 0 0 0 0 0 0\n"
    "   7       0 loop0 0 0 0 0 0 0 0 0 0 0 0\n"
)


def test_parse_selects_named_disks():
    stats = parse_diskstats(SAMPLE, {"sdb", "sde"})
    assert set(stats) == {"sdb", "sde"}
    assert stats["sde"].reads == 734588
    assert stats["sde"].read_sectors == 177605984
    assert stats["sde"].writes == 56817
    assert stats["sde"].write_sectors == 89887528


def test_parse_ignores_unnamed():
    stats = parse_diskstats(SAMPLE, {"sde"})
    assert set(stats) == {"sde"}


def test_compute_rates_basic():
    prev = DiskStat(reads=100, read_sectors=1000, writes=10, write_sectors=200)
    curr = DiskStat(reads=110, read_sectors=1200, writes=10, write_sectors=200)
    r = compute_rates(prev, curr, dt=2.0, sector_size=512)
    assert r.read_iops == 5.0            # 10 reads / 2s
    assert r.read_bps == 200 * 512 / 2.0  # 200 setores * 512 / 2s
    assert r.write_iops == 0.0
    assert r.active is True


def test_compute_rates_idle_is_inactive():
    s = DiskStat(reads=5, read_sectors=50, writes=5, write_sectors=50)
    r = compute_rates(s, s, dt=2.0)
    assert r.active is False
    assert r.read_bps == 0.0


def test_compute_rates_zero_dt_is_safe():
    prev = DiskStat(1, 1, 1, 1)
    curr = DiskStat(2, 2, 2, 2)
    r = compute_rates(prev, curr, dt=0.0)
    assert r.read_bps == 0.0 and r.active is True
