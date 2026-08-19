"""The asset library: what the renderer is allowed to use, and the
licence gate that stops an uncleared clip reaching a live post."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from trendstealer import repo


@pytest.fixture
def brand_id(conn: sqlite3.Connection) -> int:
    return repo.upsert_brand(conn, "acme", "Acme")


def test_upsert_asset_is_idempotent_on_path(conn: sqlite3.Connection) -> None:
    first = repo.upsert_asset(
        conn, path="assets/video/a.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    second = repo.upsert_asset(
        conn, path="assets/video/a.mp4", kind="video", license="Pexels", tags="football"
    )
    assert first == second
    row = repo.get_asset_by_path(conn, "assets/video/a.mp4")
    assert row is not None
    assert row["tags"] == "football"
    # the re-registration carried its own clearance value, which is the
    # honest reading of "this is what I now know about this file"
    assert row["cleared_for_commercial"] == 0


def test_list_assets_hides_uncleared_by_default(conn: sqlite3.Connection) -> None:
    repo.upsert_asset(
        conn, path="ok.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    repo.upsert_asset(
        conn, path="risky.mp4", kind="video", license="unknown", cleared_for_commercial=False
    )

    cleared = repo.list_assets(conn, kind="video")
    assert [r["path"] for r in cleared] == ["ok.mp4"]

    everything = repo.list_assets(conn, kind="video", cleared_only=False)
    assert {r["path"] for r in everything} == {"ok.mp4", "risky.mp4"}


def test_list_assets_filters_by_kind(conn: sqlite3.Connection) -> None:
    repo.upsert_asset(
        conn, path="clip.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    repo.upsert_asset(
        conn, path="pic.png", kind="image", license="Pexels", cleared_for_commercial=True
    )
    assert [r["path"] for r in repo.list_assets(conn, kind="image")] == ["pic.png"]


def test_list_assets_filters_by_tag_without_matching_substrings(
    conn: sqlite3.Connection,
) -> None:
    repo.upsert_asset(
        conn,
        path="football.mp4",
        kind="video",
        license="Pexels",
        tags="football,sport",
        cleared_for_commercial=True,
    )
    repo.upsert_asset(
        conn,
        path="footballer.mp4",
        kind="video",
        license="Pexels",
        tags="footballers",
        cleared_for_commercial=True,
    )
    matched = repo.list_assets(conn, kind="video", tag="football")
    assert [r["path"] for r in matched] == ["football.mp4"]


def test_unused_assets_sort_ahead_of_recently_used_ones(conn: sqlite3.Connection) -> None:
    """The recency penalty -- otherwise a small B-roll library shows the
    same clip in every single video."""
    used_recently = repo.upsert_asset(
        conn, path="stale.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    used_long_ago = repo.upsert_asset(
        conn, path="older.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    repo.upsert_asset(
        conn, path="fresh.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )

    now = datetime.now(UTC)
    repo.touch_asset_used(conn, used_recently, when=now)
    repo.touch_asset_used(conn, used_long_ago, when=now - timedelta(days=30))

    order = [r["path"] for r in repo.list_assets(conn, kind="video")]
    assert order == ["fresh.mp4", "older.mp4", "stale.mp4"]


def test_uncleared_asset_in_a_render_is_reported_for_preflight(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', 'v1', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute("SELECT id FROM trends").fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook="hook",
        spoken_script="script",
    )

    cleared = repo.upsert_asset(
        conn, path="ok.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    uncleared = repo.upsert_asset(
        conn, path="risky.jpg", kind="image", license="press photo", cleared_for_commercial=False
    )
    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[cleared], role="broll")
    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[uncleared], role="intro")

    flagged = repo.list_uncleared_assets_for_revision(conn, revision_id)
    assert [r["path"] for r in flagged] == ["risky.jpg"]


def test_record_item_assets_is_idempotent(conn: sqlite3.Connection, brand_id: int) -> None:
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', 'v1', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute("SELECT id FROM trends").fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook="hook",
        spoken_script="script",
    )
    asset_id = repo.upsert_asset(conn, path="a.mp4", kind="video", license="Pexels")

    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[asset_id], role="broll")
    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[asset_id], role="broll")

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM item_assets WHERE revision_id = ?", (revision_id,)
    ).fetchone()["n"]
    assert count == 1
