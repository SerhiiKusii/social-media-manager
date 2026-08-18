"""All SQL for trendstealer lives in this module. Nothing else writes SQL.

Keeping every query in one place makes the state-machine guard in
transition() the single choke point content_items.status can move through,
and makes it possible to grep for every write against a given table.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict, cast

from trendstealer.db import transaction
from trendstealer.ingest.simhash import to_sqlite_int64
from trendstealer.states import (
    WORKER_CLAIMABLE_STATES,
    ContentStatus,
    StaleStateError,
    validate_transition,
)

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
        row = conn.execute("SELECT id FROM brands WHERE brand_key = ?", (brand_key,)).fetchone()
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


def get_trend(conn: sqlite3.Connection, trend_id: int) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        conn.execute("SELECT * FROM trends WHERE id = ?", (trend_id,)).fetchone(),
    )


def insert_trend(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    scrape_run_id: int | None,
    platform: str,
    platform_video_id: str,
    source_account: str | None = None,
    source_url: str | None = None,
    caption: str | None = None,
    transcript: str | None = None,
    views: int | None = None,
    likes: int | None = None,
    comments: int | None = None,
    shares: int | None = None,
    source_follower_count: int | None = None,
    duration_secs: float | None = None,
    posted_at: str | None = None,
    audio_id: str | None = None,
    transcript_simhash: int | None = None,
    virality_score: float | None = None,
    skip_reason: str | None = None,
) -> int:
    """Natural-key dedupe layer 1: UNIQUE(platform, platform_video_id) means
    a trend already seen on a prior ingest run is silently skipped."""
    stored_simhash = None if transcript_simhash is None else to_sqlite_int64(transcript_simhash)
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO trends (
                brand_id, scrape_run_id, platform, platform_video_id, source_account,
                source_url, caption, transcript, views, likes, comments, shares,
                source_follower_count, duration_secs, posted_at, scraped_at,
                audio_id, transcript_simhash, virality_score, skip_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?, ?, ?, ?)
            """,
            (
                brand_id,
                scrape_run_id,
                platform,
                platform_video_id,
                source_account,
                source_url,
                caption,
                transcript,
                views,
                likes,
                comments,
                shares,
                source_follower_count,
                duration_secs,
                posted_at,
                audio_id,
                stored_simhash,
                virality_score,
                skip_reason,
            ),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT id FROM trends WHERE platform = ? AND platform_video_id = ?",
                (platform, platform_video_id),
            ).fetchone()
            return int(row["id"])
        assert cur.lastrowid is not None
        return cur.lastrowid


def create_scrape_run(
    conn: sqlite3.Connection, *, brand_id: int, platform: str, actor_id: str
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO scrape_runs (brand_id, platform, actor_id, started_at, status)
            VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'running')
            """,
            (brand_id, platform, actor_id),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def finish_scrape_run(
    conn: sqlite3.Connection,
    scrape_run_id: int,
    *,
    status: str,
    items_scraped: int,
    compute_units: float | None = None,
    error: str | None = None,
) -> None:
    with transaction(conn):
        conn.execute(
            """
            UPDATE scrape_runs
            SET status = ?, items_scraped = ?, compute_units = ?, error = ?,
                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (status, items_scraped, compute_units, error, scrape_run_id),
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


def try_create_content_item(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    trend_id: int,
    initial_status: ContentStatus = ContentStatus.QUEUED,
) -> int | None:
    """Dedupe layer 2: UNIQUE(brand_id, trend_id) on content_items. Returns
    None instead of raising when this (brand, trend) pair already has an
    item, so ingest can treat it as "already queued" rather than an error."""
    try:
        return create_content_item(
            conn, brand_id=brand_id, trend_id=trend_id, initial_status=initial_status
        )
    except sqlite3.IntegrityError:
        return None


_CLAIM_PRIORITY_SQL = (
    "CASE status "
    + " ".join(f"WHEN '{status}' THEN {i}" for i, status in enumerate(WORKER_CLAIMABLE_STATES))
    + " END"
)


