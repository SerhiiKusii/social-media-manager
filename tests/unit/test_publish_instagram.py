from pathlib import Path

import httpx
import pytest
import respx

from trendstealer.publish.base import PublishError
from trendstealer.publish.instagram import GRAPH_API_BASE, ExpiredTokenError, InstagramPublisher

BUSINESS_ACCOUNT_ID = "ig-biz-1"
CONTAINER_ID = "container-1"
UPLOAD_URI = "https://rupload.facebook.com/ig-api-upload/v21.0/container-1"
MEDIA_ID = "media-1"


@pytest.fixture
def video_path(tmp_path: Path) -> Path:
    path = tmp_path / "out.mp4"
    path.write_bytes(b"fake mp4 bytes")
    return path


def _publisher() -> InstagramPublisher:
    return InstagramPublisher(
        business_account_id=BUSINESS_ACCOUNT_ID,
        client=httpx.Client(),
        poll_interval_secs=0.0,
        poll_timeout_secs=5.0,
    )


@respx.mock
def test_full_publish_flow_happy_path(video_path: Path) -> None:
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media").mock(
        return_value=httpx.Response(200, json={"id": CONTAINER_ID, "uri": UPLOAD_URI})
    )
    respx.post(UPLOAD_URI).mock(return_value=httpx.Response(200, json={"success": True}))
    respx.get(f"{GRAPH_API_BASE}/{CONTAINER_ID}").mock(
        return_value=httpx.Response(200, json={"status_code": "FINISHED"})
    )
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media_publish").mock(
        return_value=httpx.Response(200, json={"id": MEDIA_ID})
    )
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}").mock(
        return_value=httpx.Response(200, json={"permalink": "https://instagram.com/p/abc"})
    )

    result = _publisher().publish(
        video_path=video_path, caption="hello #AIGenerated", access_token="tok"
    )

    assert result.platform_media_id == MEDIA_ID
    assert result.permalink == "https://instagram.com/p/abc"


@respx.mock
def test_polling_loop_waits_for_finished(video_path: Path) -> None:
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media").mock(
        return_value=httpx.Response(200, json={"id": CONTAINER_ID, "uri": UPLOAD_URI})
    )
    respx.post(UPLOAD_URI).mock(return_value=httpx.Response(200, json={"success": True}))
    respx.get(f"{GRAPH_API_BASE}/{CONTAINER_ID}").mock(
        side_effect=[
            httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
            httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
            httpx.Response(200, json={"status_code": "FINISHED"}),
        ]
    )
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media_publish").mock(
        return_value=httpx.Response(200, json={"id": MEDIA_ID})
    )
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}").mock(
        return_value=httpx.Response(200, json={"permalink": None})
    )

    result = _publisher().publish(video_path=video_path, caption="cap", access_token="tok")
    assert result.platform_media_id == MEDIA_ID


@respx.mock
def test_container_error_status_raises(video_path: Path) -> None:
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media").mock(
        return_value=httpx.Response(200, json={"id": CONTAINER_ID, "uri": UPLOAD_URI})
    )
    respx.post(UPLOAD_URI).mock(return_value=httpx.Response(200, json={"success": True}))
    respx.get(f"{GRAPH_API_BASE}/{CONTAINER_ID}").mock(
        return_value=httpx.Response(200, json={"status_code": "ERROR"})
    )

    with pytest.raises(PublishError, match="ERROR"):
        _publisher().publish(video_path=video_path, caption="cap", access_token="tok")


@respx.mock
def test_429_with_retry_after_is_retried_during_polling(video_path: Path) -> None:
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media").mock(
        return_value=httpx.Response(200, json={"id": CONTAINER_ID, "uri": UPLOAD_URI})
    )
    respx.post(UPLOAD_URI).mock(return_value=httpx.Response(200, json={"success": True}))
    respx.get(f"{GRAPH_API_BASE}/{CONTAINER_ID}").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"status_code": "FINISHED"}),
        ]
    )
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media_publish").mock(
        return_value=httpx.Response(200, json={"id": MEDIA_ID})
    )
    respx.get(f"{GRAPH_API_BASE}/{MEDIA_ID}").mock(
        return_value=httpx.Response(200, json={"permalink": None})
    )

    result = _publisher().publish(video_path=video_path, caption="cap", access_token="tok")
    assert result.platform_media_id == MEDIA_ID


@respx.mock
def test_expired_token_error_code_190_raises_expired_token_error(video_path: Path) -> None:
    respx.post(f"{GRAPH_API_BASE}/{BUSINESS_ACCOUNT_ID}/media").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 190, "message": "Error validating access token"}}
        )
    )

    with pytest.raises(ExpiredTokenError):
        _publisher().publish(video_path=video_path, caption="cap", access_token="expired")
