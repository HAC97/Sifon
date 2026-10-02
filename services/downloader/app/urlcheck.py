import ipaddress
import socket
from urllib.parse import urlsplit

from app.errors import DownloadFailure, ErrorCode

MAX_URL_LENGTH = 2048

# Ranges `is_global` still reports as public although a download has no business going there.
_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(net)
    for net in (
        "fec0::/10",       # deprecated site-local IPv6
        "192.88.99.0/24",  # deprecated 6to4 relay anycast
        "5f00::/16",       # SRv6 segment identifiers
    )
)
# IPv6 blocks that carry an IPv4 address in their last 32 bits. A NAT64 gateway or a dual-stack
# host would deliver the packet to that IPv4 address, so the embedded address is judged instead.
_EMBEDDING_V4 = tuple(
    ipaddress.ip_network(net)
    for net in (
        "::/96",            # IPv4-compatible (deprecated)
        "64:ff9b::/96",     # NAT64 well-known prefix
        "::ffff:0:0:0/96",  # SIIT translated
    )
)
_UNSPECIFIED_V6 = ipaddress.IPv6Address("::")


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6:
        if ip.ipv4_mapped:
            return is_blocked_ip(ip.ipv4_mapped)
        if ip != _UNSPECIFIED_V6 and any(ip in net for net in _EMBEDDING_V4):
            return is_blocked_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED):
        return True
    return (not ip.is_global) or ip.is_multicast


def validate_url(url: str, resolver=socket.getaddrinfo) -> str:
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in url):
        raise DownloadFailure(ErrorCode.INVALID_URL)
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise DownloadFailure(ErrorCode.INVALID_URL) from None
    if parts.scheme not in ("http", "https") or not host:
        raise DownloadFailure(ErrorCode.INVALID_URL)
    try:
        infos = resolver(host, None)
    except (socket.gaierror, UnicodeError):
        raise DownloadFailure(ErrorCode.INVALID_URL, "No se pudo resolver el host de la URL.") from None
    for info in infos:
        address = info[4][0].split("%")[0]
        if is_blocked_ip(ipaddress.ip_address(address)):
            raise DownloadFailure(
                ErrorCode.INVALID_URL,
                "Esa dirección apunta a una red local o reservada y está bloqueada.",
            )
    return url
