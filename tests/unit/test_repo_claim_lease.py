import sqlite3

import pytest

from trendstealer import repo
from trendstealer.states import ContentStatus


@pytest.fixture
def item_ids(conn: sqlite3.Connection) -> dict[str, int]:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    ids = {}
    for i, status in enumerate(
        [ContentStatus.QUEUED, ContentStatus.SCRIPT_READY, ContentStatus.CHANGES_REQUESTED]
    ):
        conn.execute(
            """
            INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
            VALUES (?, 'tiktok', ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            """,
            (brand_id, f"vid-{i}"),
        )
        trend_id = conn.execute(
            "SELECT id FROM trends WHERE platform_video_id = ?", (f"vid-{i}",)
        ).fetchone()["id"]
        item_id = repo.create_content_item(
            conn, brand_id=brand_id, trend_id=trend_id, initial_status=ContentStatus.QUEUED
        )
        if status != ContentStatus.QUEUED:
            # walk queued -> ... -> target status via legal transitions
            if status == ContentStatus.SCRIPT_READY:
                repo.transition(
                    conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="t"
                )
                repo.transition(
                    conn,
                    item_id,
                    ContentStatus.SYNTHESIZING,
                    ContentStatus.SCRIPT_READY,
                    actor="t",
                )
            elif status == ContentStatus.CHANGES_REQUESTED:
                for edge in [
                    (ContentStatus.QUEUED, ContentStatus.SYNTHESIZING),
                    (ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY),
                    (ContentStatus.SCRIPT_READY, ContentStatus.RENDERING),
                    (ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW),
                    (ContentStatus.PENDING_REVIEW, ContentStatus.CHANGES_REQUESTED),
                ]:
                    repo.transition(conn, item_id, edge[0], edge[1], actor="t")
        ids[str(status)] = item_id
    return ids


def test_claim_priority_favors_changes_requested_over_queued_and_script_ready(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    claimed = repo.claim_lease(conn, owner="w1", ttl_seconds=60)
    assert claimed is not None
    assert claimed["id"] == item_ids[str(ContentStatus.CHANGES_REQUESTED)]


def test_claim_sets_lease_owner_and_future_expiry(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    claimed = repo.claim_lease(conn, owner="w1", ttl_seconds=60)
    assert claimed is not None
    assert claimed["lease_owner"] == "w1"
    assert claimed["lease_expires_at"] is not None


def test_claimed_item_not_reclaimed_while_lease_unexpired(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    first = repo.claim_lease(conn, owner="w1", ttl_seconds=600)
    assert first is not None
    second = repo.claim_lease(conn, owner="w2", ttl_seconds=600)
    assert second is not None
    assert second["id"] != first["id"]  # next-highest-priority item, not the same one


def test_expired_lease_is_reclaimable(conn: sqlite3.Connection, item_ids: dict[str, int]) -> None:
    first = repo.claim_lease(conn, owner="w1", ttl_seconds=-1)  # already expired
    assert first is not None
    second = repo.claim_lease(conn, owner="w2", ttl_seconds=60)
    assert second is not None
    assert second["id"] == first["id"]
    assert second["lease_owner"] == "w2"


def test_claim_returns_none_when_nothing_claimable(conn: sqlite3.Connection) -> None:
    assert repo.claim_lease(conn, owner="w1", ttl_seconds=60) is None


def test_release_lease_clears_owner_and_expiry(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    claimed = repo.claim_lease(conn, owner="w1", ttl_seconds=60)
    assert claimed is not None
    repo.release_lease(conn, claimed["id"])
    row = repo.get_content_item(conn, claimed["id"])
    assert row is not None
    assert row["lease_owner"] is None
    assert row["lease_expires_at"] is None


# --- claim_lease_for_item (`generate now --item-id`) -------------------------


def test_claim_for_item_takes_the_named_item_not_the_priority_pick(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    """claim_lease() would return the changes_requested item; naming an id
    must override that ordering entirely."""
    target = item_ids[str(ContentStatus.QUEUED)]
    claimed = repo.claim_lease_for_item(conn, target, owner="w1", ttl_seconds=60)
    assert claimed is not None
    assert claimed["id"] == target
    assert claimed["lease_owner"] == "w1"


def test_claim_for_item_returns_none_for_a_non_claimable_status(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    item_id = item_ids[str(ContentStatus.CHANGES_REQUESTED)]
    for edge in [
        (ContentStatus.CHANGES_REQUESTED, ContentStatus.SYNTHESIZING),
        (ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY),
        (ContentStatus.SCRIPT_READY, ContentStatus.RENDERING),
        (ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW),
        (ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED),
    ]:
        repo.transition(conn, item_id, edge[0], edge[1], actor="t")

    assert repo.claim_lease_for_item(conn, item_id, owner="w1", ttl_seconds=60) is None


def test_claim_for_item_returns_none_while_another_worker_holds_it(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    target = item_ids[str(ContentStatus.QUEUED)]
    assert repo.claim_lease_for_item(conn, target, owner="w1", ttl_seconds=600) is not None
    assert repo.claim_lease_for_item(conn, target, owner="w2", ttl_seconds=600) is None


def test_claim_for_item_reclaims_an_expired_lease(
    conn: sqlite3.Connection, item_ids: dict[str, int]
) -> None:
    target = item_ids[str(ContentStatus.QUEUED)]
    repo.claim_lease_for_item(conn, target, owner="w1", ttl_seconds=-1)
    reclaimed = repo.claim_lease_for_item(conn, target, owner="w2", ttl_seconds=60)
    assert reclaimed is not None
    assert reclaimed["lease_owner"] == "w2"


def test_claim_for_item_returns_none_for_a_missing_id(conn: sqlite3.Connection) -> None:
    assert repo.claim_lease_for_item(conn, 99999, owner="w1", ttl_seconds=60) is None
