"""Camada de persistência SQLite (modo WAL)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS disk_samples (
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    power_state TEXT NOT NULL,
    read_bps REAL NOT NULL,
    write_bps REAL NOT NULL,
    read_iops REAL NOT NULL,
    write_iops REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_disk_ts ON disk_samples(disk, ts);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    detection TEXT NOT NULL,
    top_culprit TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(ts);

CREATE TABLE IF NOT EXISTS io_events (
    ts REAL NOT NULL,
    disk TEXT NOT NULL,
    pid INTEGER NOT NULL,
    comm TEXT NOT NULL,
    container TEXT,
    op TEXT NOT NULL,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    incident_id INTEGER,
    FOREIGN KEY(incident_id) REFERENCES incidents(id)
);
CREATE INDEX IF NOT EXISTS idx_events_incident ON io_events(incident_id);
"""


class Database:
    def __init__(self, path: str, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if read_only:
            uri = f"file:{path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self._conn.execute("PRAGMA busy_timeout=5000")
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert_disk_sample(self, ts, disk, power_state, read_bps, write_bps,
                           read_iops, write_iops) -> None:
        self._conn.execute(
            "INSERT INTO disk_samples VALUES (?,?,?,?,?,?,?)",
            (ts, disk, power_state, read_bps, write_bps, read_iops, write_iops),
        )
        self._conn.commit()

    def create_incident(self, ts, disk, detection) -> int:
        cur = self._conn.execute(
            "INSERT INTO incidents (ts, disk, detection) VALUES (?,?,?)",
            (ts, disk, detection),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def set_incident_culprit(self, incident_id, top_culprit) -> None:
        self._conn.execute(
            "UPDATE incidents SET top_culprit=? WHERE id=?",
            (top_culprit, incident_id),
        )
        self._conn.commit()

    def insert_io_event(self, ts, disk, pid, comm, container, op, path,
                        source, incident_id) -> None:
        self._conn.execute(
            "INSERT INTO io_events VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, disk, pid, comm, container, op, path, source, incident_id),
        )
        self._conn.commit()

    def latest_disk_status(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT s.* FROM disk_samples s
               JOIN (SELECT disk, MAX(ts) AS mts FROM disk_samples GROUP BY disk) m
               ON s.disk = m.disk AND s.ts = m.mts"""
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_disk_samples(self, disk, since) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM disk_samples WHERE disk=? AND ts>? ORDER BY ts",
            (disk, since),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_incidents(self, limit=50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM incidents ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def incident_events(self, incident_id) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM io_events WHERE incident_id=? ORDER BY ts",
            (incident_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def purge_older_than(self, cutoff_ts) -> int:
        cur = self._conn.execute("DELETE FROM disk_samples WHERE ts<?", (cutoff_ts,))
        n = cur.rowcount
        self._conn.execute(
            "DELETE FROM io_events WHERE incident_id IN "
            "(SELECT id FROM incidents WHERE ts<?)", (cutoff_ts,))
        self._conn.execute("DELETE FROM incidents WHERE ts<?", (cutoff_ts,))
        self._conn.commit()
        return n

    def close(self) -> None:
        self._conn.close()
