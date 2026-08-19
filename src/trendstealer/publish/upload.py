"""Video delivery to Meta for Reels publishing.

The Content Publishing API's /media endpoint does not accept a local file
directly. Two paths, both producing a "creation_id" container that
media_publish() later promotes to a live post:

Path A (default, resumable upload): create a container with
upload_type=resumable, which returns an upload URI; stream the video bytes
to that URI via the same resumable-upload protocol Meta's other upload
APIs use (Authorization: OAuth <token>, offset/file_size headers).

Path B (fallback): upload the file to our own presigned host first (see
UPLOAD_HOST_* in .env.example) and pass the resulting public URL as
video_url when creating the container -- for when path A's resumable
protocol is unavailable or misbehaving.

get_video_reference() hides the choice behind one call. NOTE: this
endpoint family has changed shape more than once historically -- the
plan calls for proving path A with a manual curl during M0 before
depending on it in production; this module has not been exercised
against a live Instagram Business account.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from trendstealer.publish.base import ExpiredTokenError

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class UploadError(RuntimeError):
    pass


def create_resumable_container(
    *,
    business_account_id: str,
    access_token: str,
    caption: str,
    client: httpx.Client,
    graph_api_base: str = GRAPH_API_BASE,
) -> tuple[str, str]:
    """Returns (container_id, upload_uri)."""
    response = client.post(
        f"{graph_api_base}/{business_account_id}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "access_token": access_token,
        },
    )
    _raise_for_graph_error(response)
    data = response.json()
    return data["id"], data["uri"]


def create_url_container(
    *,
    business_account_id: str,
    access_token: str,
    caption: str,
    video_url: str,
    client: httpx.Client,
    graph_api_base: str = GRAPH_API_BASE,
) -> str:
    """Path B: container created directly from a publicly reachable video_url.

    Required (only option) for tokens issued via Instagram Login -- that
    auth flow has no resumable-upload endpoint, per Meta's docs; Path A is
    Facebook-Login-for-Business only.
    """
    response = client.post(
        f"{graph_api_base}/{business_account_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
    )
    _raise_for_graph_error(response)
    return response.json()["id"]  # type: ignore[no-any-return]


def upload_resumable_bytes(
    *, upload_uri: str, access_token: str, video_path: Path, client: httpx.Client
) -> None:
    file_size = video_path.stat().st_size
    with video_path.open("rb") as f:
        response = client.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(file_size),
            },
            content=f.read(),
        )
    if response.status_code >= 400:
        raise UploadError(f"resumable upload failed: {response.status_code} {response.text}")


def get_video_reference(
    *,
    business_account_id: str,
    access_token: str,
    caption: str,
    video_path: Path,
    client: httpx.Client,
    video_url: str | None = None,
    graph_api_base: str = GRAPH_API_BASE,
) -> str:
    """Creates a media container and (path A only) uploads the video bytes
    to it. Returns the container_id, ready to poll then media_publish()."""
    if video_url is not None:
        return create_url_container(
            business_account_id=business_account_id,
            access_token=access_token,
            caption=caption,
            video_url=video_url,
            client=client,
            graph_api_base=graph_api_base,
        )

    container_id, upload_uri = create_resumable_container(
        business_account_id=business_account_id,
        access_token=access_token,
        caption=caption,
        client=client,
        graph_api_base=graph_api_base,
    )
    upload_resumable_bytes(
        upload_uri=upload_uri, access_token=access_token, video_path=video_path, client=client
    )
    return container_id


def _raise_for_graph_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    error: dict[str, Any] = {}
    message = response.text
    try:
        payload: dict[str, Any] = response.json()
        error = payload.get("error", {})
        message = error.get("message", response.text)
    except ValueError:
        pass
    if error.get("code") == 190:
        raise ExpiredTokenError(f"access token expired or invalid: {message}")
    raise UploadError(f"Graph API error {response.status_code}: {message}")
