"""Stock B-roll from Pexels.

This is the licensed-footage half of the compliance story: the pipeline
never republishes a scraped video (see render/props.py), so anything that
appears on screen has to come from a source we can actually point at a
licence for. The Pexels licence permits commercial use without
attribution, which is what lets these land with cleared_for_commercial=1
-- attribution is still recorded because crediting the creator is decent
practice and costs nothing.

Needs PEXELS_API_KEY (free: https://www.pexels.com/api/).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from trendstealer.logging import get_logger

logger = get_logger(__name__)

PEXELS_API_BASE = "https://api.pexels.com/videos"
PEXELS_LICENSE = "Pexels"

# Reels are 1080x1920. A landscape clip cropped to vertical loses most of
# the frame, so portrait is requested and used as a ranking signal too.
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class PexelsError(RuntimeError):
    pass


@dataclass(frozen=True)
class PexelsVideo:
    pexels_id: int
    width: int
    height: int
    duration_secs: int
    download_url: str
    author: str
    source_url: str

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def attribution(self) -> str:
        return f"{self.author} on Pexels ({self.source_url})"


def _best_file(video_files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the mp4 closest to 1080x1920 without going below it.

    Pexels returns several renditions per video; the largest is often 4K
    (needless bytes and slow to render), and the smallest is frequently
    360p (visibly soft on a phone). Preference order: portrait first, then
    the smallest rendition that still covers the target height.
    """
    mp4s = [f for f in video_files if f.get("file_type") == "video/mp4" and f.get("link")]
    if not mp4s:
        return None

    def sort_key(f: dict[str, Any]) -> tuple[int, int, int]:
        width = int(f.get("width") or 0)
        height = int(f.get("height") or 0)
        portrait_first = 0 if height > width else 1
        big_enough_first = 0 if height >= TARGET_HEIGHT else 1
        return (portrait_first, big_enough_first, height)

    return sorted(mp4s, key=sort_key)[0]


def search_videos(
    *,
    query: str,
    api_key: str,
    client: httpx.Client,
    per_page: int = 15,
    min_duration_secs: int = 5,
    max_duration_secs: int = 60,
) -> list[PexelsVideo]:
    response = client.get(
        f"{PEXELS_API_BASE}/search",
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        headers={"Authorization": api_key},
    )
    if response.status_code == 401:
        raise PexelsError("Pexels rejected the API key (401) -- check PEXELS_API_KEY")
    if response.status_code >= 400:
        raise PexelsError(f"Pexels API error {response.status_code}: {response.text[:200]}")

    results: list[PexelsVideo] = []
    for entry in response.json().get("videos", []):
        duration = int(entry.get("duration") or 0)
        if not (min_duration_secs <= duration <= max_duration_secs):
            continue
        best = _best_file(entry.get("video_files", []))
        if best is None:
            continue
        results.append(
            PexelsVideo(
                pexels_id=int(entry["id"]),
                width=int(best.get("width") or 0),
                height=int(best.get("height") or 0),
                duration_secs=duration,
                download_url=str(best["link"]),
                author=str((entry.get("user") or {}).get("name") or "unknown"),
                source_url=str(entry.get("url") or ""),
            )
        )
    return results


def download_video(video: PexelsVideo, dest_dir: Path, *, client: httpx.Client) -> Path:
    """Streams to disk -- these are tens of MB and should not be buffered."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"pexels-{video.pexels_id}.mp4"
    if dest.exists():
        logger.info("pexels_download_skipped_exists", path=str(dest))
        return dest

    tmp = dest.with_suffix(".part")
    try:
        with client.stream("GET", video.download_url) as response:
            if response.status_code >= 400:
                raise PexelsError(
                    f"download failed for {video.pexels_id}: HTTP {response.status_code}"
                )
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes(chunk_size=256 * 1024):
                    f.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)

    logger.info("pexels_downloaded", path=str(dest), bytes=dest.stat().st_size)
    return dest
