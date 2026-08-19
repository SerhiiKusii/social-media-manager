from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from trendstealer import repo
from trendstealer.assetlib.pexels import (
    PEXELS_API_BASE,
    PexelsError,
    PexelsVideo,
    _best_file,
    download_video,
    search_videos,
)
from trendstealer.commands.assets import fetch_pexels_broll, register_local_asset


def _video_entry(
    *, vid: int = 1, duration: int = 12, files: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": vid,
        "duration": duration,
        "url": f"https://www.pexels.com/video/{vid}/",
        "user": {"name": "Jane Doe"},
        "video_files": files
        if files is not None
        else [
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://cdn/x.mp4"}
        ],
    }


def test_best_file_prefers_portrait_over_a_bigger_landscape() -> None:
    best = _best_file(
        [
            {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "land"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "port"},
        ]
    )
    assert best is not None
    assert best["link"] == "port"


def test_best_file_prefers_the_smallest_rendition_that_still_covers_1920() -> None:
    best = _best_file(
        [
            {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "huge"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "just-right"},
            {"file_type": "video/mp4", "width": 360, "height": 640, "link": "tiny"},
        ]
    )
    assert best is not None
    assert best["link"] == "just-right"


def test_best_file_ignores_non_mp4_renditions() -> None:
    only_mov = [{"file_type": "video/quicktime", "link": "mov", "width": 1, "height": 2}]
    assert _best_file(only_mov) is None


@respx.mock
def test_search_videos_filters_by_duration() -> None:
    respx.get(f"{PEXELS_API_BASE}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "videos": [
                    _video_entry(vid=1, duration=3),  # too short
                    _video_entry(vid=2, duration=12),
                    _video_entry(vid=3, duration=600),  # too long
                ]
            },
        )
    )
    results = search_videos(query="football", api_key="k", client=httpx.Client())
    assert [v.pexels_id for v in results] == [2]


@respx.mock
def test_search_videos_requests_portrait_orientation() -> None:
    route = respx.get(f"{PEXELS_API_BASE}/search").mock(
        return_value=httpx.Response(200, json={"videos": []})
    )
    search_videos(query="football", api_key="k", client=httpx.Client())
    assert route.calls.last.request.url.params["orientation"] == "portrait"
    assert route.calls.last.request.headers["Authorization"] == "k"


@respx.mock
def test_search_videos_reports_a_bad_api_key_clearly() -> None:
    respx.get(f"{PEXELS_API_BASE}/search").mock(return_value=httpx.Response(401, text="nope"))
    with pytest.raises(PexelsError, match="PEXELS_API_KEY"):
        search_videos(query="football", api_key="bad", client=httpx.Client())


@respx.mock
def test_download_video_streams_to_disk(tmp_path: Path) -> None:
    respx.get("https://cdn/x.mp4").mock(return_value=httpx.Response(200, content=b"video-bytes"))
    video = PexelsVideo(
        pexels_id=7,
        width=1080,
        height=1920,
        duration_secs=10,
        download_url="https://cdn/x.mp4",
        author="Jane Doe",
        source_url="https://www.pexels.com/video/7/",
    )
    path = download_video(video, tmp_path, client=httpx.Client())
    assert path.read_bytes() == b"video-bytes"
    assert path.name == "pexels-7.mp4"
    assert not list(tmp_path.glob("*.part"))  # no partial left behind


@respx.mock
def test_download_video_leaves_no_partial_file_on_failure(tmp_path: Path) -> None:
    respx.get("https://cdn/x.mp4").mock(return_value=httpx.Response(500, text="boom"))
    video = PexelsVideo(
        pexels_id=8,
        width=1080,
        height=1920,
        duration_secs=10,
        download_url="https://cdn/x.mp4",
        author="Jane Doe",
        source_url="",
    )
    with pytest.raises(PexelsError):
        download_video(video, tmp_path, client=httpx.Client())
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_fetch_pexels_broll_registers_downloads_as_cleared(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.commands.assets as assets_mod

    monkeypatch.setattr(assets_mod, "REPO_ROOT", tmp_path)
    respx.get(f"{PEXELS_API_BASE}/search").mock(
        return_value=httpx.Response(200, json={"videos": [_video_entry(vid=42)]})
    )
    respx.get("https://cdn/x.mp4").mock(return_value=httpx.Response(200, content=b"bytes"))

    summary = fetch_pexels_broll(
        conn,
        query="football",
        api_key="k",
        client=httpx.Client(),
        dest_dir=tmp_path / "assets" / "video",
    )
    assert summary.registered == 1

    rows = repo.list_assets(conn, kind="video")
    assert len(rows) == 1
    assert rows[0]["cleared_for_commercial"] == 1
    assert rows[0]["license"] == "Pexels"
    assert "Jane Doe" in rows[0]["attribution"]
    assert rows[0]["tags"] == "football"


def test_register_local_asset_refuses_paths_outside_assets(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    stray = tmp_path / "somewhere.mp4"
    stray.write_bytes(b"x")
    with pytest.raises(ValueError, match="outside assets/"):
        register_local_asset(conn, path=stray, kind="video", license="unknown")
