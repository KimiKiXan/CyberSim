"""Central runtime configuration for CyberSim."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


@dataclass
class OllamaConfig:
    host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    # Default tuned for an RTX 4080 Super (16 GB VRAM): Qwen 2.5 14B Instruct.
    # The bare `qwen2.5:14b` Ollama tag resolves to the instruct Q4_K_M build
    # (~9 GB) — fits entirely on-GPU and is what `ollama pull qwen2.5:14b`
    # downloads by default.
    model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
    fallback_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:7b")
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
    top_p: float = float(os.getenv("OLLAMA_TOP_P", "0.9"))
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
    request_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "180.0"))
    keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "60m")


@dataclass
class ServerConfig:
    host: str = os.getenv("SERVER_HOST", "localhost")
    port: int = int(os.getenv("SERVER_PORT", "4899"))
    reload: bool = os.getenv("CYBERSIM_RELOAD", "false").lower() == "true"


@dataclass
class AgentConfig:
    max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "40"))
    react_pause_seconds: float = float(os.getenv("AGENT_REACT_PAUSE", "0.0"))
    enable_self_debug: bool = True
    json_retry_limit: int = 3


@dataclass
class SandboxConfig:
    enforce_target_allowlist: bool = True
    default_targets: list[str] = field(default_factory=list)
    block_public_internet_when_empty: bool = True
    private_only_fallback_nets: list[str] = field(
        default_factory=lambda: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"]
    )


@dataclass
class PathsConfig:
    root: Path = ROOT
    uploads: Path = ROOT / "uploads"
    reports: Path = ROOT / "reports"
    logs: Path = ROOT / "logs"
    data: Path = ROOT / "data"
    config: Path = ROOT / "config"


@dataclass
class CyberSimConfig:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)

    def ensure_paths(self) -> None:
        for p in (self.paths.uploads, self.paths.reports, self.paths.logs, self.paths.data):
            p.mkdir(parents=True, exist_ok=True)


CONFIG = CyberSimConfig()
CONFIG.ensure_paths()
