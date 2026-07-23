import json
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def client(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.put_snapshot("disk_info", 1.0, json.dumps({
        "sde": {"mount": "/media/HDD8TB", "device": "/dev/sde",
                "users": [{"name": "jellyfin", "files": 2}]},
    }))
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    return TestClient(create_app(ro, static_dir=str(tmp_path)))


def test_disks_info(tmp_path):
    body = client(tmp_path).get("/api/disks/info").json()
    assert body["sde"]["mount"] == "/media/HDD8TB"
    assert body["sde"]["device"] == "/dev/sde"
    assert body["sde"]["users"] == [{"name": "jellyfin", "files": 2}]
