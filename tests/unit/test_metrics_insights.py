import httpx
import pytest
import respx

from trendstealer.metrics.instagram_insights import (
    GRAPH_API_BASE,
    InsightsError,
    fetch_media_insights,
)

MEDIA_ID = "media-1"


@respx.mock
def test_fetch_media_insights_maps_metric_names() -> None:
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}/insights").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"name": "plays", "period": "lifetime", "values": [{"value": 1000}]},
                    {"name": "likes", "period": "lifetime", "values": [{"value": 50}]},
                    {"name": "comments", "period": "lifetime", "values": [{"value": 5}]},
                    {"name": "shares", "period": "lifetime", "values": [{"value": 2}]},
                    {"name": "saved", "period": "lifetime", "values": [{"value": 3}]},
                    {"name": "reach", "period": "lifetime", "values": [{"value": 900}]},
                ]
            },
        )
    )

    insights = fetch_media_insights(media_id=MEDIA_ID, access_token="tok", client=httpx.Client())
    assert insights.views == 1000
    assert insights.likes == 50
    assert insights.comments == 5
    assert insights.shares == 2
    assert insights.saves == 3
    assert insights.reach == 900


@respx.mock
def test_fetch_media_insights_raises_on_error_status() -> None:
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}/insights").mock(
        return_value=httpx.Response(400, text="bad request")
    )
    with pytest.raises(InsightsError):
        fetch_media_insights(media_id=MEDIA_ID, access_token="tok", client=httpx.Client())


@respx.mock
def test_fetch_media_insights_handles_missing_metrics_gracefully() -> None:
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}/insights").mock(
        return_value=httpx.Response(
            200, json={"data": [{"name": "likes", "values": [{"value": 10}]}]}
        )
    )
    insights = fetch_media_insights(media_id=MEDIA_ID, access_token="tok", client=httpx.Client())
    assert insights.likes == 10
    assert insights.views is None
