import sqlite3
from pathlib import Path

import pytest

from trendstealer import db


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "test.db")
    db.upgrade(connection)
    yield connection
    connection.close()
