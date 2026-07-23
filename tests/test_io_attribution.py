from sysscope.storage.db import Database
from sysscope.collector.io_attribution import (
    AttributedEvent, IoAttribution, top_culprit,
)


def ev(ts, disk="sde", comm="bazarr", container="bazarr",
       path="/media/HDD8TB/x", pid=1):
    return AttributedEvent(ts, disk, pid, comm, container, "read", path, "fatrace")


def test_top_culprit_prefers_container():
    evs = [ev(1, comm="mono", container="bazarr"),
           ev(2, comm="mono", container="bazarr"),
           ev(3, comm="ffprobe", container="jellyfin")]
    assert top_culprit(evs) == "bazarr (2 acessos)"


def test_top_culprit_singular():
    assert top_culprit([ev(1)]) == "bazarr (1 acesso)"


def test_top_culprit_empty():
    assert top_culprit([]) == "acesso curto"


def test_backfill_and_finalize(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    io.record(ev(99.0, path="/media/HDD8TB/a"))    # antes do spin-up (na janela)
    inc = db.create_incident(100.0, "sde", "atividade")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0, path="/media/HDD8TB/b"))   # depois do spin-up
    io.record(ev(101.0, disk="sdd"))               # outro disco -> ignorado
    io.finalize_due(now=200.0)                      # já passou a deadline
    events = db.incident_events(inc)
    assert len(events) == 2
    assert db.list_incidents()[0]["top_culprit"] == "bazarr (2 acessos)"


def test_dedup_same_pid_path(tmp_path):
    # A rajada de varrimentos regista o mesmo ficheiro aberto muitas vezes;
    # deduplicar por (pid, caminho) evita inflar a contagem.
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    inc = db.create_incident(100.0, "sde", "atividade")
    io.open_incident(inc, "sde", 100.0)
    for t in (100.2, 100.4, 100.6, 100.8):
        io.record(ev(t, path="/media/HDD8TB/mesmo.mkv", pid=42))
    io.finalize_due(now=200.0)
    assert len(db.incident_events(inc)) == 1
    assert db.list_incidents()[0]["top_culprit"] == "bazarr (1 acesso)"


def test_backfill_horizon_beyond_window(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0, backfill_horizon=15.0)
    io.record(ev(90.0))                 # 10s antes do spin-up: > window, < horizon
    inc = db.create_incident(100.0, "sde", "atividade")
    io.open_incident(inc, "sde", 100.0)
    io.finalize_due(now=200.0)          # já passou a deadline
    events = db.incident_events(inc)
    assert events != []
    assert db.list_incidents()[0]["top_culprit"] == "bazarr (1 acesso)"


def test_empty_incident_labelled_short_access(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    inc = db.create_incident(100.0, "sde", "atividade")
    io.open_incident(inc, "sde", 100.0)   # nenhum evento
    io.finalize_due(now=200.0)
    assert db.incident_events(inc) == []
    assert db.list_incidents()[0]["top_culprit"] == "acesso curto"


def test_not_finalized_before_deadline(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    inc = db.create_incident(100.0, "sde", "atividade")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0))
    io.finalize_due(now=102.0)          # deadline = 105, ainda não
    assert db.list_incidents()[0]["top_culprit"] is None
    assert db.incident_events(inc) == []
