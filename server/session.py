"""In-memory attack session management on the server."""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_logic.ollama_manager import OllamaManager
from agent_logic.react_agent import AgentEvent, AgentEventType, ReActAgent
from tools import build_default_registry
from tools.sandbox import SandboxGuard
from tools.base import ToolResult


@dataclass
class AttackSession:
    session_id: str
    objective: str
    targets: list[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    state: str = "pending"           # pending → running → finished / errored
    transcript: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    final_report: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    model: str = "granite3.1-dense:latest"

    _event_log: list[AgentEvent] = field(default_factory=list, repr=False)
    _subscribers: list[asyncio.Queue[AgentEvent]] = field(default_factory=list, repr=False)
    _task: asyncio.Task | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def subscribe(self) -> asyncio.Queue[AgentEvent]:
        q: asyncio.Queue[AgentEvent] = asyncio.Queue()
        # replay backlog
        for ev in self._event_log:
            q.put_nowait(ev)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[AgentEvent]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, ev: AgentEvent) -> None:
        async with self._lock:
            self._event_log.append(ev)
            for q in list(self._subscribers):
                await q.put(ev)

    def report_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "objective": self.objective,
            "targets": self.targets,
            "started_at": self.created_at,
            "finished_at": self.finished_at or "",
            "metrics": {**self.metrics, "model": self.model, "state": self.state},
            "transcript": [ev.to_dict() for ev in self._event_log],
            "tool_results": [tr.to_dict() for tr in self.tool_results],
            "final_report": self.final_report,
        }


class SessionManager:
    def __init__(self, ollama: OllamaManager) -> None:
        self.ollama = ollama
        self.sessions: dict[str, AttackSession] = {}

    # -------------------------------------------------------------- factories
    def new_session(self, objective: str, targets: list[str]) -> AttackSession:
        session = AttackSession(
            session_id=secrets.token_hex(6),
            objective=objective,
            targets=list(targets),
            model=self.ollama.cfg.model,
        )
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AttackSession | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": s.session_id,
                "state": s.state,
                "objective": s.objective[:120],
                "targets": s.targets,
                "created_at": s.created_at,
                "finished_at": s.finished_at,
                "iterations": s.metrics.get("iterations", 0),
            }
            for s in sorted(self.sessions.values(), key=lambda s: s.created_at, reverse=True)
        ]

    # ----------------------------------------------------------------- launch
    async def start(self, session: AttackSession) -> None:
        if session._task and not session._task.done():
            return
        sandbox = SandboxGuard()
        sandbox.set_targets(session.targets)
        registry = build_default_registry(sandbox)
        agent = ReActAgent(self.ollama, registry)
        session.state = "running"

        async def runner() -> None:
            t0 = time.time()
            try:
                async for ev in agent.run(session.objective, targets=session.targets):
                    await session.publish(ev)
                    if ev.type is AgentEventType.TOOL_RESULT:
                        # tool_results list is already attached to the agent; copy
                        # the current snapshot to the session so the report
                        # generator can read it without coupling to the agent.
                        session.tool_results = list(agent.tool_results)
                    elif ev.type is AgentEventType.METRICS:
                        session.metrics = ev.payload
                    elif ev.type is AgentEventType.FINAL_ANSWER:
                        session.final_report = ev.payload.get("report")
                session.state = "finished"
            except Exception as exc:  # noqa: BLE001
                session.state = "errored"
                await session.publish(AgentEvent(
                    AgentEventType.AGENT_ERROR,
                    {"error": f"{type(exc).__name__}: {exc}"},
                ))
            finally:
                session.finished_at = datetime.now(timezone.utc).isoformat()
                session.metrics.setdefault("elapsed_s", round(time.time() - t0, 2))
                if not session.final_report and agent.final_report:
                    session.final_report = agent.final_report
                session.tool_results = list(agent.tool_results)

        session._task = asyncio.create_task(runner())

    async def stop(self, session: AttackSession) -> bool:
        if session._task and not session._task.done():
            session._task.cancel()
            session.state = "cancelled"
            return True
        return False
