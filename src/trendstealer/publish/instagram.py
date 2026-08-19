from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import httpx

from trendstealer.publish.base import ExpiredTokenError, PublishError, PublishResult
from trendstealer.publish.upload import GRAPH_API_BASE, UploadError, get_video_reference


class InstagramPublisher:
    def __init__(
        self,
        *,
        business_account_id: str,
        client: httpx.Client | None = None,
        poll_interval_secs: float = 2.0,
        poll_timeout_secs: float = 120.0,
        video_url: str | None = None,
        video_url_provider: Callable[[Path], AbstractContextManager[str]] | None = None,
        graph_api_base: str = GRAPH_API_BASE,
    ) -> None:
        self.business_account_id = business_account_id
        self.client = client or httpx.Client(timeout=60.0)
        self.poll_interval_secs = poll_interval_secs
        self.poll_timeout_secs = poll_timeout_secs
        self.video_url = video_url
        # For tokens with no resumable-upload path (Instagram Login):
        # video_url_provider(video_path) yields a context manager producing
        # a temporary public URL, kept alive until Meta finishes fetching it.
        self.video_url_provider = video_url_provider
        self.graph_api_base = graph_api_base

    def publish(self, *, video_path: Path, caption: str, access_token: str) -> PublishResult:
        url_cm = (
            self.video_url_provider(video_path)
            if self.video_url_provider is not None
            else nullcontext(self.video_url)
        )
        with url_cm as video_url:
            try:
                container_id = get_video_reference(
                    business_account_id=self.business_account_id,
                    access_token=access_token,
                    caption=caption,
                    video_path=video_path,
                    client=self.client,
                    video_url=video_url,
                    graph_api_base=self.graph_api_base,
                )
            except UploadError as exc:
                raise self._reraise_graph_error(exc) from exc

            self._wait_until_finished(container_id, access_token)

        media_id = self._media_publish(container_id, access_token)
        permalink = self._fetch_permalink(media_id, access_token)
        return PublishResult(platform_media_id=media_id, permalink=permalink)

    def _wait_until_finished(self, container_id: str, access_token: str) -> None:
        deadline = time.monotonic() + self.poll_timeout_secs
        while True:
            response = self.client.get(
                f"{self.graph_api_base}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            if response.status_code == 429:
                time.sleep(float(response.headers.get("retry-after", self.poll_interval_secs)))
                continue
            self._raise_for_error(response)

            status = response.json().get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PublishError(f"container {container_id} failed to process (status ERROR)")
            if time.monotonic() > deadline:
                raise PublishError(f"timed out waiting for container {container_id} to finish")
            time.sleep(self.poll_interval_secs)

    def _media_publish(self, container_id: str, access_token: str) -> str:
        response = self.client.post(
            f"{self.graph_api_base}/{self.business_account_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        self._raise_for_error(response)
        return response.json()["id"]  # type: ignore[no-any-return]

    def _fetch_permalink(self, media_id: str, access_token: str) -> str | None:
        response = self.client.get(
            f"{self.graph_api_base}/{media_id}",
            params={"fields": "permalink", "access_token": access_token},
        )
        self._raise_for_error(response)
        permalink = response.json().get("permalink")
        return str(permalink) if permalink is not None else None

    def _raise_for_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        payload: dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            pass
        error = payload.get("error", {})
        if error.get("code") == 190:
            raise ExpiredTokenError(f"access token expired or invalid: {error.get('message')}")
        raise PublishError(f"Graph API error {response.status_code}: {error or response.text}")

    def _reraise_graph_error(self, exc: UploadError) -> PublishError:
        return PublishError(str(exc))
