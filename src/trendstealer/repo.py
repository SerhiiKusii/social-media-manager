"""All SQL for trendstealer lives in this module. Nothing else writes SQL.

Keeping every query in one place makes the state-machine guard in
transition() the single choke point content_items.status can move through,
and makes it possible to grep for every write against a given table.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from trendstealer.db import transaction
from trendstealer.states import ContentStatus, StaleStateError, validate_transition

# --- brands -------------------------------------------------------------


def upsert_brand(conn: sqlite3.Connection, brand_key: str, name: str) -> int:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO brands (brand_key, name) VALUES (?, ?)
            ON CONFLICT (brand_key) DO UPDATE SET name = excluded.name
            """,
            (brand_key, name),
        )
        row = conn.execute(
            "SELECT id FROM brands WHERE brand_key = ?", (brand_key,)
        ).fetchone()
    return int(row["id"])


def get_brand_by_key(conn: sqlite3.Connection, brand_key: str) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        conn.execute("SELECT * FROM brands WHERE brand_key = ?", (brand_key,)).fetchone(),
    )


def list_brands(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM brands ORDER BY brand_key").fetchall()


# --- trends ---------------------------------------------------------------


def get_trend_by_platform_id(
    conn: sqlite3.Connection, platform: str, platform_video_id: str
) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        conn.execute(
            "SELECT * FROM trends WHERE platform = ? AND platform_video_id = ?",
            (platform, platform_video_id),
        ).fetchone(),
    )


# --- content_items ----------------------------------------------------------


def create_content_item(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    trend_id: int,
    initial_status: ContentStatus = ContentStatus.QUEUED,
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO content_items (brand_id, trend_id, status, version)
            VALUES (?, ?, ?, 1)
            """,
            (brand_id, trend_id, str(initial_status)),
        )
        assert cur.lastrowid is not None
        item_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO status_events (content_item_id, from_status, to_status, actor, note)
            VALUES (?, NULL, ?, 'system', 'created')
            """,
            (item_id, str(initial_status)),
        )
    return item_id


def get_content_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        conn.execute("SELECT * FROM content_items WHERE id = ?", (item_id,)).fetchone(),
    )


def count_content_items_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM content_items GROUP BY status"
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


@dataclass(frozen=True)
class TransitionResult:
    item_id: int
    from_status: ContentStatus
    to_status: ContentStatus
    version: int


def transition(
    conn: sqlite3.Connection,
    item_id: int,
    expected_from: ContentStatus,
    to: ContentStatus,
    *,
    actor: str,
    note: str | None = None,
    expected_version: int | None = None,
) -> TransitionResult:
    """The only sanctioned way to move content_items.status.

    Validates the edge against states.TRANSITIONS, then performs a
    conditional UPDATE ... WHERE id=? AND status=? (and AND version=? when
    the caller — the review dashboard — passes expected_version for
    optimistic locking). rowcount == 0 means the row had already moved on
    (a race, or a stale page/lease) and raises StaleStateError rather than
    silently doing nothing or clobbering a newer write.

    Writes a status_events row in the same transaction, so the audit log
    can never diverge from content_items.status.
    """
    validate_transition(expected_from, to)

    version_clause = ""
    params: list[object] = [str(to), item_id, str(expected_from)]
    if expected_version is not None:
        version_clause = " AND version = ?"
        params.append(expected_version)

    with transaction(conn):
        cur = conn.execute(
            f"""
            UPDATE content_items
            SET status = ?, version = version + 1,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND status = ?{version_clause}
            """,
            params,
        )
        if cur.rowcount == 0:
            raise StaleStateError(item_id, expected_from)

        new_version_row = conn.execute(
            "SELECT version FROM content_items WHERE id = ?", (item_id,)
        ).fetchone()

        conn.execute(
            """
            INSERT INTO status_events (content_item_id, from_status, to_status, actor, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, str(expected_from), str(to), actor, note),
        )

    return TransitionResult(
        item_id=item_id,
        from_status=expected_from,
        to_status=to,
        version=int(new_version_row["version"]),
    )


def list_status_events(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM status_events WHERE content_item_id = ? ORDER BY created_at",
        (item_id,),
    ).fetchall()


# --- api_usage --------------------------------------------------------------


def record_api_usage(
    conn: sqlite3.Connection,
    *,
    brand_id: int | None,
    service: str,
    operation: str,
    units: float,
    unit_kind: str,
    cost_usd: float | None = None,
) -> None:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO api_usage (brand_id, service, operation, units, unit_kind, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (brand_id, service, operation, units, unit_kind, cost_usd),
        )
