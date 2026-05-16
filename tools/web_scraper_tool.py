"""Pure-Python web/DOM analyser — no external CLI required."""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from .base import BaseTool, StreamCallback, ToolResult, ToolSchema, ToolStatus


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_INTERESTING_HEADERS = {
    "server", "x-powered-by", "x-frame-options", "content-security-policy",
    "strict-transport-security", "set-cookie", "x-content-type-options",
}


class WebScraperTool(BaseTool):
    schema = ToolSchema(
        name="web_analyze",
        description=(
            "Fetch a URL and analyse its DOM, response headers, forms, comments, "
            "JavaScript references, and visible secrets. Pure-Python — no CLI required."
        ),
        parameters={
            "target": {"type": "string", "description": "Full URL to analyse."},
            "follow_redirects": {"type": "boolean", "description": "Default true."},
            "max_links": {"type": "integer", "description": "Cap the number of links returned, default 200."},
            "user_agent": {"type": "string", "description": "Optional custom User-Agent."},
            "timeout_s": {"type": "number", "description": "Hard timeout, default 30s."},
        },
        required=["target"],
        target_fields=("target",),
    )

    default_timeout = 30.0

    async def run(
        self,
        arguments: dict[str, Any],
        *,
        on_stream: StreamCallback | None = None,
    ) -> ToolResult:
        import httpx
        from bs4 import BeautifulSoup

        target = str(arguments["target"]).strip()
        if not urlparse(target).scheme:
            target = "http://" + target
        follow = bool(arguments.get("follow_redirects", True))
        max_links = int(arguments.get("max_links") or 200)
        timeout = float(arguments.get("timeout_s") or self.default_timeout)
        headers = {"User-Agent": str(arguments.get("user_agent") or "CyberSim/1.0 (+lab)")}

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow) as client:
                if on_stream:
                    await _safe_stream(on_stream, "stdout", f"GET {target}")
                resp = await client.get(target, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                status=ToolStatus.ERROR,
                summary=f"web_analyze failed to fetch {target}: {exc}",
            )

        body = resp.text or ""
        soup = BeautifulSoup(body, "lxml")
        if on_stream:
            await _safe_stream(on_stream, "stdout", f"HTTP {resp.status_code} – {len(body)} bytes")

        links: list[str] = []
        for a in soup.find_all("a", href=True):
            if len(links) >= max_links:
                break
            href = a["href"]
            links.append(urljoin(target, href))

        forms = []
        for f in soup.find_all("form"):
            forms.append({
                "action": urljoin(target, f.get("action") or ""),
                "method": (f.get("method") or "get").lower(),
                "inputs": [
                    {"name": i.get("name"), "type": i.get("type", "text")}
                    for i in f.find_all("input")
                    if i.get("name")
                ],
            })

        scripts = [urljoin(target, s.get("src")) for s in soup.find_all("script", src=True)]
        comments = [c.strip() for c in soup.find_all(string=lambda t: getattr(t, "name", None) is None and "<!--" in str(t))]
        emails = sorted(set(_EMAIL_RE.findall(body)))

        interesting_headers = {
            k.lower(): v for k, v in resp.headers.items() if k.lower() in _INTERESTING_HEADERS
        }

        title = soup.title.string.strip() if soup.title and soup.title.string else None

        data = {
            "url": str(resp.url),
            "status": resp.status_code,
            "title": title,
            "links": links,
            "forms": forms,
            "scripts": scripts,
            "comments": comments[:25],
            "emails": emails,
            "headers": interesting_headers,
            "size_bytes": len(body),
        }
        summary = (
            f"HTTP {resp.status_code} {resp.url} — "
            f"{len(links)} links / {len(forms)} forms / {len(scripts)} scripts / "
            f"{len(emails)} email(s) leaked / {len(interesting_headers)} interesting header(s)"
        )
        return ToolResult(
            status=ToolStatus.OK,
            summary=summary,
            stdout=body[:8000],
            data=data,
        )


async def _safe_stream(cb: StreamCallback, name: str, line: str) -> None:
    res = cb(name, line)
    if asyncio.iscoroutine(res):
        await res
