"""Servidor web do SysScope: REST + WebSocket + ficheiros estáticos."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sysscope.common.config import load_config
from sysscope.storage.db import Database


def create_app(db: Database, static_dir: str) -> FastAPI:
    app = FastAPI(title="SysScope")

    @app.get("/api/disks")
    def disks() -> list[dict]:
        return db.latest_disk_status()

    @app.get("/api/disks/{disk}/samples")
    def samples(disk: str, since: float = 0.0) -> list[dict]:
        return db.recent_disk_samples(disk, since)

    @app.get("/api/incidents")
    def incidents(limit: int = 50) -> list[dict]:
        return db.list_incidents(limit)

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: int) -> dict:
        items = db.list_incidents(1000)
        match = next((i for i in items if i["id"] == incident_id), None)
        return {"incident": match, "events": db.incident_events(incident_id)}

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        try:
            while True:
                await sock.send_json({"disks": db.latest_disk_status()})
                await asyncio.sleep(2.0)
        except WebSocketDisconnect:
            return

    static_path = Path(static_dir)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_path / "index.html")

    if (static_path / "app.js").exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    return app


def main() -> None:
    import uvicorn
    cfg = load_config("/etc/sysscope/sysscope.toml")
    db = Database(cfg.db_path, read_only=True)
    static_dir = str(Path(__file__).parent / "static")
    app = create_app(db, static_dir)
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port)


if __name__ == "__main__":
    main()