def claim_lease(conn: sqlite3.Connection, *, owner: str, ttl_seconds: int) -> sqlite3.Row | None:
    """Claim one claimable item, in WORKER_CLAIMABLE_STATES priority order,
    for exclusive processing by `owner` for ttl_seconds. An item with an
    unexpired lease is skipped (someone else is genuinely working it); one
    whose lease has expired (crashed worker) is fair game again. Runs inside
    a single BEGIN IMMEDIATE transaction, so the claim is race-free against
    other callers without needing a portable atomic UPDATE...ORDER BY."""
    placeholders = ",".join("?" for _ in WORKER_CLAIMABLE_STATES)
    with transaction(conn):
        row = conn.execute(
            f"""
            SELECT id FROM content_items
            WHERE status IN ({placeholders})
              AND (lease_expires_at IS NULL
                   OR lease_expires_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ORDER BY {_CLAIM_PRIORITY_SQL}, updated_at ASC
            LIMIT 1
            """,
            [str(s) for s in WORKER_CLAIMABLE_STATES],
        ).fetchone()
        if row is None:
            return None

        item_id = row["id"]
        conn.execute(
            """
            UPDATE content_items
            SET lease_owner = ?,
                lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ? || ' seconds')
            WHERE id = ?
            """,
            (owner, ttl_seconds, item_id),
        )
        claimed = conn.execute("SELECT * FROM content_items WHERE id = ?", (item_id,)).fetchone()
    return cast("sqlite3.Row | None", claimed)


def release_lease(conn: sqlite3.Connection, item_id: int) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE content_items SET lease_owner = NULL, lease_expires_at = NULL WHERE id = ?",
            (item_id,),
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


# --- revisions ----------------------------------------------------------


