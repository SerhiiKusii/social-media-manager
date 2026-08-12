from __future__ import annotations

from datetime import timedelta
from typing import Any

from apify_client import ApifyClient

from trendstealer.ingest.backend import ScrapeResult


class LiveApifyBackend:
    """ApifyBackend backed by the real Apify platform.

    Every call passes explicit max_items/memory_mbytes/run_timeout -- never
    an unbounded run -- and shouldDownloadVideos is forced off in run_input
    by the caller (commands/ingest.py), not here, so it's visible at the
    call site next to the other explicit caps.
    """

    def __init__(self, token: str, *, client: ApifyClient | None = None) -> None:
        self.client = client or ApifyClient(token)

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
        run = self.client.actor(actor_id).call(
            run_input=run_input,
            max_items=max_items,
            memory_mbytes=memory_mbytes,
            run_timeout=timedelta(seconds=timeout_secs),
        )
        if run is None:
            return ScrapeResult(items=[], compute_units=0.0)

        page = self.client.dataset(run.default_dataset_id).list_items(limit=max_items)
        compute_units = run.stats.compute_units or 0.0
        return ScrapeResult(items=list(page.items), compute_units=compute_units)
