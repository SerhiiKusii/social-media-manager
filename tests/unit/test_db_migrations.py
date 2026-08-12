import sqlite3
from pathlib import Path

import pytest

from trendstealer import db


def test_real_migrations_create_all_13_tables(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "brands",
        "accounts",
        "scrape_runs",
        "trends",
        "content_items",
        "revisions",
        "assets",
        "item_assets",
        "publications",
        "metrics_snapshots",
        "status_events",
        "api_usage",
        "schema_migrations",
    }
    assert expected <= tables


def test_second_upgrade_is_a_noop(conn: sqlite3.Connection) -> None:
    assert db.upgrade(conn) == []


def test_check_reports_nothing_pending_after_upgrade(conn: sqlite3.Connection) -> None:
    assert db.check(conn) == []


def test_check_reports_pending_before_any_upgrade(tmp_path: Path) -> None:
    fresh_conn = db.connect(tmp_path / "fresh.db")
    try:
        pending = db.check(fresh_conn)
        assert "0001_initial.sql" in pending
    finally:
        fresh_conn.close()


def test_checksum_guard_rejects_tampered_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_file = migrations_dir / "0001_test.sql"
    migration_file.write_text("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations_dir)

    conn = db.connect(tmp_path / "scratch.db")
    try:
        assert db.upgrade(conn) == ["0001_test.sql"]

        migration_file.write_text("CREATE TABLE t (id INTEGER PRIMARY KEY, extra TEXT)")
        with pytest.raises(db.MigrationChecksumError):
            db.upgrade(conn)
    finally:
        conn.close()


def test_migrations_apply_in_filename_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0002_second.sql").write_text("CREATE TABLE second (id INTEGER)")
    (migrations_dir / "0001_first.sql").write_text("CREATE TABLE first (id INTEGER)")

    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations_dir)

    conn = db.connect(tmp_path / "order.db")
    try:
        applied = db.upgrade(conn)
        assert applied == ["0001_first.sql", "0002_second.sql"]
    finally:
        conn.close()
