"""SSRF (Server-Side Request Forgery) protection and URL validation module.

Ensures that the research engine never connects to internal infrastructure,
localhost, cloud metadata services (e.g. 169.254.169.254), or unsafe network ports.
"""

import ipaddress
import socket
import urllib.parse
from typing import List, Optional, Tuple


class SSRFSecurityError(ValueError):
    """Raised when a URL violates SSRF security boundaries."""
    pass


# Disallowed IPv4 and IPv6 networks
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),        # Private IPv4 (Class A)
    ipaddress.ip_network("172.16.0.0/12"),     # Private IPv4 (Class B)
    ipaddress.ip_network("192.168.0.0/16"),    # Private IPv4 (Class C)
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("0.0.0.0/8"),         # Broadcast / current network
    ipaddress.ip_network("100.64.0.0/10"),     # Shared address space (Carrier-grade NAT)
    ipaddress.ip_network("192.0.0.0/24"),      # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved / Future use
    ipaddress.ip_network("::1/128"),           # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),          # Unique Local Address (ULA) IPv6
    ipaddress.ip_network("fe80::/10"),         # Link-local IPv6
    ipaddress.ip_network("ff00::/8"),          # Multicast IPv6
]

DEFAULT_ALLOWED_PORTS = [80, 443, 8080, 8443]


def is_ip_blocked(ip_addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address falls into any blocked or private network range."""
    for network in BLOCKED_NETWORKS:
        if ip_addr in network:
            return True
    return False


def resolve_and_validate_hostname(hostname: str) -> List[str]:
    """Resolve a hostname via DNS and verify that none of the resolved IPs are private/blocked."""
    try:
        # Resolve all addresses
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFSecurityError(f"DNS resolution failed for hostname '{hostname}': {e}")

    validated_ips: List[str] = []
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFSecurityError(f"Invalid resolved IP string '{ip_str}' for hostname '{hostname}'")

        if is_ip_blocked(ip_obj):
            raise SSRFSecurityError(
                f"Hostname '{hostname}' resolved to blocked/private IP '{ip_str}'."
            )
        validated_ips.append(ip_str)

    if not validated_ips:
        raise SSRFSecurityError(f"Hostname '{hostname}' did not resolve to any IP addresses.")

    return validated_ips


def validate_url(
    url: str,
    allowed_ports: Optional[List[int]] = None,
    block_private_ips: bool = True
) -> str:
    """Validate that a URL is safe to fetch and does not point to internal/SSRF targets.
    
    Returns the normalized URL string if valid.
    Raises SSRFSecurityError if unsafe.
    """
    if not url or not isinstance(url, str):
        raise SSRFSecurityError("URL must be a non-empty string.")

    cleaned_url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(cleaned_url)
    except Exception as e:
        raise SSRFSecurityError(f"Malformed URL '{cleaned_url}': {e}")

    # 1. Scheme check: only http and https allowed
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SSRFSecurityError(
            f"Invalid scheme '{scheme}'. Only HTTP and HTTPS protocols are permitted."
        )

    # 2. Reject embedded user credentials (e.g. http://user:pass@example.com)
    if parsed.username or parsed.password:
        raise SSRFSecurityError("URLs containing user credentials are not allowed.")

    # 3. Hostname check
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise SSRFSecurityError("URL missing hostname.")

    # Explicit check for localhost string
    if hostname in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
        raise SSRFSecurityError(f"Connection to localhost '{hostname}' is blocked.")

    # 4. Port check
    ports = allowed_ports or DEFAULT_ALLOWED_PORTS
    port = parsed.port
    if port is not None and port not in ports:
        raise SSRFSecurityError(
            f"Port {port} is not allowed. Permitted ports: {ports}."
        )

    # 5. IP verification / DNS resolution
    if block_private_ips:
        # Check if hostname is directly an IP literal
        try:
            direct_ip = ipaddress.ip_address(hostname.strip("[]"))
            if is_ip_blocked(direct_ip):
                raise SSRFSecurityError(f"Direct IP target '{hostname}' is blocked.")
        except ValueError:
            # Not an IP literal, resolve via DNS
            resolve_and_validate_hostname(hostname)

    return cleaned_url