def create_revision(
    conn: sqlite3.Connection,
    *,
    content_item_id: int,
    revision_no: int,
    prompt_version: str,
    on_screen_hook: str,
    spoken_script: str,
    change_request: str | None = None,
    script_plan_json: str | None = None,
    voiceover_path: str | None = None,
    captions_path: str | None = None,
    video_path: str | None = None,
    render_ms: int | None = None,
    llm_input_tokens: int | None = None,
    llm_output_tokens: int | None = None,
    llm_cache_read_tokens: int | None = None,
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO revisions (
                content_item_id, revision_no, prompt_version, change_request,
                script_plan_json, on_screen_hook, spoken_script, voiceover_path,
                captions_path, video_path, render_ms,
                llm_input_tokens, llm_output_tokens, llm_cache_read_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_item_id,
                revision_no,
                prompt_version,
                change_request,
                script_plan_json,
                on_screen_hook,
                spoken_script,
                voiceover_path,
                captions_path,
                video_path,
                render_ms,
                llm_input_tokens,
                llm_output_tokens,
                llm_cache_read_tokens,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def get_revision(conn: sqlite3.Connection, revision_id: int) -> sqlite3.Row | None:
    return cast(
        "sqlite3.Row | None",
        conn.execute("SELECT * FROM revisions WHERE id = ?", (revision_id,)).fetchone(),
    )


def update_revision_render(
    conn: sqlite3.Connection,
    revision_id: int,
    *,
    voiceover_path: str,
    captions_path: str,
    video_path: str,
    render_ms: int,
) -> None:
    with transaction(conn):
        conn.execute(
            """
            UPDATE revisions
            SET voiceover_path = ?, captions_path = ?, video_path = ?, render_ms = ?
            WHERE id = ?
            """,
            (voiceover_path, captions_path, video_path, render_ms, revision_id),
        )


def set_current_revision(conn: sqlite3.Connection, item_id: int, revision_id: int) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE content_items SET current_revision_id = ? WHERE id = ?",
            (revision_id, item_id),
        )


def list_revisions(conn: sqlite3.Connection, content_item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM revisions WHERE content_item_id = ? ORDER BY revision_no",
        (content_item_id,),
    ).fetchall()


def get_latest_revision_no(conn: sqlite3.Connection, content_item_id: int) -> int | None:
    row = conn.execute(
        "SELECT MAX(revision_no) AS n FROM revisions WHERE content_item_id = ?",
        (content_item_id,),
    ).fetchone()
    return None if row["n"] is None else int(row["n"])


# --- review dashboard queries -------------------------------------------


def list_items_for_review(
    conn: sqlite3.Connection,
    status: ContentStatus,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Items in the given status, oldest trend first — a stale trend-jack
    sitting in the review queue is worse than one that never got made."""
    return conn.execute(
        """
        SELECT
            ci.id AS item_id, ci.status, ci.version, ci.created_at,
            t.platform, t.caption AS trend_caption, t.posted_at,
            r.revision_no, r.on_screen_hook, r.spoken_script, r.video_path
        FROM content_items ci
        JOIN trends t ON t.id = ci.trend_id
        LEFT JOIN revisions r ON r.id = ci.current_revision_id
        WHERE ci.status = ?
        ORDER BY COALESCE(t.posted_at, t.scraped_at) ASC
        LIMIT ? OFFSET ?
        """,
        (str(status), limit, offset),
    ).fetchall()


def count_items_by_status_value(conn: sqlite3.Connection, status: ContentStatus) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM content_items WHERE status = ?", (str(status),)
    ).fetchone()
    return int(row["n"])


def get_item_detail(conn: sqlite3.Connection, item_id: int) -> dict[str, object] | None:
    row = conn.execute(
        """
        SELECT
            ci.id AS item_id, ci.status, ci.version, ci.brand_id, ci.trend_id,
            ci.current_revision_id, ci.created_at, ci.updated_at,
            t.platform, t.caption AS trend_caption, t.transcript AS trend_transcript,
            t.source_url, t.posted_at
        FROM content_items ci
        JOIN trends t ON t.id = ci.trend_id
        WHERE ci.id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        **dict(row),
        "revisions": [dict(r) for r in list_revisions(conn, item_id)],
    }


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


# --- accounts ----------------------------------------------------------


def upsert_account(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    platform: str,
    platform_account_id: str,
    display_name: str | None = None,
) -> int:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO accounts (brand_id, platform, platform_account_id, display_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (brand_id, platform, platform_account_id)
            DO UPDATE SET display_name = excluded.display_name
            """,
            (brand_id, platform, platform_account_id, display_name),
        )
        row = conn.execute(
            """
            SELECT id FROM accounts
            WHERE brand_id = ? AND platform = ? AND platform_account_id = ?
            """,
            (brand_id, platform, platform_account_id),
        ).fetchone()
    return int(row["id"])


# --- publications --------------------------------------------------------

_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _format_ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(_TS_FORMAT)[:-3] + "Z"


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=UTC)


def create_publication(
    conn: sqlite3.Connection,
    *,
    content_item_id: int,
    revision_id: int,
    brand_id: int,
    platform: str,
    account_id: int,
    idempotency_key: str,
    platform_media_id: str | None = None,
    permalink: str | None = None,
    status: str = "published",
    error: str | None = None,
    published_at: datetime | None = None,
) -> int:
    """UNIQUE(idempotency_key) means a double-publish attempt raises
    sqlite3.IntegrityError instead of posting twice."""
    published_at = published_at or datetime.now(UTC)
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO publications (
                content_item_id, revision_id, brand_id, platform, account_id,
                idempotency_key, platform_media_id, permalink, published_at, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_item_id,
                revision_id,
                brand_id,
                platform,
                account_id,
                idempotency_key,
                platform_media_id,
                permalink,
                _format_ts(published_at),
                status,
                error,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def count_published_last_24h(conn: sqlite3.Connection, *, brand_id: int, now: datetime) -> int:
    cutoff = _format_ts(now - timedelta(hours=24))
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM publications
        WHERE brand_id = ? AND status = 'published' AND published_at >= ?
        """,
        (brand_id, cutoff),
    ).fetchone()
    return int(row["n"])


def get_last_publication_time(conn: sqlite3.Connection, *, brand_id: int) -> datetime | None:
    row = conn.execute(
        """
        SELECT published_at FROM publications
        WHERE brand_id = ? AND status = 'published'
        ORDER BY published_at DESC LIMIT 1
        """,
        (brand_id,),
    ).fetchone()
    return None if row is None else _parse_ts(row["published_at"])


def list_approved_items(conn: sqlite3.Connection, *, brand_id: int) -> list[sqlite3.Row]:
    """Oldest-approved-first, for the publisher's one-item-per-run pick."""
    return conn.execute(
        """
        SELECT * FROM content_items
        WHERE brand_id = ? AND status = ?
        ORDER BY updated_at ASC
        """,
        (brand_id, str(ContentStatus.APPROVED)),
    ).fetchall()


# --- metrics -------------------------------------------------------------


def list_publications_needing_snapshot(
    conn: sqlite3.Connection, *, brand_id: int, min_age_hours: int, now: datetime
) -> list[sqlite3.Row]:
    """Published items with no snapshot in the last min_age_hours."""
    cutoff = _format_ts(now - timedelta(hours=min_age_hours))
    return conn.execute(
        """
        SELECT p.* FROM publications p
        WHERE p.brand_id = ? AND p.status = 'published' AND p.platform_media_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM metrics_snapshots m
              WHERE m.publication_id = p.id AND m.captured_at >= ?
          )
        ORDER BY p.published_at ASC
        """,
        (brand_id, cutoff),
    ).fetchall()


def create_metrics_snapshot(
    conn: sqlite3.Connection,
    *,
    publication_id: int,
    captured_at: datetime,
    views: int | None = None,
    likes: int | None = None,
    comments: int | None = None,
    shares: int | None = None,
    saves: int | None = None,
    reach: int | None = None,
    conversions: int | None = None,
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO metrics_snapshots (
                publication_id, captured_at, views, likes, comments, shares, saves, reach,
                conversions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                publication_id,
                _format_ts(captured_at),
                views,
                likes,
                comments,
                shares,
                saves,
                reach,
                conversions,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


class HookPatternStat(TypedDict):
    hook_pattern: str
    avg_views: float
    sample_size: int


def get_hook_pattern_performance(
    conn: sqlite3.Connection, *, brand_id: int
) -> list[HookPatternStat]:
    """Joins each publication's most recent metrics_snapshot back to the
    revision that produced it, groups by hook_pattern (a field inside
    revisions.script_plan_json, not its own column), and averages views.
    This is the M9 feedback loop: which hook patterns work for *this*
    account, fed back into the synthesize prompt."""
    rows = conn.execute(
        """
        SELECT r.script_plan_json, m.views
        FROM metrics_snapshots m
        JOIN publications p ON p.id = m.publication_id
        JOIN revisions r ON r.id = p.revision_id
        WHERE p.brand_id = ?
          AND m.captured_at = (
              SELECT MAX(m2.captured_at) FROM metrics_snapshots m2
              WHERE m2.publication_id = m.publication_id
          )
        """,
        (brand_id,),
    ).fetchall()

    views_by_pattern: dict[str, list[int]] = {}
    for row in rows:
        if row["script_plan_json"] is None or row["views"] is None:
            continue
        try:
            plan = json.loads(row["script_plan_json"])
        except ValueError:
            continue
        pattern = plan.get("hook_pattern")
        if pattern:
            views_by_pattern.setdefault(pattern, []).append(row["views"])

    return [
        {
            "hook_pattern": pattern,
            "avg_views": sum(views_list) / len(views_list),
            "sample_size": len(views_list),
        }
        for pattern, views_list in views_by_pattern.items()
    ]


# --- maintenance -----------------------------------------------------------


def list_stale_pending_review(
    conn: sqlite3.Connection, *, max_age_hours: int, now: datetime
) -> list[sqlite3.Row]:
    """pending_review items sitting past max_age_hours -- a stale
    trend-jack is worse than no post, so these are auto-archive candidates
    rather than left to rot in the queue."""
    cutoff = _format_ts(now - timedelta(hours=max_age_hours))
    return conn.execute(
        """
        SELECT * FROM content_items
        WHERE status = ? AND updated_at < ?
        """,
        (str(ContentStatus.PENDING_REVIEW), cutoff),
    ).fetchall()


def list_terminal_items_older_than(
    conn: sqlite3.Connection, *, retention_days: int, now: datetime
) -> list[sqlite3.Row]:
    """Items in a terminal state whose render artifacts (var/work/<id>/)
    are safe to garbage-collect."""
    cutoff = _format_ts(now - timedelta(days=retention_days))
    placeholders = ",".join("?" for _ in range(3))
    return conn.execute(
        f"""
        SELECT * FROM content_items
        WHERE status IN ({placeholders}) AND updated_at < ?
        """,
        (
            str(ContentStatus.PUBLISHED),
            str(ContentStatus.ARCHIVED),
            str(ContentStatus.REJECTED),
            cutoff,
        ),
    ).fetchall()
