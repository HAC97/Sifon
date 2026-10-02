"""The egress proxy must stop redirects and DNS tricks from reaching private addresses.

127.0.0.1 plays "the public internet" and 127.0.0.2 plays "the private network": the test
blocker allows only the first, so no real private network is touched.
"""
import http.server
import socket
import threading
import urllib.error
import urllib.request

import pytest
import yt_dlp
from yt_dlp.networking.exceptions import HTTPError, RequestError

from app.egress_proxy import BLOCKED_REASON, EgressProxy
from app.errors import ErrorCode, map_error

PUBLIC, PRIVATE = "127.0.0.1", "127.0.0.2"


def allow_only_public(ip) -> bool:
    return str(ip) != PUBLIC


class _QuickBindServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind does a reverse DNS lookup (getfqdn) that takes seconds on Windows.
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]


class Server:
    def __init__(self, address, routes):
        self.hits: list[str] = []
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                status, headers, body = routes[self.path]
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = _QuickBindServer((address, 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def world():
    """A 'public' server whose /redirect points at a 'private' server on the same port number."""
    private = Server(PRIVATE, {"/secret": (200, {}, b"internal data")})
    public = Server(
        PUBLIC,
        {
            "/ok": (200, {}, b"hello"),
            "/redirect": (302, {"Location": f"http://{PRIVATE}:{private.port}/secret"}, b""),
        },
    )
    calls: list[str] = []
    table = {"public.test": PUBLIC, "private.test": PRIVATE}

    def resolver(host, port, *args, **kwargs):
        calls.append(host)
        ip = table.get(host, host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    proxy = EgressProxy(resolver=resolver, is_blocked=allow_only_public)
    proxy.start()
    yield proxy, public, private, calls, table
    proxy.stop()
    public.close()
    private.close()


def opener(proxy):
    handler = urllib.request.ProxyHandler({"http": proxy.url})
    return urllib.request.build_opener(handler)


def test_proxy_listens_only_on_loopback(world):
    proxy = world[0]
    assert proxy.url.startswith("http://127.0.0.1:")
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=2):
        pass


def test_public_http_request_is_forwarded(world):
    proxy, public, *_ = world
    with opener(proxy).open(f"http://public.test:{public.port}/ok", timeout=5) as res:
        assert res.read() == b"hello"
    assert public.hits == ["/ok"]


def test_private_destination_is_refused_and_never_contacted(world):
    proxy, _, private, *_ = world
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener(proxy).open(f"http://private.test:{private.port}/secret", timeout=5)
    assert caught.value.code == 403
    assert caught.value.reason == BLOCKED_REASON
    assert private.hits == []


def test_ip_literal_private_destination_is_refused(world):
    proxy, _, private, *_ = world
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener(proxy).open(f"http://{PRIVATE}:{private.port}/secret", timeout=5)
    assert caught.value.code == 403
    assert private.hits == []


def test_redirect_from_a_public_host_to_a_private_one_is_blocked(world):
    proxy, public, private, *_ = world
    with pytest.raises(urllib.error.HTTPError) as caught:
        opener(proxy).open(f"http://public.test:{public.port}/redirect", timeout=5)
    assert caught.value.code == 403
    assert public.hits == ["/redirect"]
    assert private.hits == []


def test_a_mixed_dns_answer_is_refused_if_any_address_is_private(world):
    proxy, public, private, calls, table = world

    def mixed(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PRIVATE, port)),
        ]

    mixed_proxy = EgressProxy(resolver=mixed, is_blocked=allow_only_public)
    mixed_proxy.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            opener(mixed_proxy).open(f"http://anything.test:{public.port}/ok", timeout=5)
        assert caught.value.code == 403
        assert public.hits == []
    finally:
        mixed_proxy.stop()


def test_dns_is_resolved_once_and_the_checked_address_is_the_one_used():
    """A rebinding name: public on the first lookup, private on every later one."""
    public = Server(PUBLIC, {"/ok": (200, {}, b"hello")})
    private = Server(PRIVATE, {"/ok": (200, {}, b"internal")})
    lookups = []

    def rebinding(host, port, *args, **kwargs):
        lookups.append(host)
        ip = PUBLIC if len(lookups) == 1 else PRIVATE
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    proxy = EgressProxy(resolver=rebinding, is_blocked=allow_only_public)
    proxy.start()
    try:
        # Same port on both servers is not guaranteed, so point the request at the public one.
        with opener(proxy).open(f"http://rebind.test:{public.port}/ok", timeout=5) as res:
            assert res.read() == b"hello"
        assert len(lookups) == 1  # the proxy did not resolve a second time to connect
        assert private.hits == []
    finally:
        proxy.stop()
        public.close()
        private.close()


def raw_exchange(proxy, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
        sock.sendall(payload)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)


def test_connect_to_a_private_address_gets_403(world):
    proxy, _, private, *_ = world
    reply = raw_exchange(proxy, f"CONNECT private.test:{private.port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    assert reply.startswith(f"HTTP/1.1 403 {BLOCKED_REASON}".encode())
    assert private.hits == []


def test_connect_to_a_public_address_opens_a_tunnel(world):
    proxy, public, *_ = world
    with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
        sock.sendall(f"CONNECT public.test:{public.port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert sock.recv(1024).startswith(b"HTTP/1.1 200")
        sock.sendall(b"GET /ok HTTP/1.1\r\nHost: public.test\r\nConnection: close\r\n\r\n")
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    assert data.endswith(b"hello")


@pytest.mark.parametrize(
    "request_line",
    ["GET /relative HTTP/1.1", "GET ftp://public.test/x HTTP/1.1", "GARBAGE", "CONNECT nohost HTTP/1.1"],
)
def test_malformed_or_unsupported_requests_get_400(world, request_line):
    reply = raw_exchange(world[0], f"{request_line}\r\nHost: x\r\n\r\n".encode())
    assert reply.startswith(b"HTTP/1.1 400")


def test_unresolvable_host_gets_502(world):
    proxy, *_ = world

    def failing(host, port, *args, **kwargs):
        raise socket.gaierror("no such host")

    broken = EgressProxy(resolver=failing, is_blocked=allow_only_public)
    broken.start()
    try:
        assert raw_exchange(broken, b"GET http://nope.test/ HTTP/1.1\r\nHost: nope.test\r\n\r\n").startswith(b"HTTP/1.1 502")
    finally:
        broken.stop()


def test_ytdlp_through_the_proxy_reaches_public_and_is_blocked_on_redirect(world):
    """The real yt-dlp network stack, not just urllib, must honor the proxy."""
    proxy, public, private, *_ = world
    with yt_dlp.YoutubeDL({"proxy": proxy.url, "quiet": True}) as ydl:
        res = ydl.urlopen(f"http://public.test:{public.port}/ok")
        assert res.read() == b"hello"
        with pytest.raises((HTTPError, RequestError)) as caught:
            ydl.urlopen(f"http://public.test:{public.port}/redirect")
    assert private.hits == []
    assert BLOCKED_REASON in str(caught.value) or "403" in str(caught.value)


def test_the_refusal_reason_maps_to_blocked_address():
    assert map_error(f"Tunnel connection failed: 403 {BLOCKED_REASON}") == ErrorCode.BLOCKED_ADDRESS
    assert map_error(f"HTTP Error 403: {BLOCKED_REASON}") == ErrorCode.BLOCKED_ADDRESS


def test_stop_releases_the_port():
    proxy = EgressProxy()
    proxy.start()
    port = proxy.port
    proxy.stop()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)
