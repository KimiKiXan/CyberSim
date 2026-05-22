"""Block until the Ollama daemon answers on $OLLAMA_HOST/api/tags.

Used by run_server.bat to make sure the LLM backend is ready before the
FastAPI server starts answering /health requests.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request


def _host() -> str:
    raw = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw.rstrip("/")


def main(timeout_s: float = 45.0, poll_s: float = 1.5) -> int:
    base = _host()
    url = f"{base}/api/tags"
    deadline = time.time() + timeout_s
    last_err: str = ""
    print(f"[wait_for_ollama] probing {url} (timeout={int(timeout_s)}s)", flush=True)
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CyberSim"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if 200 <= resp.status < 300:
                    print(f"[wait_for_ollama] OK ({resp.status})", flush=True)
                    return 0
                last_err = f"http {resp.status}"
        except urllib.error.URLError as exc:
            last_err = str(exc.reason)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(poll_s)
    print(f"[wait_for_ollama] TIMEOUT — last error: {last_err}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
