"""SQLmap CLI wrapper for SQL injection auditing."""
from __future__ import annotations

import re
from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


class SqlmapTool(BaseTool):
    schema = ToolSchema(
        name="sqlmap_audit",
        description=(
            "Audit a target URL or HTTP request file for SQL injection using sqlmap. "
            "Use --batch-style non-interactive flags only."
        ),
        parameters={
            "target": {"type": "string", "description": "URL with parameters, e.g. http://target/item?id=1"},
            "data": {"type": "string", "description": "POST body to test (optional)."},
            "level": {"type": "integer", "description": "Test level 1-5, default 2."},
            "risk": {"type": "integer", "description": "Risk level 1-3, default 1."},
            "technique": {"type": "string", "description": "Subset of BEUSTQ techniques, default 'BEU'."},
            "dump": {"type": "boolean", "description": "If true, dump discovered tables. Default false."},
            "timeout_s": {"type": "number", "description": "Hard timeout, default 900s."},
        },
        required=["target"],
        target_fields=("target",),
    )

    default_timeout = 900.0

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        binary = self._which("sqlmap") or self._which("sqlmap.py")
        if binary is None:
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary="sqlmap not found on PATH",
            )

        target = str(arguments["target"]).strip()
        level = int(arguments.get("level") or 2)
        risk = int(arguments.get("risk") or 1)
        technique = str(arguments.get("technique") or "BEU")
        data = arguments.get("data")
        dump = bool(arguments.get("dump"))
        timeout = float(arguments.get("timeout_s") or self.default_timeout)

        argv: list[str] = [
            binary, "-u", target, "--batch", "--disable-coloring",
            "--level", str(max(1, min(level, 5))),
            "--risk", str(max(1, min(risk, 3))),
            "--technique", technique,
        ]
        if data:
            argv += ["--data", str(data)]
        if dump:
            argv += ["--dump"]

        rc, stdout, stderr, elapsed = await self._spawn(argv, timeout=timeout, on_stream=on_stream)
        injections = _extract_injections(stdout)
        dbms = _extract_dbms(stdout)
        status = ToolStatus.OK if rc == 0 else ToolStatus.ERROR
        summary = (
            f"sqlmap finished on {target} in {elapsed:.1f}s — "
            f"{len(injections)} injection(s) detected"
            + (f", DBMS={dbms}" if dbms else "")
        )
        return ToolResult(
            status=status,
            summary=summary,
            stdout=stdout,
            stderr=stderr,
            duration_s=elapsed,
            data={"injections": injections, "dbms": dbms},
        )


_INJ_RE = re.compile(r"Parameter:\s*(?P<param>[^\s]+)\s*\((?P<method>[^)]+)\)")
_DBMS_RE = re.compile(r"back-end DBMS:\s*(?P<dbms>.+)$", re.MULTILINE)


def _extract_injections(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _INJ_RE.finditer(text):
        out.append({"parameter": m.group("param"), "method": m.group("method")})
    return out


def _extract_dbms(text: str) -> str | None:
    m = _DBMS_RE.search(text)
    return m.group("dbms").strip() if m else None
