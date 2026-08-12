from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from trendstealer.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class MigrationChecksumError(RuntimeError):
    """An already-applied migration file changed on disk since it was applied."""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or get_settings().db_path_abs
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE so writers fail fast on contention instead of
    upgrading a read lock mid-transaction (SQLITE_BUSY on upgrade)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements.

    Deliberately not using conn.executescript(): it implicitly COMMITs any
    open transaction before running, which would break atomicity with the
    surrounding BEGIN IMMEDIATE in transaction() below. Full-line `--`
    comments are stripped first (they may themselves contain semicolons);
    safe here because migration files contain plain DDL with no semicolons
    inside string literals and no trailing same-line comments.
    """
    code_only = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [stmt.strip() for stmt in code_only.split(";") if stmt.strip()]


def upgrade(conn: sqlite3.Connection) -> list[str]:
    """Apply pending forward-only migrations. Returns names of migrations applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            checksum   TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    applied = {
        row["filename"]: row["checksum"]
        for row in conn.execute("SELECT filename, checksum FROM schema_migrations")
    }

    newly_applied = []
    for path in _migration_files():
        checksum = _checksum(path)
        if path.name in applied:
            if applied[path.name] != checksum:
                raise MigrationChecksumError(
                    f"{path.name} was modified after being applied "
                    f"(recorded {applied[path.name]}, now {checksum}). "
                    "Migrations are forward-only — add a new file instead of editing this one."
                )
            continue

        sql = path.read_text()
        with transaction(conn):
            for stmt in _split_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES (?, ?)",
                (path.name, checksum),
            )
        newly_applied.append(path.name)

    return newly_applied


def check(conn: sqlite3.Connection) -> list[str]:
    """Return migration filenames that have not yet been applied, without applying them."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    applied: set[str] = set()
    if tables:
        applied = {
            row["filename"] for row in conn.execute("SELECT filename FROM schema_migrations")
        }
    return [p.name for p in _migration_files() if p.name not in applied]
