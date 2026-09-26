"""Egress policy helpers shared by the Sentinel and network tools (defence in depth)."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def is_private_host(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(_BLOCKED_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def domain_allowed(host: str, allowlist: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowlist)


def urls_in(value: Any) -> list[str]:
    """All http(s) URLs anywhere in a JSON-like value."""
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, dict):
        return [u for v in value.values() for u in urls_in(v)]
    if isinstance(value, list):
        return [u for v in value for u in urls_in(v)]
    return []


def registrable_domain(host: str) -> str:
    """Rough eTLD+1 (no PSL dependency): keeps the last two labels, three for common 2-level TLDs."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "edu", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
