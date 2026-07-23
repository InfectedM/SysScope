"""Servidor web do SysScope: REST + WebSocket + ficheiros estáticos."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sysscope.common.config import load_config
from sysscope.storage.db import Database
from sysscope.web.settings import (
    DEFAULT_SETTINGS_PATH,
    host_for_mode,
    lan_ipv4_addresses,
    read_bind_mode,
    write_bind_mode,
)


class _BindBody(BaseModel):
    # Definida ao nível do módulo (não dentro de create_app): com
    # `from __future__ import annotations`, o FastAPI resolve anotações via
    # get_type_hints() no __globals__ da função — uma classe aninhada não
    # seria visível aí e o pydantic deixaria de ser detetado como corpo.
    bind_mode: str


def create_app(
    db: Database,
    static_dir: str,
    settings_path: str = DEFAULT_SETTINGS_PATH,
    restart_fn=None,
) -> FastAPI:
    app = FastAPI(title="SysScope")

    def _default_restart() -> None:
        # Sai ~0.8s depois de responder; o systemd (Restart=always) reinicia
        # o serviço, que relê o bind_mode no arranque.
        threading.Timer(0.8, lambda: os._exit(0)).start()

    do_restart = restart_fn or _default_restart

    @app.get("/api/settings")
    def get_settings() -> dict:
        mode = read_bind_mode(settings_path)
        port = getattr(app.state, "web_port", 8787)
        urls = [f"http://{ip}:{port}" for ip in lan_ipv4_addresses()]
        return {"bind_mode": mode, "port": port, "lan_urls": urls}

    @app.post("/api/settings/bind")
    def set_bind(body: _BindBody) -> dict:
        try:
            write_bind_mode(settings_path, body.bind_mode)
        except ValueError:
            raise HTTPException(status_code=400, detail="bind_mode inválido")
        do_restart()
        return {"ok": True, "bind_mode": body.bind_mode, "restarting": True}

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

    @app.get("/api/services")
    def services() -> dict:
        snap = db.get_snapshot("services")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/containers")
    def containers() -> list:
        snap = db.get_snapshot("containers")
        return json.loads(snap["payload"]) if snap else []

    @app.get("/api/network")
    def network() -> dict:
        conns = db.get_snapshot("connections")
        return {
            "interfaces": db.latest_net_status(),
            "connections": json.loads(conns["payload"]) if conns else [],
        }

    @app.get("/api/network/samples")
    def network_samples(iface: str, since: float = 0.0) -> list:
        return db.recent_net_samples(iface, since)

    @app.get("/api/system")
    def system() -> dict:
        snap = db.get_snapshot("system")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/wakeups")
    def wakeups_ep() -> dict:
        snap = db.get_snapshot("wakeups")
        return json.loads(snap["payload"]) if snap else {}

    @app.get("/api/processes")
    def processes() -> list:
        snap = db.get_snapshot("processes")
        return json.loads(snap["payload"]) if snap else []

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
    app.state.web_port = cfg.web_port
    mode = read_bind_mode(DEFAULT_SETTINGS_PATH)
    uvicorn.run(app, host=host_for_mode(mode), port=cfg.web_port)


if __name__ == "__main__":
    main()
