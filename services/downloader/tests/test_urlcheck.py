import socket

import pytest

from app.errors import DownloadFailure, ErrorCode
from app.urlcheck import validate_url


def resolver_for(*ips):
    def _resolve(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
            for ip in ips
        ]

    return _resolve


PUBLIC = resolver_for("93.184.216.34")


def test_accepts_public_https_url():
    url = "https://example.com/watch?v=1"
    assert validate_url(url, PUBLIC) == url


def test_accepts_http_and_strips_outer_whitespace():
    assert validate_url("  http://example.com/a \n", PUBLIC) == "http://example.com/a"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ftp://example.com/a",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "youtube.com/watch?v=1",
        "http://",
        "https://",
        "https://exa mple.com/",
        "https://example.com/a\nb",
        "https://example.com/" + "a" * 3000,
        "http://[::1",
    ],
)
def test_rejects_malformed_urls(bad):
    with pytest.raises(DownloadFailure) as exc:
        validate_url(bad, PUBLIC)
    assert exc.value.code == ErrorCode.INVALID_URL


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_hosts_resolving_to_non_public_addresses(ip):
    with pytest.raises(DownloadFailure) as exc:
        validate_url("https://innocent.example/v", resolver_for(ip))
    assert exc.value.code == ErrorCode.INVALID_URL


def test_rejects_decimal_ip_host_that_resolves_to_loopback():
    with pytest.raises(DownloadFailure):
        validate_url("http://2130706433/", resolver_for("127.0.0.1"))


def test_rejects_when_any_resolved_address_is_private():
    with pytest.raises(DownloadFailure):
        validate_url("https://rebind.example/v", resolver_for("93.184.216.34", "10.0.0.1"))


def test_rejects_unresolvable_host():
    def boom(host, port, *args, **kwargs):
        raise socket.gaierror("no such host")

    with pytest.raises(DownloadFailure) as exc:
        validate_url("https://does-not-exist.invalid/v", boom)
    assert exc.value.code == ErrorCode.INVALID_URL
