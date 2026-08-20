from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trendstealer import repo
from trendstealer.config import BrandConfig, Settings
from trendstealer.logging import get_logger
from trendstealer.publish.base import Publisher
from trendstealer.publish.disclosure import (
    DisclosureError,
    ensure_caption_has_disclosure,
    preflight,
)
from trendstealer.publish.ratelimit import check_rate_limit
from trendstealer.states import ContentStatus

logger = get_logger(__name__)


class MissingCredentialsError(RuntimeError):
    """Live publish mode without an IG token / account id."""


def build_publisher(
    settings: Settings, brand: BrandConfig
) -> tuple[Publisher, str, str]:
    """(publisher, access_token, business_account_id) for the configured mode.

    Single source of truth for how a publisher is wired up -- which upload
    path, which Graph host, whether a tunnel provides the public video_url.
    Both `publish run` and `publish now` go through here so a forced publish
    is byte-for-byte the same operation as a scheduled one.
    """
    import os

    from trendstealer.publish.base import DryRunPublisher
    from trendstealer.publish.instagram import InstagramPublisher
    from trendstealer.publish.upload import GRAPH_API_BASE

    access_token = brand.instagram_access_token()
    business_account_id = brand.instagram_business_account_id()

    if settings.publish_mode != "live":
        return (
            DryRunPublisher(),
            access_token or "dry-run",
            business_account_id or "dry-run-account",
        )

    if not access_token or not business_account_id:
        raise MissingCredentialsError("IG_ACCESS_TOKEN / IG_BUSINESS_ACCOUNT_ID are not set")

    video_url_provider = None
    if os.environ.get("TRENDSTEALER_PUBLISH_TUNNEL") == "cloudflared":
        from trendstealer.publish.tunnel import serve_video_publicly

        video_url_provider = serve_video_publicly

    publisher = InstagramPublisher(
        business_account_id=business_account_id,
        graph_api_base=os.environ.get("TRENDSTEALER_GRAPH_API_BASE", GRAPH_API_BASE),
        video_url_provider=video_url_provider,
    )
    return publisher, access_token, business_account_id


@dataclass(frozen=True)
class PublishOutcome:
    item_id: int
    status: str  # "published" | "failed"
    reason: str | None = None


class ItemNotPublishableError(ValueError):
    """A specifically-requested item is not in `approved`.

    Distinct from "nothing to publish" (None): asking for item 7 by id and
    getting silence would be indistinguishable from an empty queue, and the
    tempting fallback -- publishing the oldest approved item instead -- would
    post something the operator did not name.
    """

    def __init__(self, item_id: int, status: str) -> None:
        self.item_id = item_id
        self.status = status
        super().__init__(f"item {item_id} is '{status}', not 'approved' -- refusing to publish it")


def _pick_item(
    conn: sqlite3.Connection, *, brand_id: int, item_id: int | None
) -> sqlite3.Row | None:
    if item_id is None:
        approved = repo.list_approved_items(conn, brand_id=brand_id)
        return approved[0] if approved else None

    item = repo.get_content_item(conn, item_id)
    if item is None:
        raise ItemNotPublishableError(item_id, "missing")
    if item["status"] != ContentStatus.APPROVED:
        raise ItemNotPublishableError(item_id, str(item["status"]))
    return item


def run_publish_once(
    conn: sqlite3.Connection,
    *,
    brand: BrandConfig,
    brand_id: int,
    account_id: int,
    publisher: Publisher,
    access_token: str,
    now: datetime | None = None,
    enforce_rate_limit: bool = True,
    item_id: int | None = None,
    actor: str = "publisher",
    note: str | None = None,
) -> PublishOutcome | None:
    """Rate-gates, then publishes at most one item (oldest-approved-first)
    per call. Returns None when the gate denies or there's nothing
    approved -- neither is an error, just nothing to do this tick.

    `enforce_rate_limit=False` is the `publish now` override. It skips the
    cadence checks only: the review gate (APPROVED is the sole legal source
    status), preflight/disclosure, and the publications idempotency key all
    still apply, so forcing can change *when* something posts but can never
    post something unapproved, unlicensed, or twice. Callers that pass it
    must also pass `actor`/`note` so the bypass is visible in status_events.
    """
    now = now or datetime.now(UTC)

    if enforce_rate_limit:
        verdict = check_rate_limit(conn, brand_id=brand_id, brand=brand, now=now)
        if not verdict.allowed:
            logger.info("publish_rate_limited", brand_id=brand_id, reason=verdict.reason)
            return None

    item = _pick_item(conn, brand_id=brand_id, item_id=item_id)
    if item is None:
        return None

    item_id = item["id"]
    assert item_id is not None
    revision = repo.get_revision(conn, item["current_revision_id"])
    assert revision is not None

    plan = json.loads(revision["script_plan_json"])
    caption = ensure_caption_has_disclosure(plan["caption"])
    video_path = Path(revision["video_path"])
    idempotency_key = f"{item_id}:{revision['id']}:instagram"

    try:
        preflight(
            video_path=video_path, caption=caption, conn=conn, revision_id=revision["id"]
        )
    except DisclosureError as exc:
        logger.warning("publish_preflight_failed", item_id=item_id, reason=str(exc))
        return PublishOutcome(item_id=item_id, status="failed", reason=str(exc))

    repo.transition(
        conn,
        item_id,
        ContentStatus.APPROVED,
        ContentStatus.PUBLISHING,
        actor=actor,
        note=note,
    )

    try:
        result = publisher.publish(
            video_path=video_path, caption=caption, access_token=access_token
        )
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised as a failed transition
        repo.create_publication(
            conn,
            content_item_id=item_id,
            revision_id=revision["id"],
            brand_id=brand_id,
            platform="instagram",
            account_id=account_id,
            idempotency_key=idempotency_key,
            status="failed",
            error=str(exc),
            published_at=now,
        )
        repo.transition(
            conn,
            item_id,
            ContentStatus.PUBLISHING,
            ContentStatus.PUBLISH_FAILED,
            actor="publisher",
            note=str(exc),
        )
        return PublishOutcome(item_id=item_id, status="failed", reason=str(exc))

    # Past this point the Reel is live and nothing local can undo it. A
    # failure here is a bookkeeping failure, not a publish failure -- it
    # must never be reported as "failed" (that would invite a retry that
    # double-posts) and must never leave the item wedged in `publishing`.
    # Log the platform ids loudly so the row can be reconciled by hand.
    try:
        repo.create_publication(
            conn,
            content_item_id=item_id,
            revision_id=revision["id"],
            brand_id=brand_id,
            platform="instagram",
            account_id=account_id,
            idempotency_key=idempotency_key,
            platform_media_id=result.platform_media_id,
            permalink=result.permalink,
            status="published",
            published_at=now,
        )
    except Exception:
        logger.exception(
            "publish_recorded_failed_but_post_is_live",
            item_id=item_id,
            revision_id=revision["id"],
            platform_media_id=result.platform_media_id,
            permalink=result.permalink,
        )

    repo.transition(
        conn, item_id, ContentStatus.PUBLISHING, ContentStatus.PUBLISHED, actor="publisher"
    )
    return PublishOutcome(item_id=item_id, status="published")
