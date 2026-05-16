"""Metasploit RPC integration (msfrpcd).

Talks to ``msfrpcd`` over its MessagePack RPC API.  Because msfrpc requires a
running ``msfrpcd`` instance (``msfrpcd -P <pass> -S -a 127.0.0.1``) we only
attempt the integration when the connection parameters are reachable; otherwise
the tool returns ``NOT_INSTALLED`` so the agent can adapt.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


class MetasploitTool(BaseTool):
    schema = ToolSchema(
        name="msf_exploit",
        description=(
            "Run a Metasploit module against an authorized target via msfrpcd. "
            "Use for confirmed CVEs only. Requires a running msfrpcd daemon."
        ),
        parameters={
            "target": {"type": "string", "description": "RHOST (must be in scope)."},
            "module": {"type": "string", "description": "Full module path, e.g. 'exploit/windows/smb/ms17_010_eternalblue'."},
            "module_type": {"type": "string", "enum": ["exploit", "auxiliary", "post"], "description": "Default 'exploit'."},
            "options": {"type": "object", "description": "Datastore key/value overrides (RPORT, LHOST, LPORT, ...)."},
            "payload": {"type": "string", "description": "Optional payload override."},
            "wait_seconds": {"type": "number", "description": "How long to wait for session output. Default 25s."},
        },
        required=["target", "module"],
        target_fields=("target",),
    )

    default_timeout = 600.0

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        host = os.getenv("MSFRPC_HOST", "127.0.0.1")
        port = int(os.getenv("MSFRPC_PORT", "55553"))
        user = os.getenv("MSFRPC_USER", "msf")
        password = os.getenv("MSFRPC_PASSWORD", "")
        ssl = os.getenv("MSFRPC_SSL", "true").lower() == "true"

        if not password:
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary=(
                    "MSFRPC_PASSWORD env var not set. Start msfrpcd with "
                    "`msfrpcd -P <pwd> -S -a 127.0.0.1` and export MSFRPC_PASSWORD."
                ),
            )

        try:
            client = await asyncio.to_thread(
                _connect_msfrpc, host, port, user, password, ssl
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                status=ToolStatus.NOT_INSTALLED,
                summary=f"cannot reach msfrpcd at {host}:{port}: {exc}",
            )

        target = str(arguments["target"]).strip()
        module = str(arguments["module"]).strip()
        module_type = str(arguments.get("module_type") or "exploit")
        options = dict(arguments.get("options") or {})
        options.setdefault("RHOSTS", target)
        payload = arguments.get("payload")
        wait_s = float(arguments.get("wait_seconds") or 25.0)

        try:
            result = await asyncio.to_thread(
                _execute_module, client, module_type, module, options, payload, wait_s, on_stream
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                status=ToolStatus.ERROR,
                summary=f"msfrpc module execution failed: {exc}",
            )
        return result


# ----------------------------------------------------------------- low-level
def _connect_msfrpc(host: str, port: int, user: str, password: str, ssl: bool) -> Any:
    """Connect using pymetasploit3 if available, else raise."""
    try:
        from pymetasploit3.msfrpc import MsfRpcClient  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pymetasploit3 not installed — `pip install pymetasploit3` for live MSF integration"
        ) from exc
    return MsfRpcClient(password, server=host, port=port, ssl=ssl, username=user)


def _execute_module(
    client: Any,
    mtype: str,
    name: str,
    options: dict[str, Any],
    payload: str | None,
    wait_s: float,
    on_stream: StreamCallback | None,
) -> ToolResult:
    import time

    module = client.modules.use(mtype, name)
    for k, v in options.items():
        module[k] = v
    if payload:
        result = module.execute(payload=payload)
    else:
        result = module.execute()
    job_id = result.get("job_id")
    uuid = result.get("uuid")
    if on_stream:
        try:
            on_stream("stdout", f"msfrpc: executed {mtype}/{name} job_id={job_id} uuid={uuid}")
        except Exception:
            pass

    deadline = time.time() + wait_s
    sessions_found: list[dict[str, Any]] = []
    while time.time() < deadline:
        sessions = client.sessions.list or {}
        if sessions:
            sessions_found = [
                {"id": sid, **sinfo} for sid, sinfo in sessions.items()
            ]
            break
        time.sleep(1.5)

    return ToolResult(
        status=ToolStatus.OK,
        summary=(
            f"msf {mtype}/{name} dispatched (job={job_id}); "
            f"{len(sessions_found)} session(s) opened within {wait_s:.0f}s"
        ),
        data={
            "job_id": job_id,
            "uuid": uuid,
            "options": options,
            "sessions": sessions_found,
        },
    )
