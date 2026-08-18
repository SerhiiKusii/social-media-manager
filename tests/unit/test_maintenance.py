import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from trendstealer import db, repo
from trendstealer.commands.maintenance import (
    GRAPH_API_BASE,
    auto_archive_stale_pending_review,
    backup_database,
    check_token_expiry,
    gc_render_artifacts,
)
from trendstealer.states import ContentStatus


def _make_item(conn: sqlite3.Connection, brand_id: int, suffix: str) -> int:
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
    return repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)


def _advance_to(conn: sqlite3.Connection, item_id: int, target: ContentStatus) -> None:
    path = {
        ContentStatus.PENDING_REVIEW: [
            (ContentStatus.QUEUED, ContentStatus.SYNTHESIZING),
            (ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY),
            (ContentStatus.SCRIPT_READY, ContentStatus.RENDERING),
            (ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW),
        ],
    }[target]
    for edge in path:
        repo.transition(conn, item_id, edge[0], edge[1], actor="test")


def _backdate_updated_at(conn: sqlite3.Connection, item_id: int, when: datetime) -> None:
    conn.execute(
        "UPDATE content_items SET updated_at = ? WHERE id = ?",
        (when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", item_id),
    )


@pytest.fixture
def brand_id(conn: sqlite3.Connection) -> int:
    return repo.upsert_brand(conn, "acme", "Acme")


def test_auto_archive_archives_stale_pending_review_items(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    item_id = _make_item(conn, brand_id, "1")
    _advance_to(conn, item_id, ContentStatus.PENDING_REVIEW)
    _backdate_updated_at(conn, item_id, datetime.now(UTC) - timedelta(hours=72))

    count = auto_archive_stale_pending_review(conn, max_age_hours=48, now=datetime.now(UTC))
    assert count == 1

    row = repo.get_content_item(conn, item_id)
    assert row is not None
    assert row["status"] == str(ContentStatus.ARCHIVED)


def test_auto_archive_leaves_recent_pending_review_items_alone(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    item_id = _make_item(conn, brand_id, "1")
    _advance_to(conn, item_id, ContentStatus.PENDING_REVIEW)

    count = auto_archive_stale_pending_review(conn, max_age_hours=48, now=datetime.now(UTC))
    assert count == 0

    row = repo.get_content_item(conn, item_id)
    assert row is not None
    assert row["status"] == str(ContentStatus.PENDING_REVIEW)


def test_gc_render_artifacts_removes_old_terminal_item_dirs(
    conn: sqlite3.Connection, brand_id: int, tmp_path: Path
) -> None:
    item_id = _make_item(conn, brand_id, "1")
    _advance_to(conn, item_id, ContentStatus.PENDING_REVIEW)
    repo.transition(
        conn, item_id, ContentStatus.PENDING_REVIEW, ContentStatus.REJECTED, actor="test"
    )
    _backdate_updated_at(conn, item_id, datetime.now(UTC) - timedelta(days=60))

    render_root = tmp_path / "work"
    item_dir = render_root / str(item_id)
    item_dir.mkdir(parents=True)
    (item_dir / "out.mp4").write_bytes(b"fake")

    removed = gc_render_artifacts(
        conn, render_root=render_root, retention_days=30, now=datetime.now(UTC)
    )
    assert removed == 1
    assert not item_dir.exists()


def test_gc_render_artifacts_keeps_recent_items(
    conn: sqlite3.Connection, brand_id: int, tmp_path: Path
) -> None:
    item_id = _make_item(conn, brand_id, "1")
    _advance_to(conn, item_id, ContentStatus.PENDING_REVIEW)
    repo.transition(
        conn, item_id, ContentStatus.PENDING_REVIEW, ContentStatus.REJECTED, actor="test"
    )

    render_root = tmp_path / "work"
    item_dir = render_root / str(item_id)
    item_dir.mkdir(parents=True)

    removed = gc_render_artifacts(
        conn, render_root=render_root, retention_days=30, now=datetime.now(UTC)
    )
    assert removed == 0
    assert item_dir.exists()


def test_backup_database_creates_a_restorable_copy(tmp_path: Path) -> None:
    db_path = tmp_path / "trendstealer.db"
    conn = db.connect(db_path)
    db.upgrade(conn)
    repo.upsert_brand(conn, "acme", "Acme")
    conn.close()

    result = backup_database(db_path, tmp_path / "backups", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert result.path.exists()
    assert result.size_bytes > 0

    restored = db.connect(result.path)
    row = repo.get_brand_by_key(restored, "acme")
    assert row is not None
    restored.close()


def test_backup_database_prunes_old_backups_beyond_keep_last(tmp_path: Path) -> None:
    db_path = tmp_path / "trendstealer.db"
    conn = db.connect(db_path)
    db.upgrade(conn)
    conn.close()

    backup_dir = tmp_path / "backups"
    for i in range(5):
        backup_database(db_path, backup_dir, now=datetime(2026, 1, 1 + i, tzinfo=UTC), keep_last=3)

    remaining = sorted(backup_dir.glob("trendstealer-*.db"))
    assert len(remaining) == 3


@respx.mock
def test_check_token_expiry_reports_days_remaining() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    expires_at = now + timedelta(days=10)
    respx.get(f"{GRAPH_API_BASE}/debug_token").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"is_valid": True, "expires_at": int(expires_at.timestamp())}},
        )
    )
    status = check_token_expiry(access_token="tok", client=httpx.Client(), now=now)
    assert status.is_valid
    assert status.days_remaining is not None
    assert 9.9 < status.days_remaining < 10.1


@respx.mock
def test_check_token_expiry_handles_never_expires() -> None:
    respx.get(f"{GRAPH_API_BASE}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 0}})
    )
    status = check_token_expiry(access_token="tok", client=httpx.Client())
    assert status.is_valid
    assert status.days_remaining is None


@respx.mock
def test_check_token_expiry_reports_invalid_token() -> None:
    respx.get(f"{GRAPH_API_BASE}/debug_token").mock(
        return_value=httpx.Response(200, json={"data": {"is_valid": False}})
    )
    status = check_token_expiry(access_token="expired-tok", client=httpx.Client())
    assert not status.is_valid
