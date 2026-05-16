"""CyberSim tool abstraction layer.

Every offensive capability the LLM can call is exposed here as a ``BaseTool``
subclass registered with :class:`ToolRegistry`.  The registry takes care of:

* exposing a JSON-schema description of each tool to the LLM
* validating arguments
* enforcing the sandbox (target allow-list)
* streaming stdout / stderr back through the agent event bus
"""
from .base import BaseTool, ToolResult, ToolSchema, ToolStatus
from .registry import ToolRegistry
from .sandbox import SandboxGuard, SandboxViolation
from .nmap_tool import NmapTool
from .gobuster_tool import GobusterTool
from .nuclei_tool import NucleiTool
from .sqlmap_tool import SqlmapTool
from .hydra_tool import HydraTool
from .web_scraper_tool import WebScraperTool
from .metasploit_tool import MetasploitTool
from .postexploit_tool import PostExploitTool


def build_default_registry(sandbox: SandboxGuard) -> ToolRegistry:
    """Build the canonical registry with all 8 pentest tools."""
    registry = ToolRegistry(sandbox=sandbox)
    registry.register(NmapTool())
    registry.register(GobusterTool())
    registry.register(NucleiTool())
    registry.register(SqlmapTool())
    registry.register(HydraTool())
    registry.register(WebScraperTool())
    registry.register(MetasploitTool())
    registry.register(PostExploitTool())
    return registry


__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolSchema",
    "ToolStatus",
    "ToolRegistry",
    "SandboxGuard",
    "SandboxViolation",
    "NmapTool",
    "GobusterTool",
    "NucleiTool",
    "SqlmapTool",
    "HydraTool",
    "WebScraperTool",
    "MetasploitTool",
    "PostExploitTool",
    "build_default_registry",
]
