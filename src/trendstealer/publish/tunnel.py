"""Disposable public hosting for one video file, for Instagram Login's
video_url-only upload path (see upload.py docstring). Serves the file over
a localhost HTTP server and exposes it via a Cloudflare "quick tunnel" --
a free, anonymous *.trycloudflare.com URL with no account or DNS setup,
torn down as soon as the caller is done with it.

Two things this has to get right, both learned the hard way against the
live Graph API:

1. Meta validates video_url *synchronously* when the container is created.
   cloudflared prints the URL before the Cloudflare edge will actually
   serve it ("it may take some time to be reachable"), so handing that URL
   straight to Meta gets the container marked ERROR within seconds. We
   poll the public URL ourselves and only yield once it answers.

2. facebookexternalhit may issue HEAD and Range requests, so the handler
   implements both rather than only whole-file GET.

Requires the cloudflared binary (see scripts/install-tools.sh or
.tools/cloudflared) on PATH or in .tools/.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from trendstealer.config import REPO_ROOT
from trendstealer.logging import get_logger

logger = get_logger(__name__)

_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# api.trycloudflare.com is Cloudflare's control-plane endpoint, not a tunnel
# hostname -- real quick-tunnel subdomains are random dictionary words and
# never literally "api". cloudflared prints it in its own failure message
# ("failed to request quick Tunnel: Post \"https://api.trycloudflare.com/tunnel\":
# unexpected EOF"), which otherwise matches the regex above and gets mistaken
# for a successfully assigned tunnel URL, sending the caller off to poll a
# URL that was never going to work instead of surfacing the real failure.
_CONTROL_PLANE_HOST = "api.trycloudflare.com"
_TUNNEL_START_TIMEOUT_SECS = 30.0
_REACHABLE_TIMEOUT_SECS = 90.0
_REACHABLE_POLL_SECS = 3.0
_CHUNK_BYTES = 256 * 1024

# Used only when the local resolver can't resolve the tunnel hostname --
# some DNS filters block trycloudflare.com wholesale, which would make the
# readiness probe fail even though Meta's resolvers are fine with it.
_DOH_ENDPOINT = "https://1.1.1.1/dns-query"


class TunnelError(RuntimeError):
    pass


def _find_cloudflared() -> str:
    local = REPO_ROOT / ".tools" / "cloudflared"
    if local.exists():
        return str(local)
    found = shutil.which("cloudflared")
    if found:
        return found
    raise TunnelError(
        "cloudflared not found (looked in .tools/cloudflared and PATH) -- "
        "see docs/RUNBOOK.md for install instructions"
    )


def _cloudflared_env() -> dict[str, str]:
    """cloudflared is a Go binary and negotiates HTTP/2 via ALPN by default
    for its "request a quick tunnel" API call. On networks where something
    in the path (a TLS-inspecting proxy/firewall) mangles HTTP/2 POST
    bodies, that call fails with a bare "unexpected EOF" and no tunnel is
    ever created -- plain HTTP/1.1 to the same endpoint works fine.
    GODEBUG=http2client=0 is a Go-runtime knob that forces the HTTP/2
    client off without needing a cloudflared rebuild or flag; it only
    affects this control-plane call, not the tunnel's own data transport
    (quic), so it's safe to set unconditionally rather than only on
    networks known to need it.
    """
    env = dict(os.environ)
    existing = env.get("GODEBUG", "")
    settings = [s for s in existing.split(",") if s and not s.startswith("http2client=")]
    settings.append("http2client=0")
    env["GODEBUG"] = ",".join(settings)
    return env


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Returns an inclusive (start, end) byte range, or None if unparseable."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match:
        return None
    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "":
        if raw_end == "":
            return None
        length = min(int(raw_end), size)
        return size - length, size - 1
    start = int(raw_start)
    end = int(raw_end) if raw_end else size - 1
    end = min(end, size - 1)
    if start > end:
        return None
    return start, end


def _single_file_handler(video_path: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _matches(self) -> bool:
            return urlsplit(self.path).path == f"/{video_path.name}"

        def _send_headers(self, status: int, length: int, extra: dict[str, str]) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib method name
            if not self._matches():
                self.send_error(404)
                return
            self._send_headers(200, video_path.stat().st_size, {})

        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            if not self._matches():
                self.send_error(404)
                return
            size = video_path.stat().st_size
            range_header = self.headers.get("Range")
            byte_range = _parse_range(range_header, size) if range_header else None

            if byte_range is None:
                start, end = 0, size - 1
                status = 200
                extra: dict[str, str] = {}
            else:
                start, end = byte_range
                status = 206
                extra = {"Content-Range": f"bytes {start}-{end}/{size}"}

            self._send_headers(status, end - start + 1, extra)
            with video_path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return Handler


def _resolve_via_doh(host: str) -> str | None:
    import httpx

    try:
        response = httpx.get(
            _DOH_ENDPOINT,
            params={"name": host, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=10.0,
        )
        answers = response.json().get("Answer", [])
    except (httpx.HTTPError, json.JSONDecodeError, KeyError):
        return None
    for answer in answers:
        if answer.get("type") == 1:
            return str(answer["data"])
    return None


def _resolve(host: str) -> str | None:
    try:
        return str(socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0])
    except socket.gaierror:
        return _resolve_via_doh(host)


def _probe_once(host: str, path: str, ip: str) -> bool:
    """One HEAD against the public edge, connecting to `ip` with SNI `host`
    so a blocked local resolver can't produce a false negative."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((ip, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                request = f"HEAD {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                tls.sendall(request.encode())
                status_line = tls.recv(256).decode(errors="replace").split("\r\n")[0]
    except (TimeoutError, OSError, ssl.SSLError):
        return False
    return " 200 " in status_line


