from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def seeded_db(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.insert_disk_sample(100.0, "sde", "active", 1000, 0, 5, 0)
    inc = db.create_incident(100.0, "sde", "power")
    db.insert_io_event(100.1, "sde", 1, "bazarr", "bazarr", "read",
                       "/media/HDD8TB/x", "fatrace", inc)
    db.set_incident_culprit(inc, "bazarr (1 acesso)")
    return db, inc


def client(tmp_path):
    db, inc = seeded_db(tmp_path)
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    app = create_app(ro, static_dir=str(tmp_path))
    return TestClient(app), inc


def test_disks_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/disks")
    assert r.status_code == 200
    assert r.json()[0]["disk"] == "sde"
    assert r.json()[0]["power_state"] == "active"


def test_incidents_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/incidents")
    assert r.status_code == 200
    assert r.json()[0]["top_culprit"] == "bazarr (1 acesso)"


def test_incident_detail(tmp_path):
    c, inc = client(tmp_path)
    r = c.get(f"/api/incidents/{inc}")
    assert r.status_code == 200
    body = r.json()
    assert body["incident"]["disk"] == "sde"
    assert body["events"][0]["comm"] == "bazarr"


def test_samples_endpoint(tmp_path):
    c, _ = client(tmp_path)
    r = c.get("/api/disks/sde/samples?since=0")
    assert r.status_code == 200
    assert len(r.json()) == 1
