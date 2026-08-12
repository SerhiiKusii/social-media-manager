import sqlite3

import pytest

from trendstealer import repo
from trendstealer.states import ContentStatus, InvalidTransitionError, StaleStateError


@pytest.fixture
def item_id(conn: sqlite3.Connection) -> int:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    conn.execute(
        """
        INSERT INTO scrape_runs (brand_id, platform, actor_id, started_at, status)
        VALUES (?, 'tiktok', 'test-actor', strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'succeeded')
        """,
        (brand_id,),
    )
    run_id = conn.execute("SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO trends (scrape_run_id, brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, ?, 'tiktok', 'vid123', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (run_id, brand_id),
    )
    trend_id = conn.execute(
        "SELECT id FROM trends WHERE platform_video_id = 'vid123'"
    ).fetchone()["id"]
    return repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)


def test_create_content_item_starts_queued(conn: sqlite3.Connection, item_id: int) -> None:
    row = repo.get_content_item(conn, item_id)
    assert row["status"] == str(ContentStatus.QUEUED)
    assert row["version"] == 1


def test_valid_transition_updates_status_bumps_version_and_logs_event(
    conn: sqlite3.Connection, item_id: int
) -> None:
    result = repo.transition(
        conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="worker"
    )
    assert result.to_status == ContentStatus.SYNTHESIZING
    assert result.version == 2

    row = repo.get_content_item(conn, item_id)
    assert row["status"] == str(ContentStatus.SYNTHESIZING)
    assert row["version"] == 2

    events = repo.list_status_events(conn, item_id)
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "queued"),
        ("queued", "synthesizing"),
    ]


def test_illegal_transition_raises_before_touching_db(
    conn: sqlite3.Connection, item_id: int
) -> None:
    with pytest.raises(InvalidTransitionError):
        repo.transition(
            conn, item_id, ContentStatus.QUEUED, ContentStatus.PUBLISHED, actor="worker"
        )
    row = repo.get_content_item(conn, item_id)
    assert row["status"] == str(ContentStatus.QUEUED)
    assert row["version"] == 1


def test_stale_from_status_raises(conn: sqlite3.Connection, item_id: int) -> None:
    repo.transition(
        conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="worker"
    )
    with pytest.raises(StaleStateError):
        repo.transition(
            conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="worker"
        )


def test_optimistic_lock_rejects_stale_version(conn: sqlite3.Connection, item_id: int) -> None:
    # simulate a concurrent writer bumping version first
    repo.transition(
        conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="worker"
    )
    conn.execute("UPDATE content_items SET status = 'queued' WHERE id = ?", (item_id,))

    with pytest.raises(StaleStateError):
        repo.transition(
            conn,
            item_id,
            ContentStatus.QUEUED,
            ContentStatus.SYNTHESIZING,
            actor="dashboard:user",
            expected_version=1,  # actual version is now 2
        )


def test_status_injection_style_action_is_rejected(
    conn: sqlite3.Connection, item_id: int
) -> None:
    """Simulates the original architecture's bug: an action string that maps
    to an arbitrary status must still go through validate_transition and be
    rejected if it's not a legal edge from the item's current state."""
    with pytest.raises(InvalidTransitionError):
        repo.transition(
            conn, item_id, ContentStatus.QUEUED, ContentStatus.APPROVED, actor="dashboard:attacker"
        )