def _wait_until_publicly_reachable(url: str) -> None:
    parts = urlsplit(url)
    host, path = parts.hostname, parts.path
    if host is None:
        raise TunnelError(f"could not parse host from tunnel URL {url!r}")

    deadline = time.monotonic() + _REACHABLE_TIMEOUT_SECS
    while time.monotonic() < deadline:
        ip = _resolve(host)
        if ip is not None and _probe_once(host, path, ip):
            return
        time.sleep(_REACHABLE_POLL_SECS)
    raise TunnelError(
        f"tunnel {url} did not become publicly reachable within "
        f"{_REACHABLE_TIMEOUT_SECS:.0f}s -- refusing to hand an unready URL to the "
        "Graph API (it validates video_url synchronously and fails the container)"
    )


@contextmanager
def serve_video_publicly(video_path: Path) -> Iterator[str]:
    """Yields a public https URL serving video_path, torn down on exit.

    Only yields once the URL actually answers from the public internet.
    The URL is anonymous and unguessable-but-not-secret (random subdomain,
    no auth) -- acceptable for a single-fetch handoff to Meta's servers
    immediately followed by teardown, not for standing hosting.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _single_file_handler(video_path))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    local_port = server.server_address[1]

    cloudflared = _find_cloudflared()
    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{local_port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=_cloudflared_env(),
    )
    try:
        public_base = _wait_for_tunnel_url(proc)
        url = f"{public_base}/{video_path.name}"
        _wait_until_publicly_reachable(url)
        logger.info("tunnel_ready", url=url, bytes=video_path.stat().st_size)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        server_thread.join(timeout=5)


def _wait_for_tunnel_url(proc: subprocess.Popen[str]) -> str:
    deadline = time.monotonic() + _TUNNEL_START_TIMEOUT_SECS
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise TunnelError(f"cloudflared exited early (code {proc.returncode})")
            continue
        match = _TUNNEL_URL_RE.search(line)
        if match and match.group(0) != f"https://{_CONTROL_PLANE_HOST}":
            return match.group(0)
        if _CONTROL_PLANE_HOST in line and ("failed" in line or "error" in line.lower()):
            raise TunnelError(f"cloudflared failed to create a quick tunnel: {line.strip()}")
    raise TunnelError("timed out waiting for cloudflared to print a tunnel URL")
