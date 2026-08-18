from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from trendstealer import repo
from trendstealer.logging import get_logger
from trendstealer.states import ContentStatus

logger = get_logger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def auto_archive_stale_pending_review(
    conn: sqlite3.Connection, *, max_age_hours: int = 48, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    stale = repo.list_stale_pending_review(conn, max_age_hours=max_age_hours, now=now)
    for item in stale:
        try:
            repo.transition(
                conn,
                item["id"],
                ContentStatus.PENDING_REVIEW,
                ContentStatus.ARCHIVED,
                actor="maintenance",
                note=f"auto-archived: exceeded {max_age_hours}h in pending_review",
                expected_version=item["version"],
            )
        except Exception:  # noqa: BLE001 - raced with a human action; skip, not fatal
            logger.warning("auto_archive_race_skipped", item_id=item["id"])
    return len(stale)


def gc_render_artifacts(
    conn: sqlite3.Connection,
    *,
    render_root: Path,
    retention_days: int = 30,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    old_items = repo.list_terminal_items_older_than(conn, retention_days=retention_days, now=now)
    removed = 0
    for item in old_items:
        item_dir = render_root / str(item["id"])
        if item_dir.exists() and item_dir.is_relative_to(render_root):
            shutil.rmtree(item_dir)
            removed += 1
    return removed


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int


def backup_database(
    db_path: Path, backup_dir: Path, *, now: datetime | None = None, keep_last: int = 14
) -> BackupResult:
    """Uses sqlite3's native online backup API rather than copying the file
    directly -- safe against a concurrent writer under WAL mode, unlike a
    plain file copy which can capture a torn, inconsistent snapshot."""
    now = now or datetime.now(UTC)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"trendstealer-{now.strftime('%Y%m%dT%H%M%SZ')}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    backups = sorted(backup_dir.glob("trendstealer-*.db"))
    for stale_backup in backups[:-keep_last]:
        stale_backup.unlink()

    return BackupResult(path=dest, size_bytes=dest.stat().st_size)


@dataclass(frozen=True)
class TokenStatus:
    is_valid: bool
    expires_at: datetime | None
    days_remaining: float | None


def check_token_expiry(
    *, access_token: str, client: httpx.Client, now: datetime | None = None
) -> TokenStatus:
    now = now or datetime.now(UTC)
    response = client.get(
        f"{GRAPH_API_BASE}/debug_token",
        params={"input_token": access_token, "access_token": access_token},
    )
    response.raise_for_status()
    data = response.json().get("data", {})
    is_valid = bool(data.get("is_valid"))
    expires_at_epoch = data.get("expires_at")

    if not expires_at_epoch:  # 0 or missing means "never expires" for some token types
        return TokenStatus(is_valid=is_valid, expires_at=None, days_remaining=None)

    expires_at = datetime.fromtimestamp(expires_at_epoch, tz=UTC)
    days_remaining = (expires_at - now) / timedelta(days=1)
    return TokenStatus(is_valid=is_valid, expires_at=expires_at, days_remaining=days_remaining)
