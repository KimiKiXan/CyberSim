"""Nuclei vulnerability template scanner."""
from __future__ import annotations

import json
from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


class NucleiTool(BaseTool):
    schema = ToolSchema(
        name="vuln_scan",
        description=(
            "Run ProjectDiscovery Nuclei templates against a target URL. Returns a list of "
            "matched templates with severity, name, CVE id (if any) and matched line."
        ),
        parameters={
            "target": {"type": "string", "description": "Full URL (http/https) of the target."},
            "severity": {
                "type": "string",
                "description": "Comma-separated severities to include (info,low,medium,high,critical).",
            },
            "tags": {"type": "string", "description": "Comma-separated nuclei template tags."},
            "rate_limit": {"type": "integer", "description": "Requests per second (default 150)."},
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
        binary = self._which("nuclei")
        if binary is None:
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary="nuclei binary not found on PATH",
            )

        target = str(arguments["target"]).strip()
        severity = arguments.get("severity") or "medium,high,critical"
        tags = arguments.get("tags")
        rate = int(arguments.get("rate_limit") or 150)
        timeout = float(arguments.get("timeout_s") or self.default_timeout)

        argv: list[str] = [
            binary, "-u", target, "-jsonl", "-silent",
            "-severity", str(severity),
            "-rate-limit", str(rate),
            "-no-color",
        ]
        if tags:
            argv += ["-tags", str(tags)]

        rc, stdout, stderr, elapsed = await self._spawn(argv, timeout=timeout, on_stream=on_stream)
        findings: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            info = doc.get("info") or {}
            findings.append({
                "template": doc.get("template-id") or doc.get("templateID"),
                "name": info.get("name"),
                "severity": info.get("severity"),
                "matched_at": doc.get("matched-at") or doc.get("matched"),
                "cve": (info.get("classification") or {}).get("cve-id"),
                "cvss": (info.get("classification") or {}).get("cvss-score"),
                "tags": info.get("tags"),
            })

        severities = {}
        for f in findings:
            sev = (f.get("severity") or "unknown").lower()
            severities[sev] = severities.get(sev, 0) + 1

        status = ToolStatus.OK if rc in (0, 1) else ToolStatus.ERROR
        summary = (
            f"nuclei produced {len(findings)} finding(s) on {target} "
            f"({', '.join(f'{k}={v}' for k, v in severities.items()) or 'no hits'}) "
            f"in {elapsed:.1f}s"
        )
        return ToolResult(
            status=status,
            summary=summary,
            stdout=stdout,
            stderr=stderr,
            duration_s=elapsed,
            data={"findings": findings, "by_severity": severities},
        )
