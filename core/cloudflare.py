"""
cloudflare.py — Cloudflare IP detection and real client IP resolution.

Cloudflare sits in front of the origin server, so Django sees Cloudflare's
IP in REMOTE_ADDR instead of the reader's real IP. Requests from Cloudflare
carry the real client IP in the CF-Connecting-IP header, which we trust
only when the request genuinely came from a known Cloudflare IP range.

Usage:
    from core.cloudflare import get_real_ip

    ip = get_real_ip(request)  # reader's true IP address
"""

import ipaddress
import logging

from django.conf import settings

logger = logging.getLogger("core.cloudflare")

# Pre-built list of ipaddress.IPv4Network / IPv6Network objects for fast lookup.
# Populated lazily from settings.CLOUDFLARE_IPS on first call.
_CLOUDFLARE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None

# Pre-built list of trusted proxy networks from settings.TRUSTED_PROXIES.
# Populated lazily on first call.
_TRUSTED_PROXY_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None


def _get_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Return the parsed Cloudflare IP network list, building it once."""
    global _CLOUDFLARE_NETWORKS
    if _CLOUDFLARE_NETWORKS is None:
        ranges: list[str] = getattr(settings, "CLOUDFLARE_IPS", [])
        networks = []
        for cidr in ranges:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning("Invalid CIDR in CLOUDFLARE_IPS: %s", cidr)
        _CLOUDFLARE_NETWORKS = networks
    return _CLOUDFLARE_NETWORKS


def _get_trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Return the parsed TRUSTED_PROXIES network list, building it once."""
    global _TRUSTED_PROXY_NETWORKS
    if _TRUSTED_PROXY_NETWORKS is None:
        ranges: list[str] = getattr(settings, "TRUSTED_PROXIES", [])
        networks = []
        for cidr in ranges:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning("Invalid CIDR in TRUSTED_PROXIES: %s", cidr)
        _TRUSTED_PROXY_NETWORKS = networks
    return _TRUSTED_PROXY_NETWORKS


def is_trusted_proxy(ip: str) -> bool:
    """
    Return True if *ip* belongs to a configured trusted proxy range.

    Args:
        ip: IPv4 or IPv6 address string.

    Returns:
        True if the address is within any of the CIDR blocks listed in
        settings.TRUSTED_PROXIES.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    return any(addr in network for network in _get_trusted_proxy_networks())


def is_cloudflare_ip(ip: str) -> bool:
    """
    Return True if *ip* belongs to a known Cloudflare IP range.

    Args:
        ip: IPv4 or IPv6 address string.

    Returns:
        True if the address is within any of the Cloudflare CIDR blocks
        listed in settings.CLOUDFLARE_IPS.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    return any(addr in network for network in _get_networks())


def get_real_ip(request) -> str:
    """
    Resolve the real client IP address from a Django request.

    Priority order:
      1. CF-Connecting-IP header — if request came from a Cloudflare IP.
      2. X-Forwarded-For first entry — if behind any other trusted proxy.
      3. REMOTE_ADDR — direct connection fallback.

    Args:
        request: Django HttpRequest object.

    Returns:
        IP address string, or "unknown" if none is resolvable.
    """
    remote_addr = request.META.get("REMOTE_ADDR", "")

    # Cloudflare path: trust CF-Connecting-IP only when the upstream is CF
    if remote_addr and is_cloudflare_ip(remote_addr):
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if cf_ip:
            return cf_ip

    # Generic reverse-proxy path: only trust X-Forwarded-For when the
    # direct connection (REMOTE_ADDR) is a configured trusted proxy.
    # Without this guard a client can forge X-Forwarded-For and spoof any IP.
    if remote_addr and is_trusted_proxy(remote_addr):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()

    return remote_addr or "unknown"
