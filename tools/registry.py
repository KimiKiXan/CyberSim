"""Tool registry exposed to the LLM via the ReAct loop."""
from __future__ import annotations

import json
import time
from typing import Any

from .base import BaseTool, ToolResult, ToolStatus, StreamCallback
from .sandbox import SandboxGuard, SandboxViolation


class ToolRegistry:
    def __init__(self, sandbox: SandboxGuard) -> None:
        self.sandbox = sandbox
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------ registration
    def register(self, tool: BaseTool) -> None:
        if tool.schema.name in self._tools:
            raise ValueError(f"tool '{tool.schema.name}' already registered")
        self._tools[tool.schema.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    # --------------------------------------------------------------- prompting
    def describe_for_prompt(self) -> str:
        """Render an LLM-facing tool catalog."""
        catalog = [t.schema.as_prompt_dict() for t in self._tools.values()]
        return json.dumps(catalog, indent=2)

    def describe_json(self) -> list[dict[str, Any]]:
        return [t.schema.as_prompt_dict() for t in self._tools.values()]

    # -------------------------------------------------------------- execution
    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        arguments = dict(arguments or {})
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name,
                status=ToolStatus.ERROR,
                summary=f"unknown tool '{name}'. Available: {', '.join(self.names())}",
                arguments=arguments,
            )

        # arg validation
        missing = [k for k in tool.schema.required if k not in arguments or arguments[k] in ("", None)]
        if missing:
            return ToolResult(
                tool=name,
                status=ToolStatus.ERROR,
                summary=f"missing required argument(s): {', '.join(missing)}",
                arguments=arguments,
            )

        # sandbox enforcement on every declared target field
        for field_name in tool.schema.target_fields:
            value = arguments.get(field_name)
            if value is None:
                continue
            try:
                self.sandbox.assert_allowed(str(value))
            except SandboxViolation as exc:
                return ToolResult(
                    tool=name,
                    status=ToolStatus.BLOCKED,
                    summary=f"sandbox blocked '{field_name}={value}': {exc}",
                    arguments=arguments,
                )

        start = time.perf_counter()
        try:
            result = await tool.run(arguments, on_stream=on_stream)
        except Exception as exc:  # noqa: BLE001 - exposing message to the LLM
            return ToolResult(
                tool=name,
                status=ToolStatus.ERROR,
                summary=f"tool crashed: {type(exc).__name__}: {exc}",
                duration_s=time.perf_counter() - start,
                arguments=arguments,
            )
        if not result.tool:
            result.tool = name
        if not result.arguments:
            result.arguments = arguments
        if result.duration_s == 0.0:
            result.duration_s = time.perf_counter() - start
        return result
