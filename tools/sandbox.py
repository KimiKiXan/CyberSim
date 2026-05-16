"""Sandbox / authorization guard.

Every tool invocation is filtered through :class:`SandboxGuard`.  Only targets
that appear in the operator-provided allow-list (IPs, CIDR networks, or DNS
hostnames) are permitted.  Anything else raises :class:`SandboxViolation`.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse


class SandboxViolation(RuntimeError):
    """Raised when a tool tries to act outside the authorized scope."""


_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class SandboxGuard:
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = field(default_factory=list)
    enforce: bool = True
    block_when_empty: bool = True

    # ------------------------------------------------------------------ setup
    def set_targets(self, targets: list[str]) -> None:
        """Replace the allow-list with the supplied entries."""
        self.allowed_hosts.clear()
        self.allowed_networks.clear()
        for raw in targets:
            entry = (raw or "").strip().lower()
            if not entry:
                continue
            # strip schema/port/path so the operator can paste URLs
            host = self._extract_host(entry)
            if host is None:
                continue
            # CIDR network
            try:
                net = ipaddress.ip_network(host, strict=False)
                self.allowed_networks.append(net)
                continue
            except ValueError:
                pass
            # bare IP
            try:
                ip = ipaddress.ip_address(host)
                self.allowed_hosts.add(str(ip))
                continue
            except ValueError:
                pass
            # hostname
            if _HOST_RE.match(host):
                self.allowed_hosts.add(host)

    def snapshot(self) -> dict[str, list[str]]:
        return {
            "hosts": sorted(self.allowed_hosts),
            "networks": [str(n) for n in self.allowed_networks],
        }

    # ----------------------------------------------------------------- check
    def assert_allowed(self, target: str) -> str:
        """Raise :class:`SandboxViolation` unless the target is in scope.

        Returns the canonical host string we resolved.
        """
        if not self.enforce:
            return target
        host = self._extract_host(target)
        if not host:
            raise SandboxViolation(f"target '{target}' is not parseable")
        if not self.allowed_hosts and not self.allowed_networks:
            if self.block_when_empty:
                raise SandboxViolation(
                    "no authorized targets configured — populate the Targets panel first"
                )
            return host
        if self._matches_hostname(host):
            return host
        # try IP / CIDR matching
        ip = self._resolve_ip(host)
        if ip and self._matches_ip(ip):
            return host
        raise SandboxViolation(
            f"target '{target}' is outside the authorized scope; "
            f"add it to the Targets panel to proceed"
        )

    # --------------------------------------------------------------- helpers
    def _matches_hostname(self, host: str) -> bool:
        return host in self.allowed_hosts

    def _matches_ip(self, ip: ipaddress._BaseAddress) -> bool:
        if str(ip) in self.allowed_hosts:
            return True
        return any(ip in net for net in self.allowed_networks)

    @staticmethod
    def _extract_host(value: str) -> str | None:
        value = value.strip().lower()
        if not value:
            return None
        if "://" in value:
            try:
                parsed = urlparse(value)
                host = parsed.hostname or ""
                return host or None
            except ValueError:
                return None
        # strip credentials and port
        if "@" in value:
            value = value.rsplit("@", 1)[-1]
        if value.count(":") == 1 and "/" not in value:
            value = value.split(":", 1)[0]
        if "/" in value and not _looks_like_cidr(value):
            value = value.split("/", 1)[0]
        return value or None

    @staticmethod
    def _resolve_ip(host: str) -> ipaddress._BaseAddress | None:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            pass
        try:
            return ipaddress.ip_address(socket.gethostbyname(host))
        except (socket.gaierror, ValueError):
            return None


def _looks_like_cidr(value: str) -> bool:
    if "/" not in value:
        return False
    host, _, mask = value.partition("/")
    if not mask.isdigit():
        return False
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False
