"""Nmap network reconnaissance tool wrapper."""
from __future__ import annotations

from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


# allow-listed flags — anything outside this set is silently dropped.  Keeps the
# LLM from spawning arbitrary shell tokens via the "extra_flags" channel.
_SAFE_FLAGS = {
    "-sV", "-sS", "-sT", "-sU", "-sn", "-Pn", "-O", "-A",
    "-T1", "-T2", "-T3", "-T4", "-T5",
    "-F", "--open", "-v", "-vv", "--top-ports", "--reason",
    "--script", "--script-args",
}


class NmapTool(BaseTool):
    schema = ToolSchema(
        name="nmap_scan",
        description=(
            "Network reconnaissance with Nmap. Use for host discovery, service/version "
            "detection, OS fingerprinting and NSE script scans. Returns parsed host + "
            "port + service data."
        ),
        parameters={
            "target": {"type": "string", "description": "Single host, hostname or CIDR (must be in scope)."},
            "ports": {"type": "string", "description": "Port spec (e.g. '1-1024' or '22,80,443'). Optional."},
            "profile": {
                "type": "string",
                "enum": ["quick", "service", "aggressive", "discovery", "vuln"],
                "description": "High-level scan profile. Defaults to 'service'.",
            },
            "extra_flags": {
                "type": "string",
                "description": "Optional extra nmap flags, restricted to a safe subset.",
            },
            "timeout_s": {"type": "number", "description": "Hard timeout in seconds (default 600)."},
        },
        required=["target"],
        target_fields=("target",),
    )

    default_timeout = 600.0

    _PROFILE_FLAGS = {
        "quick":      ["-T4", "-F", "--open", "--reason"],
        "service":    ["-T4", "-sV", "--open", "--reason"],
        "aggressive": ["-T4", "-A", "-sV", "--reason"],
        "discovery":  ["-sn", "-T4", "--reason"],
        "vuln":       ["-T4", "-sV", "--script=vuln", "--reason"],
    }

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        binary = self._which("nmap")
        if binary is None:
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary="nmap binary not found on PATH",
            )

        target = str(arguments["target"]).strip()
        profile = str(arguments.get("profile") or "service")
        if profile not in self._PROFILE_FLAGS:
            profile = "service"
        ports = arguments.get("ports")
        extra = arguments.get("extra_flags") or ""
        timeout = float(arguments.get("timeout_s") or self.default_timeout)

        argv: list[str] = [binary, *self._PROFILE_FLAGS[profile]]
        if ports:
            argv += ["-p", str(ports)]
        for tok in str(extra).split():
            head = tok.split("=", 1)[0]
            if head in _SAFE_FLAGS:
                argv.append(tok)
        argv.append(target)

        rc, stdout, stderr, elapsed = await self._spawn(
            argv, timeout=timeout, on_stream=on_stream
        )
        status = ToolStatus.OK if rc == 0 else ToolStatus.ERROR
        parsed = _parse_nmap_text(stdout)
        summary = (
            f"nmap {profile} scan of {target}: "
            f"{len(parsed['hosts'])} host(s), "
            f"{sum(len(h['ports']) for h in parsed['hosts'])} open port(s) "
            f"in {elapsed:.1f}s (rc={rc})"
        )
        return ToolResult(
            status=status,
            summary=summary + "\n\n" + stdout,
            stdout=stdout,
            stderr=stderr,
            duration_s=elapsed,
            data=parsed,
        )


def _parse_nmap_text(text: str) -> dict[str, Any]:
    """Light-weight parser that turns nmap stdout into structured JSON."""
    hosts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Nmap scan report for"):
            if current is not None:
                hosts.append(current)
            current = {"host": line.replace("Nmap scan report for", "").strip(), "ports": [], "os": None}
        elif current is not None:
            if "/tcp" in line or "/udp" in line:
                parts = line.split()
                if len(parts) >= 3 and parts[1] in {"open", "filtered", "closed"}:
                    port, proto = parts[0].split("/", 1)
                    current["ports"].append({
                        "port": int(port),
                        "proto": proto,
                        "state": parts[1],
                        "service": parts[2] if len(parts) > 2 else "",
                        "version": " ".join(parts[3:]) if len(parts) > 3 else "",
                    })
            elif line.lower().startswith("os details:") or line.lower().startswith("running:"):
                current["os"] = line.split(":", 1)[1].strip()
    if current is not None:
        hosts.append(current)
    return {"hosts": hosts}
