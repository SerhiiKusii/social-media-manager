from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from trendstealer import repo
from trendstealer.logging import get_logger
from trendstealer.metrics.instagram_insights import MediaInsights

logger = get_logger(__name__)

FetchInsights = Callable[[str], MediaInsights]


def run_metrics_once(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    fetch_insights: FetchInsights,
    min_age_hours: int = 24,
    now: datetime | None = None,
) -> int:
    """Snapshots insights for every published item that doesn't already
    have one from the last min_age_hours. fetch_insights takes a
    platform_media_id and is injected so callers choose live vs. dry-run
    without this module knowing about Graph API credentials."""
    now = now or datetime.now(UTC)
    due = repo.list_publications_needing_snapshot(
        conn, brand_id=brand_id, min_age_hours=min_age_hours, now=now
    )

    count = 0
    for publication in due:
        try:
            insights = fetch_insights(publication["platform_media_id"])
        except Exception:
            logger.warning("metrics_fetch_failed", publication_id=publication["id"])
            continue

        repo.create_metrics_snapshot(
            conn,
            publication_id=publication["id"],
            captured_at=now,
            views=insights.views,
            likes=insights.likes,
            comments=insights.comments,
            shares=insights.shares,
            saves=insights.saves,
            reach=insights.reach,
        )
        count += 1

    return count
