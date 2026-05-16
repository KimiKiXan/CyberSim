"""Central runtime configuration for CyberSim."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class OllamaConfig:
    host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model: str = os.getenv("OLLAMA_MODEL", "granite3.1-dense:latest")
    fallback_model: str = os.getenv("OLLAMA_FALLBACK_MODEL", "granite3.1-dense:8b")
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
    top_p: float = float(os.getenv("OLLAMA_TOP_P", "0.9"))
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    request_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "180.0"))
    keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")


@dataclass
class ServerConfig:
    host: str = os.getenv("CYBERSIM_HOST", "127.0.0.1")
    port: int = int(os.getenv("CYBERSIM_PORT", "8765"))
    reload: bool = os.getenv("CYBERSIM_RELOAD", "false").lower() == "true"


@dataclass
class AgentConfig:
    max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "25"))
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
