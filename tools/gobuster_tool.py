"""Directory/file brute forcing — Gobuster preferred, dirsearch fallback."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


_DEFAULT_WORDLISTS = (
    "/usr/share/wordlists/dirb/common.txt",
    "/usr/share/seclists/Discovery/Web-Content/common.txt",
    "C:/Tools/SecLists/Discovery/Web-Content/common.txt",
)


class GobusterTool(BaseTool):
    schema = ToolSchema(
        name="dir_brute",
        description=(
            "Directory and file enumeration on a target web server using Gobuster "
            "(or dirsearch as a fallback). Returns discovered paths with HTTP status."
        ),
        parameters={
            "target": {"type": "string", "description": "Full base URL, e.g. http://10.0.0.5/"},
            "wordlist": {"type": "string", "description": "Path to wordlist (optional)."},
            "extensions": {"type": "string", "description": "Comma-separated extensions, e.g. 'php,asp,txt'."},
            "threads": {"type": "integer", "description": "Concurrency. Default 30."},
            "status_codes": {"type": "string", "description": "Status code allow-list, default '200,204,301,302,307,401,403'."},
            "timeout_s": {"type": "number", "description": "Hard timeout, default 600s."},
        },
        required=["target"],
        target_fields=("target",),
    )

    default_timeout = 600.0

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        target = str(arguments["target"]).strip()
        wordlist = arguments.get("wordlist") or _autodetect_wordlist()
        if not wordlist:
            return ToolResult(
                status=ToolStatus.ERROR,
                summary="no wordlist found — pass `wordlist` explicitly or install seclists",
            )
        threads = int(arguments.get("threads") or 30)
        status_codes = str(arguments.get("status_codes") or "200,204,301,302,307,401,403")
        extensions = arguments.get("extensions")
        timeout = float(arguments.get("timeout_s") or self.default_timeout)

        gobuster = self._which("gobuster")
        if gobuster:
            argv = [
                gobuster, "dir",
                "-u", target,
                "-w", str(wordlist),
                "-t", str(threads),
                "-s", status_codes,
                "--no-error", "-q",
            ]
            if extensions:
                argv += ["-x", str(extensions)]
            rc, stdout, stderr, elapsed = await self._spawn(argv, timeout=timeout, on_stream=on_stream)
            findings = _parse_gobuster(stdout)
            status = ToolStatus.OK if rc == 0 else ToolStatus.ERROR
            return ToolResult(
                status=status,
                summary=f"gobuster found {len(findings)} path(s) on {target} in {elapsed:.1f}s",
                stdout=stdout,
                stderr=stderr,
                duration_s=elapsed,
                data={"findings": findings, "engine": "gobuster"},
            )

        dirsearch = self._which("dirsearch") or self._which("dirsearch.py")
        if dirsearch:
            argv = [
                dirsearch, "-u", target, "-w", str(wordlist),
                "-t", str(threads), "--no-color",
            ]
            if extensions:
                argv += ["-e", str(extensions)]
            rc, stdout, stderr, elapsed = await self._spawn(argv, timeout=timeout, on_stream=on_stream)
            findings = _parse_dirsearch(stdout)
            status = ToolStatus.OK if rc == 0 else ToolStatus.ERROR
            return ToolResult(
                status=status,
                summary=f"dirsearch found {len(findings)} path(s) on {target}",
                stdout=stdout,
                stderr=stderr,
                duration_s=elapsed,
                data={"findings": findings, "engine": "dirsearch"},
            )

        return ToolResult(
            status=ToolStatus.NOT_INSTALLED,
            summary="neither gobuster nor dirsearch found on PATH",
        )


def _autodetect_wordlist() -> str | None:
    for p in _DEFAULT_WORDLISTS:
        if Path(p).is_file():
            return p
    return None


def _parse_gobuster(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("/"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        path = parts[0]
        status = next((p for p in parts if p.startswith("(Status:")), "")
        size = next((p for p in parts if p.startswith("[Size:")), "")
        out.append({
            "path": path,
            "status": status.replace("(Status:", "").rstrip(")"),
            "size": size.replace("[Size:", "").rstrip("]"),
        })
    return out


def _parse_dirsearch(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        # dirsearch format: "[time] HTTP_CODE - SIZE  -  /path"
        if " - " not in line or not line.startswith("["):
            continue
        try:
            _, body = line.split("] ", 1)
            code, rest = body.split(" - ", 1)
            size, path = rest.split("  -  ", 1)
            out.append({"path": path.strip(), "status": code.strip(), "size": size.strip()})
        except ValueError:
            continue
    return out
