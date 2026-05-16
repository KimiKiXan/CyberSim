"""OllamaManager — async gateway for the local Granite model.

Provides:
  * Health check / model auto-pull
  * Streaming chat with line-buffered yields (for terminal display)
  * Robust JSON extraction for ReAct tool-call output
  * Token / latency accounting
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable

import httpx

from config.settings import CONFIG, OllamaConfig


@dataclass
class ChatStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_ms: float = 0.0
    calls: int = 0

    def record(self, prompt_tokens: int, completion_tokens: int, latency_ms: float) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_latency_ms += latency_ms
        self.calls += 1


@dataclass
class OllamaResponse:
    content: str
    raw: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_LAST_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*$", re.DOTALL)


class OllamaError(RuntimeError):
    """Raised when the Ollama backend is unreachable or returns bad data."""


class OllamaManager:
    """Async wrapper around the Ollama HTTP API tuned for the Granite ReAct agent."""

    def __init__(self, cfg: OllamaConfig | None = None) -> None:
        self.cfg = cfg or CONFIG.ollama
        self.stats = ChatStats()
        self._client: httpx.AsyncClient | None = None
        self._model_resolved: str | None = None
        self._lock = asyncio.Lock()

    # --------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> "OllamaManager":
        await self.connect()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.cfg.host,
                timeout=httpx.Timeout(self.cfg.request_timeout, connect=10.0),
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -------------------------------------------------------------- diagnostics
    async def health(self) -> dict[str, Any]:
        await self.connect()
        assert self._client is not None
        try:
            r = await self._client.get("/api/tags")
            r.raise_for_status()
            data = r.json()
            models = [m.get("name") for m in data.get("models", [])]
            return {"ok": True, "host": self.cfg.host, "available_models": models}
        except httpx.HTTPError as exc:
            return {"ok": False, "host": self.cfg.host, "error": str(exc)}

    async def ensure_model(self) -> str:
        """Return the resolved model name, pulling if necessary."""
        async with self._lock:
            if self._model_resolved:
                return self._model_resolved
            await self.connect()
            assert self._client is not None
            tags = await self._client.get("/api/tags")
            tags.raise_for_status()
            installed = {m.get("name") for m in tags.json().get("models", [])}
            for candidate in (self.cfg.model, self.cfg.fallback_model):
                if candidate in installed:
                    self._model_resolved = candidate
                    return candidate
            # Try pulling the primary
            await self._pull(self.cfg.model)
            self._model_resolved = self.cfg.model
            return self._model_resolved

    async def _pull(self, model: str) -> None:
        assert self._client is not None
        async with self._client.stream(
            "POST", "/api/pull", json={"name": model, "stream": True}
        ) as resp:
            resp.raise_for_status()
            async for _line in resp.aiter_lines():
                # pull progress is intentionally swallowed; UI is welcome to wrap this
                pass

    # ------------------------------------------------------------------- chat
    def _build_options(self, **overrides: Any) -> dict[str, Any]:
        return {
            "temperature": overrides.get("temperature", self.cfg.temperature),
            "top_p": overrides.get("top_p", self.cfg.top_p),
            "num_ctx": overrides.get("num_ctx", self.cfg.num_ctx),
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        **opts: Any,
    ) -> OllamaResponse:
        """Single-shot chat completion. Returns full content + stats."""
        await self.connect()
        assert self._client is not None
        model = await self.ensure_model()
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.cfg.keep_alive,
            "options": self._build_options(**opts),
        }
        if json_mode:
            body["format"] = "json"
        start = time.perf_counter()
        try:
            r = await self._client.post("/api/chat", json=body)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama chat failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000
        data = r.json()
        msg = data.get("message", {}) or {}
        content: str = msg.get("content", "") or ""
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        self.stats.record(prompt_tokens, completion_tokens, latency_ms)
        return OllamaResponse(
            content=content,
            raw=data,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        **opts: Any,
    ) -> AsyncIterator[str]:
        """Stream raw token chunks. Caller is responsible for assembling them."""
        await self.connect()
        assert self._client is not None
        model = await self.ensure_model()
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.cfg.keep_alive,
            "options": self._build_options(**opts),
        }
        async with self._client.stream("POST", "/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_lines():
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                piece = (chunk.get("message") or {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    pt = int(chunk.get("prompt_eval_count", 0) or 0)
                    ct = int(chunk.get("eval_count", 0) or 0)
                    self.stats.record(pt, ct, 0.0)
                    break

    # -------------------------------------------------------------- JSON utils
    @staticmethod
    def extract_json(text: str) -> dict[str, Any] | None:
        """Best-effort JSON object extractor for ReAct tool-call payloads."""
        if not text:
            return None
        # 1) plain parse
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        # 2) fenced ```json ... ``` block
        fences = list(_JSON_FENCE_RE.finditer(text))
        if fences:
            blob = fences[-1].group(1)
            try:
                obj = json.loads(blob)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        # 3) last balanced { ... } object in the text
        candidate = OllamaManager._last_balanced_object(text)
        if candidate:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                # try to repair single quotes / trailing commas
                repaired = OllamaManager._repair_json(candidate)
                try:
                    obj = json.loads(repaired)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def _last_balanced_object(text: str) -> str | None:
        depth = 0
        start = -1
        last: tuple[int, int] | None = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    last = (start, i + 1)
        if last is None:
            return None
        return text[last[0]:last[1]]

    @staticmethod
    def _repair_json(text: str) -> str:
        repaired = re.sub(r",\s*([}\]])", r"\1", text)  # trailing commas
        repaired = repaired.replace("'", '"')
        return repaired
