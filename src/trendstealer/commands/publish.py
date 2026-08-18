from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trendstealer import repo
from trendstealer.config import BrandConfig
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


@dataclass(frozen=True)
class PublishOutcome:
    item_id: int
    status: str  # "published" | "failed"
    reason: str | None = None


def run_publish_once(
    conn: sqlite3.Connection,
    *,
    brand: BrandConfig,
    brand_id: int,
    account_id: int,
    publisher: Publisher,
    access_token: str,
    now: datetime | None = None,
) -> PublishOutcome | None:
    """Rate-gates, then publishes at most one item (oldest-approved-first)
    per call. Returns None when the gate denies or there's nothing
    approved -- neither is an error, just nothing to do this tick."""
    now = now or datetime.now(UTC)

    verdict = check_rate_limit(conn, brand_id=brand_id, brand=brand, now=now)
    if not verdict.allowed:
        logger.info("publish_rate_limited", brand_id=brand_id, reason=verdict.reason)
        return None

    approved = repo.list_approved_items(conn, brand_id=brand_id)
    if not approved:
        return None

    item = approved[0]
    item_id = item["id"]
    revision = repo.get_revision(conn, item["current_revision_id"])
    assert revision is not None

    plan = json.loads(revision["script_plan_json"])
    caption = ensure_caption_has_disclosure(plan["caption"])
    video_path = Path(revision["video_path"])
    idempotency_key = f"{item_id}:{revision['id']}:instagram"

    try:
        preflight(video_path=video_path, caption=caption)
    except DisclosureError as exc:
        logger.warning("publish_preflight_failed", item_id=item_id, reason=str(exc))
        return PublishOutcome(item_id=item_id, status="failed", reason=str(exc))

    repo.transition(
        conn, item_id, ContentStatus.APPROVED, ContentStatus.PUBLISHING, actor="publisher"
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
    repo.transition(
        conn, item_id, ContentStatus.PUBLISHING, ContentStatus.PUBLISHED, actor="publisher"
    )
    return PublishOutcome(item_id=item_id, status="published")
