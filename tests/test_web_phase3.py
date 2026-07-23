import json
from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app


def client(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    db.put_snapshot("system", 1.0, json.dumps({"cpu_percent": 12.5, "mem_total": 100}))
    db.put_snapshot("wakeups", 1.0, json.dumps({"timers": [{"unit": "a.timer"}], "cron": [], "rtc_wakealarm": None}))
    db.put_snapshot("processes", 1.0, json.dumps([{"pid": 1, "name": "init", "cpu_percent": 0.0}]))
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    return TestClient(create_app(ro, static_dir=str(tmp_path)))


def test_system(tmp_path):
    assert client(tmp_path).get("/api/system").json()["cpu_percent"] == 12.5


def test_wakeups(tmp_path):
    assert client(tmp_path).get("/api/wakeups").json()["timers"][0]["unit"] == "a.timer"


def test_processes(tmp_path):
    assert client(tmp_path).get("/api/processes").json()[0]["name"] == "init"
