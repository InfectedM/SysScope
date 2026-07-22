from sysscope.storage.db import Database


def mk(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema(); return db


def test_net_samples_latest_and_recent(tmp_path):
    db = mk(tmp_path)
    db.insert_net_sample(10.0, "eno1", 100, 200)
    db.insert_net_sample(20.0, "eno1", 300, 400)
    latest = db.latest_net_status()
    e = next(r for r in latest if r["iface"] == "eno1")
    assert e["rx_bps"] == 300 and e["tx_bps"] == 400
    assert len(db.recent_net_samples("eno1", since=15.0)) == 1


def test_snapshot_upsert(tmp_path):
    db = mk(tmp_path)
    db.put_snapshot("services", 1.0, '{"a":1}')
    db.put_snapshot("services", 2.0, '{"a":2}')
    snap = db.get_snapshot("services")
    assert snap["ts"] == 2.0 and snap["payload"] == '{"a":2}'
    assert db.get_snapshot("inexistente") is None


def test_purge_covers_net_samples(tmp_path):
    db = mk(tmp_path)
    db.insert_net_sample(10.0, "eno1", 1, 1)
    db.insert_net_sample(1000.0, "eno1", 1, 1)
    db.purge_older_than(500.0)
    assert len(db.recent_net_samples("eno1", 0.0)) == 1
