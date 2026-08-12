"""Four independent dedupe layers, per the plan:

1. Natural-key check before insert (repo.get_trend_by_platform_id)
2. UNIQUE(brand_id, trend_id) on content_items (DB constraint, caught by
   the caller as sqlite3.IntegrityError)
3. SimHash near-duplicate check (this module, is_near_duplicate)
4. Audio-ID cooldown (this module, is_audio_in_cooldown)
"""

from __future__ import annotations

import sqlite3

from trendstealer.ingest.simhash import from_sqlite_int64, hamming_distance, simhash64


def is_near_duplicate(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    transcript: str,
    window_days: int,
    hamming_threshold: int,
) -> bool:
    candidate_hash = simhash64(transcript)
    rows = conn.execute(
        """
        SELECT transcript_simhash FROM trends
        WHERE brand_id = ?
          AND transcript_simhash IS NOT NULL
          AND scraped_at >= datetime('now', ?)
        """,
        (brand_id, f"-{window_days} days"),
    ).fetchall()
    return any(
        hamming_distance(candidate_hash, from_sqlite_int64(row["transcript_simhash"]))
        <= hamming_threshold
        for row in rows
    )


def is_audio_in_cooldown(
    conn: sqlite3.Connection, *, brand_id: int, audio_id: str, cooldown_days: int
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM trends
        WHERE brand_id = ? AND audio_id = ? AND scraped_at >= datetime('now', ?)
        LIMIT 1
        """,
        (brand_id, audio_id, f"-{cooldown_days} days"),
    ).fetchone()
    return row is not None
