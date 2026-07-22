from sysscope.storage.db import Database
from sysscope.collector.io_attribution import (
    AttributedEvent, IoAttribution, top_culprit,
)


def ev(ts, disk="sde", comm="bazarr", container="bazarr", path="/media/HDD8TB/x"):
    return AttributedEvent(ts, disk, 1, comm, container, "read", path, "fatrace")


def test_top_culprit_prefers_container():
    evs = [ev(1, comm="mono", container="bazarr"),
           ev(2, comm="mono", container="bazarr"),
           ev(3, comm="ffprobe", container="jellyfin")]
    assert top_culprit(evs) == "bazarr (2 acessos)"


def test_top_culprit_singular():
    assert top_culprit([ev(1)]) == "bazarr (1 acesso)"


def test_top_culprit_empty():
    assert top_culprit([]) == "desconhecido"


def test_backfill_and_finalize(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    io.record(ev(99.0))                 # antes do spin-up (dentro da janela)
    inc = db.create_incident(100.0, "sde", "power")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0))                # depois do spin-up
    io.record(ev(101.0, disk="sdd"))    # outro disco -> ignorado
    io.finalize_due(now=200.0)          # já passou a deadline
    events = db.incident_events(inc)
    assert len(events) == 2
    assert db.list_incidents()[0]["top_culprit"] == "bazarr (2 acessos)"


def test_backfill_horizon_beyond_window(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0, backfill_horizon=15.0)
    io.record(ev(90.0))                 # 10s antes do spin-up: > window, < horizon
    inc = db.create_incident(100.0, "sde", "power")
    io.open_incident(inc, "sde", 100.0)
    io.finalize_due(now=200.0)          # já passou a deadline
    events = db.incident_events(inc)
    assert events != []
    assert db.list_incidents()[0]["top_culprit"] != "desconhecido"


def test_not_finalized_before_deadline(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.init_schema()
    io = IoAttribution(db, window=5.0)
    inc = db.create_incident(100.0, "sde", "power")
    io.open_incident(inc, "sde", 100.0)
    io.record(ev(101.0))
    io.finalize_due(now=102.0)          # deadline = 105, ainda não
    assert db.list_incidents()[0]["top_culprit"] is None
    assert db.incident_events(inc) == []
