import json
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def client(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.put_snapshot("services", 1.0, json.dumps({"total": 5, "active": 4, "failed": ["z.service"], "counts": {}}))
    db.put_snapshot("containers", 1.0, json.dumps([{"name": "radarr", "cpu_pct": 0.1}]))
    db.put_snapshot("connections", 1.0, json.dumps([{"proto": "tcp", "process": "sonarr"}]))
    db.insert_net_sample(1.0, "eno1", 100, 200)
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    return TestClient(create_app(ro, static_dir=str(tmp_path)))


def test_services(tmp_path):
    r = client(tmp_path).get("/api/services")
    assert r.status_code == 200 and r.json()["failed"] == ["z.service"]


def test_containers(tmp_path):
    r = client(tmp_path).get("/api/containers")
    assert r.json()[0]["name"] == "radarr"


def test_network(tmp_path):
    r = client(tmp_path).get("/api/network")
    body = r.json()
    assert body["interfaces"][0]["iface"] == "eno1"
    assert body["connections"][0]["process"] == "sonarr"


def test_network_samples(tmp_path):
    r = client(tmp_path).get("/api/network/samples?iface=eno1&since=0")
    assert len(r.json()) == 1
