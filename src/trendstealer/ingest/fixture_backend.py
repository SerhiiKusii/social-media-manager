from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trendstealer.config import REPO_ROOT
from trendstealer.ingest.backend import ScrapeResult

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "apify"


class ApifyFixtureBackend:
    """Zero-network ApifyBackend. Replays a committed dataset JSON file
    (tests/fixtures/apify/<platform>.json) recorded once against the real
    actor. Re-feeding the same fixture twice must produce items_new == 0 --
    that's the ingest re-run idempotency test."""

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or FIXTURES_DIR

    def scrape(
        self,
        *,
        platform: str,
        actor_id: str,
        run_input: dict[str, Any],
        max_items: int,
        timeout_secs: int,
        memory_mbytes: int = 1024,
    ) -> ScrapeResult:
        path = self.fixtures_dir / f"{platform}.json"
        if not path.exists():
            return ScrapeResult(items=[], compute_units=0.0)
        items = json.loads(path.read_text())
        return ScrapeResult(items=items[:max_items], compute_units=0.05)
