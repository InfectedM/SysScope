from fastapi.testclient import TestClient

from sysscope.storage.db import Database, culprit_name
from sysscope.web.app import create_app


def test_culprit_name():
    assert culprit_name("bazarr (8 acessos)") == "bazarr"
    assert culprit_name("jellyfin (1 acesso)") == "jellyfin"
    assert culprit_name("desconhecido") == "desconhecido"
    assert culprit_name(None) == "desconhecido"
    assert culprit_name("") == "desconhecido"


def test_incident_summary(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    def inc(ts, disk, culprit):
        i = db.create_incident(ts, disk, "atividade")
        db.set_incident_culprit(i, culprit)
    inc(100, "sdc", "bazarr (8 acessos)")
    inc(200, "sdc", "bazarr (2 acessos)")
    inc(300, "sdc", "jellyfin (1 acesso)")
    inc(400, "sde", "jellyfin (5 acessos)")
    inc(50,  "sde", "bazarr (1 acesso)")   # antes do 'since'
    s = db.incident_summary(since=99)
    by_disk = {d["disk"]: d for d in s}
    assert by_disk["sdc"]["count"] == 3
    assert by_disk["sdc"]["culprits"][0] == {"name": "bazarr", "count": 2}
    assert by_disk["sde"]["count"] == 1              # o de ts=50 foi excluído
    assert s[0]["disk"] == "sdc"                     # ordenado por count desc


def test_summary_endpoint_reachable(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    import time
    now = time.time()
    i = db.create_incident(now, "sdc", "atividade")
    db.set_incident_culprit(i, "bazarr (3 acessos)")
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    c = TestClient(create_app(ro, static_dir=str(tmp_path)))
    r = c.get("/api/incidents/summary?hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["disk"] == "sdc"
    assert body[0]["culprits"][0]["name"] == "bazarr"


def test_incident_by_id_still_works(tmp_path):
    # garante que a rota {incident_id} continua a funcionar após a reordenação
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    i = db.create_incident(1.0, "sde", "atividade")
    ro = Database(str(tmp_path / "t.db"), read_only=True)
    c = TestClient(create_app(ro, static_dir=str(tmp_path)))
    r = c.get(f"/api/incidents/{i}")
    assert r.status_code == 200
    assert r.json()["incident"]["disk"] == "sde"
