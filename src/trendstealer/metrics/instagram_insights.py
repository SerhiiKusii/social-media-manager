"""Instagram media insights.

NOTE: like publish/instagram.py, this has not been exercised against a
live account -- verify the metric names below against the Graph API
version actually in use before depending on them. "plays" in particular
has been renamed across API versions; check the current docs during M0.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
METRICS = ["reach", "likes", "comments", "shares", "saved", "plays"]


class InsightsError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInsights:
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reach: int | None = None


_METRIC_TO_FIELD = {
    "plays": "views",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "saved": "saves",
    "reach": "reach",
}


def fetch_media_insights(
    *, media_id: str, access_token: str, client: httpx.Client
) -> MediaInsights:
    response = client.get(
        f"{GRAPH_API_BASE}/{media_id}/insights",
        params={"metric": ",".join(METRICS), "access_token": access_token},
    )
    if response.status_code >= 400:
        raise InsightsError(f"Graph API error {response.status_code}: {response.text}")

    fields: dict[str, int] = {}
    for entry in response.json().get("data", []):
        field = _METRIC_TO_FIELD.get(entry["name"])
        values = entry.get("values", [])
        if field and values:
            fields[field] = values[0].get("value")

    return MediaInsights(**fields)
