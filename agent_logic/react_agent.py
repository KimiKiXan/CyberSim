"""ReAct (Reason → Act → Observe) loop driving the CyberSim LLM agent."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from config.settings import CONFIG
from tools.base import ToolResult, ToolStatus
from tools.registry import ToolRegistry

from .ollama_manager import OllamaManager, OllamaError


class AgentEventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    LLM_THOUGHT = "llm_thought"
    LLM_RAW = "llm_raw"
    TOOL_CALL = "tool_call"
    TOOL_STREAM = "tool_stream"
    TOOL_RESULT = "tool_result"
    SANDBOX_BLOCK = "sandbox_block"
    AGENT_ERROR = "agent_error"
    FINAL_ANSWER = "final_answer"
    METRICS = "metrics"


@dataclass
class AgentEvent:
    type: AgentEventType
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "payload": self.payload, "ts": self.ts}


EventCallback = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass
class AgentMetrics:
    iterations: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    sandbox_blocks: int = 0
    llm_latency_ms: float = 0.0
    started_at: float = field(default_factory=time.time)

    def snapshot(self, *, finalized: bool = False) -> dict[str, Any]:
        elapsed = time.time() - self.started_at
        return {
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "sandbox_blocks": self.sandbox_blocks,
            "llm_latency_ms": round(self.llm_latency_ms, 1),
            "elapsed_s": round(elapsed, 2),
            "finalized": finalized,
        }


class ReActAgent:
    """Drives a single attack session from objective → final report."""

    def __init__(
        self,
        ollama: OllamaManager,
        registry: ToolRegistry,
        *,
        system_prompt: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.ollama = ollama
        self.registry = registry
        self.max_iterations = max_iterations or CONFIG.agent.max_iterations
        self.system_prompt = system_prompt or _load_system_prompt()
        self.transcript: list[dict[str, Any]] = []
        self.tool_results: list[ToolResult] = []
        self.metrics = AgentMetrics()
        self.final_report: str | None = None

    # ------------------------------------------------------------------ public
    async def run(
        self,
        objective: str,
        *,
        targets: list[str],
        emit: EventCallback | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Execute the ReAct loop. Yields :class:`AgentEvent`s in real time."""
        events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def push(ev: AgentEvent) -> None:
            await events.put(ev)
            if emit is not None:
                res = emit(ev)
                if asyncio.iscoroutine(res):
                    await res

        producer = asyncio.create_task(self._run_inner(objective, targets, push))

        async def drain() -> AsyncIterator[AgentEvent]:
            while True:
                if producer.done() and events.empty():
                    break
                try:
                    ev = await asyncio.wait_for(events.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if ev is None:
                    break
                yield ev

        async for ev in drain():
            yield ev
        # ensure exceptions propagate
        try:
            await producer
        except Exception as exc:  # noqa: BLE001
            yield AgentEvent(AgentEventType.AGENT_ERROR, {"error": str(exc)})

    # --------------------------------------------------------------- internals
    async def _run_inner(
        self,
        objective: str,
        targets: list[str],
        push: Callable[[AgentEvent], Awaitable[None]],
    ) -> None:
        self.metrics = AgentMetrics()
        self.transcript = []
        self.tool_results = []
        self.final_report = None

        await push(AgentEvent(AgentEventType.SESSION_START, {
            "objective": objective,
            "targets": targets,
            "model": self.ollama.cfg.model,
            "max_iterations": self.max_iterations,
            "tools": self.registry.names(),
        }))

        bootstrap_user = _initial_user_message(objective, targets, self.registry)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": bootstrap_user},
        ]

        for step in range(1, self.max_iterations + 1):
            self.metrics.iterations = step
            try:
                resp = await self.ollama.chat(messages, json_mode=False)
            except OllamaError as exc:
                await push(AgentEvent(AgentEventType.AGENT_ERROR, {"error": str(exc)}))
                return
            self.metrics.llm_latency_ms += resp.latency_ms
            await push(AgentEvent(AgentEventType.LLM_RAW, {
                "iteration": step,
                "content": resp.content,
                "latency_ms": resp.latency_ms,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
            }))

            decision = OllamaManager.extract_json(resp.content)
            if decision is None:
                # JSON salvage failed — retry once asking for strict JSON
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous turn did not contain valid JSON. Reply with EXACTLY "
                        "one JSON object matching the protocol — no markdown fences, no prose "
                        "after it."
                    ),
                })
                continue

            thought = decision.get("thought") or ""
            await push(AgentEvent(AgentEventType.LLM_THOUGHT, {
                "iteration": step,
                "thought": thought,
            }))

            action = (decision.get("action") or "").strip().lower()
            if action == "finish":
                final = decision.get("final_answer") or thought or "(empty)"
                self.final_report = str(final)
                await push(AgentEvent(AgentEventType.FINAL_ANSWER, {"report": final}))
                break

            tool_name = decision.get("tool") or ""
            arguments = decision.get("arguments") or {}
            if not tool_name:
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": (
                    "You must either call a tool (`action='tool'` + tool + arguments) or "
                    "`action='finish'` with a `final_answer`. Try again."
                )})
                continue

            await push(AgentEvent(AgentEventType.TOOL_CALL, {
                "iteration": step,
                "tool": tool_name,
                "arguments": arguments,
            }))

            async def stream_cb(stream: str, line: str) -> None:
                await push(AgentEvent(AgentEventType.TOOL_STREAM, {
                    "iteration": step,
                    "tool": tool_name,
                    "stream": stream,
                    "line": line,
                }))

            result = await self.registry.invoke(tool_name, arguments, on_stream=stream_cb)
            self.tool_results.append(result)
            self.metrics.tool_calls += 1
            if result.status == ToolStatus.ERROR:
                self.metrics.tool_errors += 1
            if result.status == ToolStatus.BLOCKED:
                self.metrics.sandbox_blocks += 1
                await push(AgentEvent(AgentEventType.SANDBOX_BLOCK, {
                    "tool": tool_name, "arguments": arguments, "reason": result.summary,
                }))

            await push(AgentEvent(AgentEventType.TOOL_RESULT, {
                "iteration": step,
                "tool": tool_name,
                "status": result.status.value,
                "summary": result.summary,
                "data_keys": sorted(result.data.keys()),
                "duration_s": round(result.duration_s, 2),
            }))

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": f"Observation:\n{result.to_observation()}\n\n"
                           "Decide the next step. Reply with one JSON object as specified.",
            })

        await push(AgentEvent(AgentEventType.METRICS, self.metrics.snapshot(
            finalized=self.final_report is not None
        )))
        await push(AgentEvent(AgentEventType.SESSION_END, {
            "completed": self.final_report is not None,
            "iterations": self.metrics.iterations,
        }))


def _load_system_prompt() -> str:
    path = CONFIG.paths.config / "system_prompt.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "You are CyberSim, an autonomous offensive-security agent in a sandboxed lab."


def _initial_user_message(objective: str, targets: list[str], registry: ToolRegistry) -> str:
    targets_block = "\n".join(f"  - {t}" for t in targets) or "  (none)"
    return (
        f"## Objective\n{objective}\n\n"
        f"## Authorized Targets (sandbox allow-list)\n{targets_block}\n\n"
        f"## Available Tools (call exactly one per turn)\n"
        f"```json\n{registry.describe_for_prompt()}\n```\n\n"
        "Begin the ReAct loop. Reply with ONE JSON object per the protocol."
    )
