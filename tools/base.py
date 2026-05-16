"""Tool base classes for the ReAct agent."""
from __future__ import annotations

import asyncio
import shlex
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence


class ToolStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"
    NOT_INSTALLED = "not_installed"


@dataclass
class ToolSchema:
    """Schema description shown to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]                # JSON-schema-ish
    required: list[str] = field(default_factory=list)
    target_fields: tuple[str, ...] = ("target",)   # fields that must pass sandbox

    def as_prompt_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }


@dataclass
class ToolResult:
    status: ToolStatus
    summary: str
    stdout: str = ""
    stderr: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_observation(self, max_chars: int = 4000) -> str:
        body = self.summary or self.stdout or self.stderr or "(no output)"
        if len(body) > max_chars:
            body = body[: max_chars - 80] + f"\n…[truncated {len(body) - max_chars + 80} chars]"
        return f"[{self.tool} :: {self.status.value}] ({self.duration_s:.2f}s)\n{body}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status.value,
            "summary": self.summary,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "data": self.data,
            "duration_s": self.duration_s,
            "arguments": self.arguments,
        }


StreamCallback = Callable[[str, str], Awaitable[None] | None]
"""``(stream_name, line)``  →  awaitable | None.  ``stream_name`` is "stdout"/"stderr"."""


class BaseTool(ABC):
    """Subclass once per offensive capability."""

    schema: ToolSchema

    # whether the tool requires the controller to provide a writable workdir
    needs_workdir: bool = False

    # subprocess defaults
    default_timeout: float = 300.0

    # ------------------------------------------------------------------ public
    @abstractmethod
    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        """Execute the tool against validated arguments."""

    # convenience that subclasses can call
    async def _spawn(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
        on_stream: StreamCallback | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str, float]:
        """Run a subprocess streaming both pipes through ``on_stream``."""
        timeout = timeout or self.default_timeout
        start = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_buf: list[str] = []
        stderr_buf: list[str] = []

        async def _pump(stream: asyncio.StreamReader | None, name: str, buf: list[str]) -> None:
            if stream is None:
                return
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\r\n")
                buf.append(line)
                if on_stream is not None:
                    result = on_stream(name, line)
                    if asyncio.iscoroutine(result):
                        await result

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _pump(proc.stdout, "stdout", stdout_buf),
                    _pump(proc.stderr, "stderr", stderr_buf),
                    proc.wait(),
                ),
                timeout=timeout,
            )
            rc = proc.returncode if proc.returncode is not None else -1
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            rc = -9
            stderr_buf.append(f"[timeout] killed after {timeout:.0f}s")
        elapsed = time.perf_counter() - start
        return rc, "\n".join(stdout_buf), "\n".join(stderr_buf), elapsed

    @staticmethod
    def _which(binary: str) -> str | None:
        return shutil.which(binary)

    @staticmethod
    def _quote_argv(argv: Sequence[str]) -> str:
        return " ".join(shlex.quote(a) for a in argv)
