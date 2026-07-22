import json
from dataclasses import replace
from sysscope.common.config import default_config
from sysscope.storage.db import Database
from sysscope.collector.services_collector import ServicesCollector

NETDEV1 = "  eno1: 1000 5 0 0 0 0 0 0 2000 6 0 0 0 0 0 0\n"
NETDEV2 = "  eno1: 3000 5 0 0 0 0 0 0 6000 6 0 0 0 0 0 0\n"


def fake_runner(argv):
    if argv[0] == "docker":
        return "radarr|0.1%|10MiB / 1GiB|1MB / 2MB|3MB / 4MB\n"
    if argv[0] == "systemctl":
        return json.dumps([{"unit": "x.service", "active": "active", "sub": "running", "description": ""}])
    if argv[0] == "ss":
        return 'tcp ESTAB 0 0 1.2.3.4:80 5.6.7.8:9 users:(("radarr",pid=1,fd=2))\n'
    raise RuntimeError("desconhecido")


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def make(tmp_path, netdev_reader):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    cfg = replace(default_config(), db_path=str(tmp_path / "t.db"))
    clock = Clock()
    sc = ServicesCollector(cfg, db, clock=clock, runner=fake_runner,
                           net_reader=netdev_reader)
    return db, sc, clock


def test_snapshots_written(tmp_path):
    db, sc, clock = make(tmp_path, lambda: NETDEV1)
    sc.poll()
    assert json.loads(db.get_snapshot("containers")["payload"])[0]["name"] == "radarr"
    assert db.get_snapshot("services")["payload"]  # non-empty
    assert json.loads(db.get_snapshot("connections")["payload"])[0]["process"] == "radarr"


def test_net_rates_across_two_polls(tmp_path):
    readers = iter([NETDEV1, NETDEV2])
    db, sc, clock = make(tmp_path, lambda: next(readers))
    sc.poll()                 # baseline
    clock.t += 2.0
    sc.poll()                 # (3000-1000)/2 = 1000 rx_bps
    e = next(r for r in db.latest_net_status() if r["iface"] == "eno1")
    assert e["rx_bps"] == 1000.0 and e["tx_bps"] == 2000.0
