import ipaddress
import socket
from urllib.parse import urlsplit

from app.errors import DownloadFailure, ErrorCode

MAX_URL_LENGTH = 2048


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
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
