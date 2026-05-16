"""FastAPI application — REST + WebSocket facade for CyberSim."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agent_logic.ollama_manager import OllamaManager
from agent_logic.react_agent import AgentEvent, AgentEventType
from config.settings import CONFIG
from .session import SessionManager
from .report_generator import ReportData, ReportFormat, ReportGenerator

log = logging.getLogger("cybersim.server")


class StartSessionRequest(BaseModel):
    objective: str = Field(..., min_length=4)
    targets: list[str] = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]
    json_mode: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    ollama = OllamaManager()
    await ollama.connect()
    app.state.ollama = ollama
    app.state.sessions = SessionManager(ollama)
    app.state.reports = ReportGenerator()
    log.info("CyberSim server ready on %s using model=%s", CONFIG.ollama.host, CONFIG.ollama.model)
    try:
        yield
    finally:
        await ollama.close()


def create_app() -> FastAPI:
    app = FastAPI(title="CyberSim", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        h = await app.state.ollama.health()
        return {"server": "ok", "ollama": h}

    @app.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        from tools import build_default_registry
        from tools.sandbox import SandboxGuard
        reg = build_default_registry(SandboxGuard(enforce=False))
        return {"tools": reg.describe_json()}

    @app.post("/api/sessions")
    async def start_session(payload: StartSessionRequest) -> dict[str, Any]:
        session = app.state.sessions.new_session(payload.objective, payload.targets)
        await app.state.sessions.start(session)
        return {"session_id": session.session_id, "state": session.state}

    @app.get("/api/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": app.state.sessions.list_sessions()}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        s = app.state.sessions.get(session_id)
        if not s:
            raise HTTPException(404, "session not found")
        return s.report_payload()

    @app.post("/api/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict[str, Any]:
        s = app.state.sessions.get(session_id)
        if not s:
            raise HTTPException(404, "session not found")
        ok = await app.state.sessions.stop(s)
        return {"stopped": ok, "state": s.state}

    @app.post("/api/sessions/{session_id}/report")
    async def build_report(session_id: str, fmt: str = "markdown") -> dict[str, Any]:
        s = app.state.sessions.get(session_id)
        if not s:
            raise HTTPException(404, "session not found")
        try:
            report_fmt = ReportFormat(fmt.lower())
        except ValueError:
            raise HTTPException(400, f"unsupported format '{fmt}'")
        rd = ReportData(**s.report_payload())
        path = app.state.reports.build(rd, report_fmt)
        return {"path": str(path), "format": report_fmt.value, "size": path.stat().st_size}

    @app.get("/api/sessions/{session_id}/report/download")
    async def download_report(session_id: str, fmt: str = "markdown") -> FileResponse:
        s = app.state.sessions.get(session_id)
        if not s:
            raise HTTPException(404, "session not found")
        try:
            report_fmt = ReportFormat(fmt.lower())
        except ValueError:
            raise HTTPException(400, f"unsupported format '{fmt}'")
        rd = ReportData(**s.report_payload())
        path = app.state.reports.build(rd, report_fmt)
        media = {
            ReportFormat.MARKDOWN: "text/markdown",
            ReportFormat.PDF: "application/pdf",
            ReportFormat.JSON: "application/json",
        }[report_fmt]
        return FileResponse(path, media_type=media, filename=path.name)

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        if not file.filename:
            raise HTTPException(400, "missing filename")
        dest = CONFIG.paths.uploads / Path(file.filename).name
        with dest.open("wb") as f:
            while chunk := await file.read(64 * 1024):
                f.write(chunk)
        return {"path": str(dest), "size": dest.stat().st_size}

    @app.get("/api/uploads")
    async def list_uploads() -> dict[str, Any]:
        items = []
        for p in CONFIG.paths.uploads.iterdir():
            if p.is_file():
                items.append({"name": p.name, "size": p.stat().st_size})
        return {"uploads": items}

    @app.post("/api/llm/chat")
    async def llm_chat(payload: ChatRequest) -> dict[str, Any]:
        resp = await app.state.ollama.chat(payload.messages, json_mode=payload.json_mode)
        return {
            "content": resp.content,
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "latency_ms": resp.latency_ms,
        }

    @app.websocket("/ws/sessions/{session_id}")
    async def session_ws(ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        session = app.state.sessions.get(session_id)
        if not session:
            await ws.send_text(json.dumps({"type": "error", "payload": {"error": "not found"}}))
            await ws.close()
            return
        queue = session.subscribe()
        try:
            while True:
                ev: AgentEvent = await queue.get()
                await ws.send_text(json.dumps(ev.to_dict(), default=str))
                if ev.type is AgentEventType.SESSION_END:
                    # flush any remaining queued events without blocking forever
                    while not queue.empty():
                        tail = queue.get_nowait()
                        await ws.send_text(json.dumps(tail.to_dict(), default=str))
                    break
        except WebSocketDisconnect:
            pass
        finally:
            session.unsubscribe(queue)
            try:
                await ws.close()
            except Exception:
                pass

    return app


def run_server() -> None:
    import uvicorn
    cfg = CONFIG.server
    uvicorn.run(
        "server.app:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        log_level="info",
    )
