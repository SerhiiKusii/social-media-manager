from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx

from trendstealer import repo
from trendstealer.assetlib.pexels import (
    PEXELS_LICENSE,
    download_video,
    search_videos,
)
from trendstealer.config import REPO_ROOT
from trendstealer.logging import get_logger

logger = get_logger(__name__)

ASSETS_VIDEO_DIR = REPO_ROOT / "assets" / "video"
ASSETS_PHOTO_DIR = REPO_ROOT / "assets" / "photos"


@dataclass
class FetchSummary:
    found: int = 0
    downloaded: int = 0
    registered: int = 0


def fetch_pexels_broll(
    conn: sqlite3.Connection,
    *,
    query: str,
    api_key: str,
    count: int = 5,
    tags: str | None = None,
    client: httpx.Client | None = None,
    dest_dir: Path | None = None,
) -> FetchSummary:
    """Download stock clips and register them as cleared B-roll."""
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    dest_dir = dest_dir or ASSETS_VIDEO_DIR
    summary = FetchSummary()

    videos = search_videos(query=query, api_key=api_key, client=client)
    summary.found = len(videos)

    for video in videos[:count]:
        path = download_video(video, dest_dir, client=client)
        summary.downloaded += 1
        repo.upsert_asset(
            conn,
            # Stored relative to the repo root so the DB stays portable
            # across machines and the systemd WorkingDirectory.
            path=str(path.relative_to(REPO_ROOT)),
            kind="video",
            license=PEXELS_LICENSE,
            tags=tags or query.replace(" ", "-"),
            attribution=video.attribution,
            cleared_for_commercial=True,
        )
        summary.registered += 1

    return summary


def register_local_asset(
    conn: sqlite3.Connection,
    *,
    path: Path,
    kind: str,
    license: str,  # noqa: A002 - matches the column name
    tags: str | None = None,
    attribution: str | None = None,
    cleared_for_commercial: bool = False,
) -> int:
    """Register a file already on disk (your own footage, a licensed photo).

    Refuses anything outside assets/ -- render/props.py would reject such a
    path at render time anyway, so failing here gives a clearer error than
    a surprise UnclearedAssetPathError three steps later.
    """
    resolved = path.resolve()
    assets_root = (REPO_ROOT / "assets").resolve()
    if not resolved.is_relative_to(assets_root):
        raise ValueError(f"{path} is outside assets/ -- copy it there first")

    return repo.upsert_asset(
        conn,
        path=str(resolved.relative_to(REPO_ROOT)),
        kind=kind,
        license=license,
        tags=tags,
        attribution=attribution,
        cleared_for_commercial=cleared_for_commercial,
    )
