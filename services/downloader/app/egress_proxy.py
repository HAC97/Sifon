"""Loopback HTTP/HTTPS forward proxy that refuses private destinations.

yt-dlp does its own DNS lookups and follows redirects inside its network handlers, so a check
done once on the URL the user typed proves nothing about where the bytes really go. Every
yt-dlp request is therefore sent through this proxy. For each connection it resolves the host
itself, refuses the connection if ANY resolved address is not a public one, and then connects
to the address it checked (never resolving again), so redirects and DNS rebinding cannot reach
a private network. It only listens on 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from typing import Callable
from urllib.parse import urlsplit

from app.urlcheck import is_blocked_ip

BLOCKED_REASON = "sifon-blocked-address"  # matched by app.errors.map_error
MAX_HEAD_BYTES = 64 * 1024
HEAD_TIMEOUT = 30.0
CONNECT_TIMEOUT = 20.0
IDLE_TIMEOUT = 120.0

Resolver = Callable[..., list]


class _Refused(Exception):
    def __init__(self, status: int, reason: str):
        self.status = status
        self.reason = reason


def _response(status: int, reason: str) -> bytes:
    return f"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode("ascii")


class EgressProxy:
    def __init__(
        self,
        resolver: Resolver = socket.getaddrinfo,
        is_blocked: Callable = is_blocked_ip,
    ):
        self._resolver = resolver
        self._is_blocked = is_blocked
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self.port: int | None = None

    @property
    def url(self) -> str | None:
        return f"http://127.0.0.1:{self.port}" if self.port else None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="egress-proxy", daemon=True)
        self._thread.start()
        if not self._ready.wait(10) or self._error is not None:
            raise RuntimeError("could not start the egress proxy") from self._error

    def stop(self) -> None:
        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        self._thread = None
        self.port = None

    # -- internals ---------------------------------------------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._server = loop.run_until_complete(
                asyncio.start_server(self._handle, "127.0.0.1", 0, family=socket.AF_INET)
            )
            self.port = self._server.sockets[0].getsockname()[1]
        except BaseException as exc:  # reported to start()
            self._error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            self._server.close()
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(asyncio.sleep(0))
            loop.close()

    async def _resolve_checked(self, host: str, port: int) -> list[str]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.run_in_executor(None, lambda: self._resolver(host, port, type=socket.SOCK_STREAM))
        except (socket.gaierror, UnicodeError, OSError):
            raise _Refused(502, "Bad Gateway") from None
        addresses: list[str] = []
        for info in infos:
            address = info[4][0].split("%")[0]
            if self._is_blocked(ipaddress.ip_address(address)):
                raise _Refused(403, BLOCKED_REASON)
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise _Refused(502, "Bad Gateway")
        return addresses

    async def _connect(self, host: str, port: int):
        addresses = await self._resolve_checked(host, port)
        for address in addresses:
            try:
                return await asyncio.wait_for(asyncio.open_connection(address, port), CONNECT_TIMEOUT)
            except (OSError, asyncio.TimeoutError):
                continue
        raise _Refused(502, "Bad Gateway")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_writer = None
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
                raise _Refused(400, "Bad Request") from None
            if len(head) > MAX_HEAD_BYTES:
                raise _Refused(400, "Bad Request")
            lines = head.decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            if len(parts) != 3:
                raise _Refused(400, "Bad Request")
            method, target, version = parts

            if method.upper() == "CONNECT":
                host, _, port_text = target.rpartition(":")
                host = host.strip("[]")
                if not host or not port_text.isdigit():
                    raise _Refused(400, "Bad Request")
                upstream_reader, upstream_writer = await self._connect(host, int(port_text))
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
                await self._tunnel(reader, writer, upstream_reader, upstream_writer)
                return

            split = urlsplit(target)
            if split.scheme != "http" or not split.hostname:
                raise _Refused(400, "Bad Request")
            port = split.port or 80
            upstream_reader, upstream_writer = await self._connect(split.hostname, port)
            path = split.path or "/"
            if split.query:
                path += "?" + split.query
            kept = [
                line
                for line in lines[1:-2]
                if line and line.split(":", 1)[0].strip().lower() not in ("proxy-connection", "connection")
            ]
            rewritten = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close", "", ""])
            upstream_writer.write(rewritten.encode("latin-1"))
            await upstream_writer.drain()
            await self._tunnel(reader, writer, upstream_reader, upstream_writer)
        except _Refused as refusal:
            try:
                writer.write(_response(refusal.status, refusal.reason))
                await writer.drain()
            except OSError:
                pass
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            for w in (writer, upstream_writer):
                if w is not None:
                    try:
                        w.close()
                    except OSError:
                        pass

    @staticmethod
    async def _pipe(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await asyncio.wait_for(source.read(65536), IDLE_TIMEOUT)
                if not data:
                    break
                sink.write(data)
                await sink.drain()
        except (OSError, asyncio.TimeoutError):
            pass

    async def _tunnel(self, client_r, client_w, upstream_r, upstream_w) -> None:
        tasks = [
            asyncio.ensure_future(self._pipe(client_r, upstream_w)),
            asyncio.ensure_future(self._pipe(upstream_r, client_w)),
        ]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
