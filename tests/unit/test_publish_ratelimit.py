import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from trendstealer import repo
from trendstealer.config import (
    BrandConfig,
    BrandIdentity,
    BrandPostingWindows,
    PublishConfig,
    ViralityConfig,
)
from trendstealer.publish.ratelimit import check_rate_limit


@pytest.fixture
def brand_id(conn: sqlite3.Connection) -> int:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    repo.upsert_account(conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1")
    return brand_id


def _brand(**publish_overrides: object) -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        posting_windows=BrandPostingWindows(windows=[], timezone="UTC"),
        virality=ViralityConfig(),
        publish=PublishConfig(
            **{"max_posts_per_day": 2, "min_gap_minutes": 240, **publish_overrides}
        ),
    )


def _make_item_and_revision(
    conn: sqlite3.Connection, brand_id: int, suffix: str
) -> tuple[int, int]:
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id, f"vid-{suffix}"),
    )
    trend_id = conn.execute(
        "SELECT id FROM trends WHERE platform_video_id = ?", (f"vid-{suffix}",)
    ).fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook="hook",
        spoken_script="script",
    )
    return item_id, revision_id


def _record_publication(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    item_id: int,
    revision_id: int,
    published_at: datetime,
) -> None:
    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1"
    )
    repo.create_publication(
        conn,
        content_item_id=item_id,
        revision_id=revision_id,
        brand_id=brand_id,
        platform="instagram",
        account_id=account_id,
        idempotency_key=f"key-{item_id}-{revision_id}",
        platform_media_id="media-1",
        status="published",
        published_at=published_at,
    )


def test_allowed_when_no_prior_publications(conn: sqlite3.Connection, brand_id: int) -> None:
    verdict = check_rate_limit(conn, brand_id=brand_id, brand=_brand(), now=datetime.now(UTC))
    assert verdict.allowed


def test_denied_once_daily_cap_reached(conn: sqlite3.Connection, brand_id: int) -> None:
    now = datetime.now(UTC)
    for i in range(2):
        item_id, revision_id = _make_item_and_revision(conn, brand_id, str(i))
        _record_publication(
            conn,
            brand_id=brand_id,
            item_id=item_id,
            revision_id=revision_id,
            published_at=now - timedelta(hours=1),
        )
    verdict = check_rate_limit(conn, brand_id=brand_id, brand=_brand(max_posts_per_day=2), now=now)
    assert not verdict.allowed
    assert verdict.reason == "max_posts_per_day reached"


def test_denied_when_min_gap_not_elapsed(conn: sqlite3.Connection, brand_id: int) -> None:
    now = datetime.now(UTC)
    item_id, revision_id = _make_item_and_revision(conn, brand_id, "1")
    _record_publication(
        conn,
        brand_id=brand_id,
        item_id=item_id,
        revision_id=revision_id,
        published_at=now - timedelta(minutes=30),
    )
    verdict = check_rate_limit(conn, brand_id=brand_id, brand=_brand(min_gap_minutes=240), now=now)
    assert not verdict.allowed
    assert verdict.reason == "min_gap_minutes not elapsed"


def test_allowed_once_gap_has_elapsed(conn: sqlite3.Connection, brand_id: int) -> None:
    now = datetime.now(UTC)
    item_id, revision_id = _make_item_and_revision(conn, brand_id, "1")
    _record_publication(
        conn,
        brand_id=brand_id,
        item_id=item_id,
        revision_id=revision_id,
        published_at=now - timedelta(minutes=300),
    )
    verdict = check_rate_limit(conn, brand_id=brand_id, brand=_brand(min_gap_minutes=240), now=now)
    assert verdict.allowed


def test_posting_window_denies_outside_configured_hours(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    brand = BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        posting_windows=BrandPostingWindows(windows=["09:00-11:00"], timezone="UTC"),
        virality=ViralityConfig(),
        publish=PublishConfig(max_posts_per_day=2, min_gap_minutes=0),
    )
    outside = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    verdict = check_rate_limit(conn, brand_id=brand_id, brand=brand, now=outside)
    assert not verdict.allowed
    assert verdict.reason == "outside posting window"

    inside = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    verdict2 = check_rate_limit(conn, brand_id=brand_id, brand=brand, now=inside)
    assert verdict2.allowed


def test_72_hour_simulation_never_exceeds_daily_cap(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    """Simulate a worker checking the gate every 10 minutes for 72 hours,
    publishing whenever allowed, and assert the daily cap is never exceeded
    on any rolling 24h window."""
    brand = _brand(max_posts_per_day=2, min_gap_minutes=240)
    published_count = 0
    published_times: list[datetime] = []

    with freeze_time("2026-01-01 00:00:00") as frozen:
        for tick in range(72 * 6):  # every 10 minutes for 72 hours
            now = datetime.now(UTC)
            verdict = check_rate_limit(conn, brand_id=brand_id, brand=brand, now=now)
            if verdict.allowed:
                item_id, revision_id = _make_item_and_revision(conn, brand_id, str(tick))
                _record_publication(
                    conn,
                    brand_id=brand_id,
                    item_id=item_id,
                    revision_id=revision_id,
                    published_at=now,
                )
                published_count += 1
                published_times.append(now)

                recent = [t for t in published_times if (now - t) < timedelta(hours=24)]
                assert len(recent) <= brand.publish.max_posts_per_day

            frozen.tick(timedelta(minutes=10))

    assert published_count > 0
