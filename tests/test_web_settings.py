from fastapi.testclient import TestClient
from sysscope.storage.db import Database
from sysscope.web.app import create_app
from sysscope.web import settings as s


def mk(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    calls = []
    app = create_app(ro, static_dir=str(tmp_path),
                     settings_path=str(tmp_path / "web_settings.json"),
                     restart_fn=lambda: calls.append(1))
    return TestClient(app), calls, str(tmp_path / "web_settings.json")


def test_get_settings_default(tmp_path):
    c, _, _ = mk(tmp_path)
    body = c.get("/api/settings").json()
    assert body["bind_mode"] == "localhost"
    assert body["port"] == 8787
    assert isinstance(body["lan_urls"], list)


def test_post_bind_lan_writes_and_restarts(tmp_path):
    c, calls, path = mk(tmp_path)
    r = c.post("/api/settings/bind", json={"bind_mode": "lan"})
    assert r.status_code == 200 and r.json()["bind_mode"] == "lan"
    assert calls == [1]                       # restart agendado
    assert s.read_bind_mode(path) == "lan"    # persistido


def test_post_bind_invalid_is_400(tmp_path):
    c, calls, _ = mk(tmp_path)
    r = c.post("/api/settings/bind", json={"bind_mode": "wan"})
    assert r.status_code == 400
    assert calls == []
