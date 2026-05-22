"""Mini smoke test: Ollama health + agent JSON round-trip.

Hits the local Ollama daemon directly via OllamaManager. First does a
streaming warm-up (the 14B model can take 60-120s to page into VRAM on a
cold start, which trips httpx ReadTimeout on a one-shot POST). Then runs
the real ReAct-style JSON round-trip on the already-resident model.

Run from the project root:

    .\.venv\Scripts\python.exe scripts\smoke_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Loading the 14B model into VRAM on a cold start can take 2-4 minutes on a
# fresh boot. Bump the HTTP timeout BEFORE config.settings is imported.
os.environ.setdefault("OLLAMA_TIMEOUT", "600.0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_logic.ollama_manager import OllamaManager  # noqa: E402
from config.settings import CONFIG  # noqa: E402


async def main() -> int:
    print("=" * 64)
    print(" CyberSim smoke test")
    print("=" * 64)
    print(f" Ollama host : {CONFIG.ollama.host}")
    print(f" Primary tag : {CONFIG.ollama.model}")
    print(f" Fallback tag: {CONFIG.ollama.fallback_model}")
    print()

    async with OllamaManager() as om:
        # ---- 1. health -----------------------------------------------------
        t0 = time.perf_counter()
        h = await om.health()
        print(f"[1/4] /api/tags  -> ok={h.get('ok')} "
              f"({(time.perf_counter()-t0)*1000:.0f} ms)")
        if not h.get("ok"):
            print(f"      ERROR: {h.get('error')}")
            return 2
        print(f"      installed models: {h.get('available_models')}")

        # ---- 2. resolve model ---------------------------------------------
        t0 = time.perf_counter()
        model = await om.ensure_model()
        print(f"[2/4] ensure_model -> {model} "
              f"({(time.perf_counter()-t0)*1000:.0f} ms)")

        # ---- 3. warm-up via streaming (tolerates slow first byte) ---------
        warm_messages = [
            {"role": "system", "content": "You are a terse assistant. Reply in <=4 words."},
            {"role": "user",   "content": "Reply with: ready"},
        ]
        print("[3/4] warm-up (streaming chat) ...", flush=True)
        t0 = time.perf_counter()
        chunks: list[str] = []
        async for piece in om.stream_chat(warm_messages, num_predict=8):
            chunks.append(piece)
        warm = "".join(chunks).strip()
        dt = time.perf_counter() - t0
        print(f"      warm-up done in {dt:.2f}s -> {warm!r}")

        # ---- 4. real ReAct-style round-trip (streaming) -------------------
        # Stream rather than json_mode=True so we don't sit blind on a long
        # grammar-constrained generation; this matches what the agent does
        # in production.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are CyberSim, an autonomous offensive-security agent operating in "
                    "an authorized lab sandbox. Respond with exactly one JSON object and "
                    "nothing else."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Authorized lab target: 10.0.0.5. Plan the very first ReAct step. "
                    "Reply ONLY with JSON of the form:\n"
                    '{"thought": "...", "action": "tool", "tool": "nmap_scan", '
                    '"arguments": {"target": "10.0.0.5"}}'
                ),
            },
        ]
        print("[4/4] ReAct chat (streaming) ...", flush=True)
        t0 = time.perf_counter()
        chunks = []
        async for piece in om.stream_chat(messages, num_predict=256):
            chunks.append(piece)
        content = "".join(chunks)
        dt = time.perf_counter() - t0
        print(f"      streamed {len(content)} chars in {dt:.2f}s "
              f"(stats: prompt={om.stats.prompt_tokens}, "
              f"completion={om.stats.completion_tokens})")
        flat = content.replace("\n", " ")
        print("      raw (first 240 chars):")
        print("      " + (flat[:240] or "<empty>"))

        obj = OllamaManager.extract_json(content)
        if not obj:
            print("      WARN: JSON extraction failed")
            return 3
        keys = ", ".join(obj.keys())
        print(f"      parsed JSON keys: [{keys}]")
        if obj.get("action") == "tool" and obj.get("tool"):
            print(f"      OK -- agent chose tool '{obj['tool']}' "
                  f"with args {obj.get('arguments')}")
        else:
            print(f"      WARN: unexpected action layout: {obj}")

    print()
    print("Smoke test PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
