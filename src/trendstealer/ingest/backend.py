from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ScrapeResult:
    items: list[dict[str, Any]]
    compute_units: float


class ApifyBackend(Protocol):
    def scrape(
        self,
        *,
        platform: str,
        actor_id: str,
        run_input: dict[str, Any],
        max_items: int,
        timeout_secs: int,
        memory_mbytes: int = 1024,
    ) -> ScrapeResult: ...
