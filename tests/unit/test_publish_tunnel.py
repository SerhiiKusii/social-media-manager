"""Tests for the local half of the disposable video host.

The cloudflared/edge half needs the network and is exercised by the live
publish path, not here. What is testable offline -- and what actually
broke against the real Graph API -- is the request handling: Meta's
fetcher issues HEAD and Range requests, and an early version of this
handler answered only whole-file GET.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from trendstealer.publish.tunnel import (
    TunnelError,
    _parse_range,
    _single_file_handler,
    _wait_for_tunnel_url,
)

CONTENT = bytes(range(256)) * 40  # 10240 bytes


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "out_r0.mp4"
    path.write_bytes(CONTENT)
    return path


@pytest.fixture
def server(video: Path) -> Iterator[tuple[str, int]]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _single_file_handler(video))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", httpd.server_address[1]
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _request(
    server: tuple[str, int], method: str, path: str, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    conn = HTTPConnection(server[0], server[1], timeout=10)
    conn.request(method, path, headers=headers or {})
    response = conn.getresponse()
    body = response.read()
    result = (response.status, dict(response.getheaders()), body)
    conn.close()
    return result


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=500-", 1000, (500, 999)),
        ("bytes=-100", 1000, (900, 999)),
        ("bytes=0-99999", 1000, (0, 999)),  # end clamped to the file
        ("bytes=900-100", 1000, None),  # start after end
        ("bytes=-", 1000, None),
        ("nonsense", 1000, None),
    ],
)
def test_parse_range(header: str, size: int, expected: tuple[int, int] | None) -> None:
    assert _parse_range(header, size) == expected


def test_get_serves_the_whole_file(server: tuple[str, int]) -> None:
    status, headers, body = _request(server, "GET", "/out_r0.mp4")
    assert status == 200
    assert body == CONTENT
    assert headers["Content-Type"] == "video/mp4"
    assert headers["Content-Length"] == str(len(CONTENT))
    assert headers["Accept-Ranges"] == "bytes"


def test_head_returns_metadata_without_a_body(server: tuple[str, int]) -> None:
    status, headers, body = _request(server, "HEAD", "/out_r0.mp4")
    assert status == 200
    assert body == b""
    assert headers["Content-Length"] == str(len(CONTENT))


def test_range_request_returns_206_and_the_requested_slice(server: tuple[str, int]) -> None:
    status, headers, body = _request(
        server, "GET", "/out_r0.mp4", {"Range": "bytes=100-199"}
    )
    assert status == 206
    assert body == CONTENT[100:200]
    assert headers["Content-Range"] == f"bytes 100-199/{len(CONTENT)}"
    assert headers["Content-Length"] == "100"


def test_unsatisfiable_range_falls_back_to_the_whole_file(server: tuple[str, int]) -> None:
    status, _, body = _request(server, "GET", "/out_r0.mp4", {"Range": "bytes=900-100"})
    assert status == 200
    assert body == CONTENT


def test_other_paths_are_404(server: tuple[str, int]) -> None:
    status, _, _ = _request(server, "GET", "/secrets.env")
    assert status == 404


def test_query_string_does_not_defeat_the_path_match(server: tuple[str, int]) -> None:
    status, _, body = _request(server, "GET", "/out_r0.mp4?cachebust=1")
    assert status == 200
    assert body == CONTENT


class _FakeProc:
    """Stands in for subprocess.Popen[str]: readline() yields queued lines,
    then behaves like a still-running or exited process."""

    def __init__(self, lines: list[str], *, exit_code: int | None = None) -> None:
        self._lines = list(lines)
        self.returncode = exit_code

    def poll(self) -> int | None:
        return self.returncode if not self._lines else None

    @property
    def stdout(self) -> "_FakeProc":
        return self

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


def test_wait_for_tunnel_url_ignores_the_control_plane_host_in_a_failure_line() -> None:
    """Regression test: cloudflared's own error message for a failed quick-
    tunnel request embeds https://api.trycloudflare.com, which matches the
    tunnel-URL regex just like a real assigned subdomain would. That must
    not be mistaken for a successful tunnel -- it previously was, sending
    the caller off to poll a URL that could never work instead of surfacing
    cloudflared's actual failure."""
    proc = _FakeProc(
        [
            "INF Requesting new quick Tunnel on trycloudflare.com...\n",
            'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel":'
            " unexpected EOF\n",
        ],
        exit_code=1,
    )
    with pytest.raises(TunnelError, match="cloudflared failed to create a quick tunnel"):
        _wait_for_tunnel_url(proc)  # type: ignore[arg-type]


def test_wait_for_tunnel_url_returns_a_real_assigned_subdomain() -> None:
    proc = _FakeProc(
        [
            "INF Requesting new quick Tunnel on trycloudflare.com...\n",
            "|  https://random-words-here.trycloudflare.com  |\n",
        ]
    )
    assert _wait_for_tunnel_url(proc) == "https://random-words-here.trycloudflare.com"  # type: ignore[arg-type]
