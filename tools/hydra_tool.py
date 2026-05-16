"""Hydra protocol auth-bypass tool."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


_DEFAULT_USERS = (
    "C:/Tools/SecLists/Usernames/top-usernames-shortlist.txt",
    "/usr/share/seclists/Usernames/top-usernames-shortlist.txt",
)
_DEFAULT_PASS = (
    "C:/Tools/SecLists/Passwords/Common-Credentials/10-million-password-list-top-1000.txt",
    "/usr/share/seclists/Passwords/Common-Credentials/10-million-password-list-top-1000.txt",
    "/usr/share/wordlists/rockyou.txt",
)


class HydraTool(BaseTool):
    schema = ToolSchema(
        name="auth_bruteforce",
        description=(
            "Try a credential dictionary against a service (ssh, ftp, http-post-form, "
            "smb, rdp, vnc, ...). Returns any valid credentials Hydra reports."
        ),
        parameters={
            "target": {"type": "string", "description": "Host or IP (must be in scope)."},
            "service": {"type": "string", "description": "Hydra service module (e.g. 'ssh', 'ftp', 'http-post-form')."},
            "user": {"type": "string", "description": "Single username (optional if user_list is set)."},
            "user_list": {"type": "string", "description": "Path to username list."},
            "pass_list": {"type": "string", "description": "Path to password list."},
            "port": {"type": "integer", "description": "Service port (optional)."},
            "module_opts": {"type": "string", "description": "Extra service-module options (e.g. http-post-form path)."},
            "tasks": {"type": "integer", "description": "Parallel tasks (default 8)."},
            "timeout_s": {"type": "number", "description": "Hard timeout, default 600s."},
        },
        required=["target", "service"],
        target_fields=("target",),
    )

    default_timeout = 600.0

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        binary = self._which("hydra")
        if binary is None:
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary="hydra not found on PATH",
            )

        target = str(arguments["target"]).strip()
        service = str(arguments["service"]).strip().lower()
        user = arguments.get("user")
        user_list = arguments.get("user_list") or _first_existing(_DEFAULT_USERS)
        pass_list = arguments.get("pass_list") or _first_existing(_DEFAULT_PASS)
        if not (user or user_list):
            return ToolResult(
                status=ToolStatus.ERROR,
                summary="provide either `user` or `user_list`",
            )
        if not pass_list:
            return ToolResult(
                status=ToolStatus.ERROR,
                summary="no password list provided / autodetected",
            )

        tasks = int(arguments.get("tasks") or 8)
        timeout = float(arguments.get("timeout_s") or self.default_timeout)
        port = arguments.get("port")
        module_opts = arguments.get("module_opts")

        argv: list[str] = [binary, "-t", str(tasks), "-I", "-V"]
        if user:
            argv += ["-l", str(user)]
        else:
            argv += ["-L", str(user_list)]
        argv += ["-P", str(pass_list)]
        if port:
            argv += ["-s", str(port)]
        service_spec = f"{service}://{target}"
        if module_opts:
            service_spec = f"{service_spec}{module_opts}"
        argv.append(service_spec)

        rc, stdout, stderr, elapsed = await self._spawn(argv, timeout=timeout, on_stream=on_stream)
        creds = _extract_creds(stdout)
        status = ToolStatus.OK if rc in (0, 255) else ToolStatus.ERROR
        return ToolResult(
            status=status,
            summary=f"hydra finished against {service}://{target} — {len(creds)} valid credential(s)",
            stdout=stdout,
            stderr=stderr,
            duration_s=elapsed,
            data={"credentials": creds},
        )


_CRED_RE = re.compile(
    r"host:\s*(?P<host>\S+)\s+login:\s*(?P<user>\S+)\s+password:\s*(?P<password>\S+)",
    re.IGNORECASE,
)


def _extract_creds(text: str) -> list[dict[str, str]]:
    return [m.groupdict() for m in _CRED_RE.finditer(text)]


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if Path(c).is_file():
            return c
    return None
