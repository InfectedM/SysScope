import json
from dataclasses import replace
from sysscope.common.config import default_config
from sysscope.storage.db import Database
from sysscope.collector.services_collector import ServicesCollector
from sysscope.collector.fdscan import OpenFile

NETDEV1 = "  eno1: 1000 5 0 0 0 0 0 0 2000 6 0 0 0 0 0 0\n"


def fake_runner(argv):
    if argv[0] == "docker":
        return "radarr|0.1%|10MiB / 1GiB|1MB / 2MB|3MB / 4MB\n"
    if argv[0] == "systemctl":
        return json.dumps([{"unit": "x.service", "active": "active", "sub": "running", "description": ""}])
    if argv[0] == "ss":
        return 'tcp ESTAB 0 0 1.2.3.4:80 5.6.7.8:9 users:(("radarr",pid=1,fd=2))\n'
    raise RuntimeError("desconhecido")


def fake_scan(disks, exclude_pids=frozenset()):
    return [
        OpenFile(pid=100, comm="jellyfin", disk="sde", path="/hdd8/a.mkv"),
        OpenFile(pid=100, comm="jellyfin", disk="sde", path="/hdd8/b.mkv"),
        OpenFile(pid=200, comm="sonarr", disk="sdc", path="/hdd4/c.mkv"),
    ]


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def make(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    cfg = replace(default_config(), db_path=str(tmp_path / "t.db"))
    clock = Clock()
    sc = ServicesCollector(cfg, db, clock=clock, runner=fake_runner,
                           net_reader=lambda: NETDEV1, scan_fn=fake_scan)
    return db, sc, cfg


def test_disk_info_snapshot(tmp_path):
    db, sc, cfg = make(tmp_path)
    sc.poll()
    info = json.loads(db.get_snapshot("disk_info")["payload"])

    sde_cfg = next(d for d in cfg.disks if d.name == "sde")
    assert info["sde"]["mount"] == sde_cfg.mount
    assert info["sde"]["device"] == sde_cfg.device
    assert info["sde"]["users"] == [{"name": "jellyfin", "files": 2}]

    assert info["sdc"]["users"][0]["name"] == "sonarr"

    # disco sem utilizadores tem lista vazia
    no_user_disk = next(d for d in cfg.disks if d.name not in ("sde", "sdc"))
    assert info[no_user_disk.name]["users"] == []
