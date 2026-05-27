"""Thin HTTP + WebSocket client used by the PyQt5 UI."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
import websockets

from config.settings import CONFIG


@dataclass
class ServerEndpoint:
    host: str = field(default_factory=lambda: CONFIG.server.host)
    port: int = field(default_factory=lambda: CONFIG.server.port)

    @property
    def http_base(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_base(self) -> str:
        return f"ws://{self.host}:{self.port}"


class CyberSimClient:
    def __init__(self, endpoint: ServerEndpoint | None = None) -> None:
        self.endpoint = endpoint or ServerEndpoint()

    # ---------------------------------------------------------------- HTTP API
    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.endpoint.http_base}/health")
            r.raise_for_status()
            return r.json()

    async def list_tools(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.endpoint.http_base}/api/tools")
            r.raise_for_status()
            return r.json().get("tools", [])

    async def start_session(self, objective: str, targets: list[str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.endpoint.http_base}/api/sessions",
                json={"objective": objective, "targets": targets},
            )
            r.raise_for_status()
            return r.json()

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.endpoint.http_base}/api/sessions")
            r.raise_for_status()
            return r.json().get("sessions", [])

    async def fetch_session(self, session_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self.endpoint.http_base}/api/sessions/{session_id}")
            r.raise_for_status()
            return r.json()

    async def stop_session(self, session_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{self.endpoint.http_base}/api/sessions/{session_id}/stop")
            r.raise_for_status()
            return r.json()

    async def build_report(self, session_id: str, fmt: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self.endpoint.http_base}/api/sessions/{session_id}/report",
                params={"fmt": fmt},
            )
            r.raise_for_status()
            return r.json()

    async def download_report(self, session_id: str, fmt: str, dest: str) -> str:
        url = f"{self.endpoint.http_base}/api/sessions/{session_id}/report/download"
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("GET", url, params={"fmt": fmt}) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        f.write(chunk)
        return dest

    async def upload_file(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(path, "rb") as f:
                files = {"file": (os.path.basename(path), f)}
                r = await client.post(f"{self.endpoint.http_base}/api/uploads", files=files)
                r.raise_for_status()
                return r.json()

    # ------------------------------------------------------------------- WS
    async def stream_session(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        url = f"{self.endpoint.ws_base}/ws/sessions/{session_id}"
        async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
            async for raw in ws:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
