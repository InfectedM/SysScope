from sysscope.storage.db import Database, culprit_name


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
