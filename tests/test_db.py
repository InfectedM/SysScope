from sysscope.storage.db import Database


def make_db(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    return db


def test_insert_and_latest_status(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(100.0, "sde", "standby", 0, 0, 0, 0)
    db.insert_disk_sample(102.0, "sde", "active", 1000, 0, 5, 0)
    rows = db.latest_disk_status()
    sde = next(r for r in rows if r["disk"] == "sde")
    assert sde["power_state"] == "active"
    assert sde["read_bps"] == 1000


def test_incident_lifecycle(tmp_path):
    db = make_db(tmp_path)
    inc = db.create_incident(200.0, "sdc", "power")
    assert isinstance(inc, int)
    db.insert_io_event(200.1, "sdc", 4821, "bazarr", "bazarr", "open",
                       "/media/HDD4TB/x.mkv", "fatrace", inc)
    db.set_incident_culprit(inc, "bazarr (1 acesso)")
    incidents = db.list_incidents()
    assert incidents[0]["top_culprit"] == "bazarr (1 acesso)"
    events = db.incident_events(inc)
    assert events[0]["comm"] == "bazarr"
    assert events[0]["path"] == "/media/HDD4TB/x.mkv"


def test_recent_samples_filtered_by_since(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(10.0, "sdd", "active", 1, 1, 1, 1)
    db.insert_disk_sample(50.0, "sdd", "active", 2, 2, 2, 2)
    rows = db.recent_disk_samples("sdd", since=40.0)
    assert len(rows) == 1 and rows[0]["ts"] == 50.0


def test_purge_older_than(tmp_path):
    db = make_db(tmp_path)
    db.insert_disk_sample(10.0, "sde", "active", 1, 1, 1, 1)
    db.insert_disk_sample(1000.0, "sde", "active", 1, 1, 1, 1)
    removed = db.purge_older_than(500.0)
    assert removed == 1
    assert len(db.recent_disk_samples("sde", 0.0)) == 1


def test_read_only_cannot_write(tmp_path):
    p = str(tmp_path / "ro.db")
    Database(p).init_schema()
    ro = Database(p, read_only=True)
    import sqlite3
    try:
        ro.insert_disk_sample(1.0, "sde", "active", 0, 0, 0, 0)
        assert False, "escrita devia falhar em read_only"
    except sqlite3.OperationalError:
        pass
