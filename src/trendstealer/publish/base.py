from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PublishResult:
    platform_media_id: str
    permalink: str | None


class PublishError(RuntimeError):
    pass


class ExpiredTokenError(PublishError):
    """Graph API error code 190 -- the access token is invalid or expired.

    Raised for any Graph API call, not just the ones instagram.py makes
    directly -- upload.py's container-creation call goes through the same
    check, since a stale token fails there just as often as anywhere else.
    """


class Publisher(Protocol):
    def publish(self, *, video_path: Path, caption: str, access_token: str) -> PublishResult: ...


class DryRunPublisher:
    """The default Publisher (TRENDSTEALER_PUBLISH_MODE=dry_run): records a
    publications row and transitions the item, but makes no network call
    and posts nothing live."""

    def publish(self, *, video_path: Path, caption: str, access_token: str) -> PublishResult:
        return PublishResult(platform_media_id=f"dry-run-{video_path.stem}", permalink=None)
