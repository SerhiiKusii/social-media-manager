"""Raw Apify actor output -> TrendCandidate.

Field names here are a best-effort mapping for clockworks/tiktok-scraper
and apify/instagram-scraper and must be verified against the actor's
current output schema in the Apify Console before going live (M0) --
scraper actors change their output shape without notice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class TrendCandidate:
    platform: str
    platform_video_id: str
    source_account: str | None
    source_url: str | None
    caption: str | None
    transcript: str | None
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    source_follower_count: int | None
    duration_secs: float | None
    posted_at: str | None  # ISO 8601
    audio_id: str | None
    audio_url: str | None  # transient analysis input only; never persisted


def with_transcript(candidate: TrendCandidate, transcript: str | None) -> TrendCandidate:
    return replace(candidate, transcript=transcript)


def _epoch_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def normalize_tiktok(raw: dict[str, Any]) -> TrendCandidate:
    author = raw.get("authorMeta") or {}
    music = raw.get("musicMeta") or {}
    video_meta = raw.get("videoMeta") or {}
    return TrendCandidate(
        platform="tiktok",
        platform_video_id=str(raw.get("id")),
        source_account=author.get("name"),
        source_url=raw.get("webVideoUrl"),
        caption=raw.get("text"),
        transcript=raw.get("transcript"),
        views=raw.get("playCount"),
        likes=raw.get("diggCount"),
        comments=raw.get("commentCount"),
        shares=raw.get("shareCount"),
        source_follower_count=author.get("fans"),
        duration_secs=video_meta.get("duration"),
        posted_at=_epoch_to_iso(raw.get("createTime")),
        audio_id=music.get("musicId"),
        audio_url=raw.get("videoUrl") or video_meta.get("downloadAddr"),
    )


def normalize_instagram(raw: dict[str, Any]) -> TrendCandidate:
    return TrendCandidate(
        platform="instagram",
        platform_video_id=str(raw.get("id") or raw.get("shortCode")),
        source_account=raw.get("ownerUsername"),
        source_url=raw.get("url"),
        caption=raw.get("caption"),
        transcript=raw.get("transcript"),
        views=raw.get("videoPlayCount") or raw.get("videoViewCount"),
        likes=raw.get("likesCount"),
        comments=raw.get("commentsCount"),
        shares=None,
        source_follower_count=None,
        duration_secs=raw.get("videoDuration"),
        posted_at=raw.get("timestamp"),
        audio_id=None,
        audio_url=raw.get("videoUrl"),
    )
