import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from trendstealer import repo
from trendstealer.commands.metrics import run_metrics_once
from trendstealer.intelligence.feedback import format_hook_performance
from trendstealer.metrics.instagram_insights import MediaInsights


@pytest.fixture
def brand_id(conn: sqlite3.Connection) -> int:
    return repo.upsert_brand(conn, "acme", "Acme")


def _published_item(
    conn: sqlite3.Connection, brand_id: int, *, suffix: str, hook_pattern: str, media_id: str | None
) -> tuple[int, int]:
    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1"
    )
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
        script_plan_json=json.dumps({"hook_pattern": hook_pattern}),
    )
    publication_id = repo.create_publication(
        conn,
        content_item_id=item_id,
        revision_id=revision_id,
        brand_id=brand_id,
        platform="instagram",
        account_id=account_id,
        idempotency_key=f"key-{suffix}",
        platform_media_id=media_id,
        status="published",
        published_at=datetime.now(UTC) - timedelta(hours=48),
    )
    return item_id, publication_id


def test_list_publications_needing_snapshot_finds_unsnapshotted(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _item_id, publication_id = _published_item(
        conn, brand_id, suffix="1", hook_pattern="pattern-interrupt", media_id="m1"
    )
    due = repo.list_publications_needing_snapshot(
        conn, brand_id=brand_id, min_age_hours=24, now=datetime.now(UTC)
    )
    assert [row["id"] for row in due] == [publication_id]


def test_list_publications_needing_snapshot_excludes_recently_snapshotted(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _item_id, publication_id = _published_item(
        conn, brand_id, suffix="1", hook_pattern="pattern-interrupt", media_id="m1"
    )
    repo.create_metrics_snapshot(
        conn, publication_id=publication_id, captured_at=datetime.now(UTC), views=100
    )
    due = repo.list_publications_needing_snapshot(
        conn, brand_id=brand_id, min_age_hours=24, now=datetime.now(UTC)
    )
    assert due == []


def test_get_hook_pattern_performance_averages_latest_snapshot_per_publication(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _item1, pub1 = _published_item(
        conn, brand_id, suffix="1", hook_pattern="pattern-interrupt", media_id="m1"
    )
    _item2, pub2 = _published_item(
        conn, brand_id, suffix="2", hook_pattern="pattern-interrupt", media_id="m2"
    )
    _item3, pub3 = _published_item(
        conn, brand_id, suffix="3", hook_pattern="before-after", media_id="m3"
    )

    now = datetime.now(UTC)
    repo.create_metrics_snapshot(conn, publication_id=pub1, captured_at=now, views=1000)
    repo.create_metrics_snapshot(conn, publication_id=pub2, captured_at=now, views=2000)
    repo.create_metrics_snapshot(conn, publication_id=pub3, captured_at=now, views=100)

    stats = repo.get_hook_pattern_performance(conn, brand_id=brand_id)
    by_pattern = {s["hook_pattern"]: s for s in stats}

    assert by_pattern["pattern-interrupt"]["avg_views"] == 1500
    assert by_pattern["pattern-interrupt"]["sample_size"] == 2
    assert by_pattern["before-after"]["avg_views"] == 100


def test_get_hook_pattern_performance_uses_only_the_latest_snapshot(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _item_id, pub_id = _published_item(
        conn, brand_id, suffix="1", hook_pattern="pattern-interrupt", media_id="m1"
    )
    repo.create_metrics_snapshot(
        conn, publication_id=pub_id, captured_at=datetime.now(UTC) - timedelta(hours=2), views=100
    )
    repo.create_metrics_snapshot(
        conn, publication_id=pub_id, captured_at=datetime.now(UTC), views=500
    )

    stats = repo.get_hook_pattern_performance(conn, brand_id=brand_id)
    assert stats[0]["avg_views"] == 500  # latest, not stale, snapshot only


def test_format_hook_performance_ranks_by_avg_views() -> None:
    stats = [
        {"hook_pattern": "low", "avg_views": 10.0, "sample_size": 1},
        {"hook_pattern": "high", "avg_views": 5000.0, "sample_size": 3},
    ]
    text = format_hook_performance(stats)
    assert text is not None
    assert text.index("high") < text.index("low")


def test_format_hook_performance_returns_none_when_empty() -> None:
    assert format_hook_performance([]) is None


def test_run_metrics_once_records_snapshots_for_due_publications(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _item_id, _pub_id = _published_item(
        conn, brand_id, suffix="1", hook_pattern="pattern-interrupt", media_id="m1"
    )

    def fake_fetch(media_id: str) -> MediaInsights:
        assert media_id == "m1"
        return MediaInsights(views=42, likes=3, comments=1, shares=0, saves=0, reach=40)

    count = run_metrics_once(
        conn, brand_id=brand_id, fetch_insights=fake_fetch, now=datetime.now(UTC)
    )
    assert count == 1

    row = conn.execute("SELECT * FROM metrics_snapshots").fetchone()
    assert row["views"] == 42


def test_run_metrics_once_skips_publications_without_media_id(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    _published_item(conn, brand_id, suffix="1", hook_pattern="x", media_id=None)

    def fake_fetch(media_id: str) -> MediaInsights:
        raise AssertionError("should not be called")

    count = run_metrics_once(
        conn, brand_id=brand_id, fetch_insights=fake_fetch, now=datetime.now(UTC)
    )
    assert count == 0
