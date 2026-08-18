"""Reads the persisted publications ledger, not timer cadence, so a laptop
asleep past several windows can't dump the whole approved queue at once on
wake -- see the "Persistent=true burst" problem in the plan's load-bearing
problems table.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from trendstealer import repo
from trendstealer.config import BrandConfig, BrandPostingWindows


@dataclass(frozen=True)
class RateLimitVerdict:
    allowed: bool
    reason: str | None = None


def check_rate_limit(
    conn: sqlite3.Connection, *, brand_id: int, brand: BrandConfig, now: datetime
) -> RateLimitVerdict:
    published_24h = repo.count_published_last_24h(conn, brand_id=brand_id, now=now)
    if published_24h >= brand.publish.max_posts_per_day:
        return RateLimitVerdict(False, "max_posts_per_day reached")

    last_published_at = repo.get_last_publication_time(conn, brand_id=brand_id)
    if last_published_at is not None:
        gap_minutes = (now - last_published_at).total_seconds() / 60
        if gap_minutes < brand.publish.min_gap_minutes:
            return RateLimitVerdict(False, "min_gap_minutes not elapsed")

    if not _within_posting_window(now, brand.posting_windows):
        return RateLimitVerdict(False, "outside posting window")

    return RateLimitVerdict(True)


def _within_posting_window(now: datetime, posting_windows: BrandPostingWindows) -> bool:
    if not posting_windows.windows:
        return True
    local_now = now.astimezone(ZoneInfo(posting_windows.timezone))
    current_minutes = local_now.hour * 60 + local_now.minute
    for window in posting_windows.windows:
        start_str, end_str = window.split("-")
        if _to_minutes(start_str) <= current_minutes <= _to_minutes(end_str):
            return True
    return False


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)
