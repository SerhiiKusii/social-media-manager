"""The `publish now` override.

The load-bearing assertions here are asymmetric on purpose: forcing must
beat every *cadence* rule, and must beat none of the *correctness* ones.
The test that `publish run` still denies under identical DB state is what
guarantees the systemd timer can never inherit the bypass.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trendstealer import repo
from trendstealer.commands.publish import ItemNotPublishableError, run_publish_once
from trendstealer.config import (
    BrandConfig,
    BrandIdentity,
    BrandPostingWindows,
    PublishConfig,
    ViralityConfig,
)
from trendstealer.publish.base import DryRunPublisher
from trendstealer.states import ContentStatus


def _brand(
    *, windows: list[str] | None = None, **publish_overrides: object
) -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        posting_windows=BrandPostingWindows(windows=windows or [], timezone="UTC"),
        virality=ViralityConfig(),
        publish=PublishConfig(
            **{"max_posts_per_day": 2, "min_gap_minutes": 240, **publish_overrides}
        ),
    )


def _make_approved_item(
    conn: sqlite3.Connection,
    tmp_path: Path,
    *,
    brand_id: int,
    suffix: str,
    caption: str = "buy now",
) -> int:
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id, f"vid-{suffix}"),
    )
    trend_id = conn.execute(
        "SELECT id FROM trends WHERE platform_video_id = ?", (f"vid-{suffix}",)
    ).fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)

    video_path = tmp_path / f"out-{suffix}.mp4"
    video_path.write_bytes(b"fake mp4")
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook=f"hook {suffix}",
        spoken_script="script",
        script_plan_json=json.dumps({"caption": caption}),
        video_path=str(video_path),
    )
    repo.set_current_revision(conn, item_id, revision_id)
    for src, dst in [
        (ContentStatus.QUEUED, ContentStatus.SYNTHESIZING),
        (ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY),
        (ContentStatus.SCRIPT_READY, ContentStatus.RENDERING),
        (ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW),
        (ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED),
    ]:
        repo.transition(conn, item_id, src, dst, actor="test")
    return int(item_id)


@pytest.fixture
def env(conn: sqlite3.Connection, tmp_path: Path) -> dict[str, int]:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1"
    )
    item_id = _make_approved_item(conn, tmp_path, brand_id=brand_id, suffix="1")
    return {"brand_id": brand_id, "account_id": account_id, "item_id": item_id}


def _publish(
    conn: sqlite3.Connection,
    env: dict[str, int],
    *,
    brand: BrandConfig,
    now: datetime,
    enforce_rate_limit: bool,
    item_id: int | None = None,
):  # noqa: ANN202 - PublishOutcome | None, inferred
    return run_publish_once(
        conn,
        brand=brand,
        brand_id=env["brand_id"],
        account_id=env["account_id"],
        publisher=DryRunPublisher(),
        access_token="tok",
        now=now,
        enforce_rate_limit=enforce_rate_limit,
        item_id=item_id,
        actor="publisher:forced" if not enforce_rate_limit else "publisher",
        note="rate limiter bypassed via `publish now`" if not enforce_rate_limit else None,
    )


def _record_prior_publication(
    conn: sqlite3.Connection, env: dict[str, int], tmp_path: Path, *, when: datetime, suffix: str
) -> None:
    other_id = _make_approved_item(conn, tmp_path, brand_id=env["brand_id"], suffix=suffix)
    revision_id = repo.get_content_item(conn, other_id)["current_revision_id"]
    repo.create_publication(
        conn,
        content_item_id=other_id,
        revision_id=revision_id,
        brand_id=env["brand_id"],
        platform="instagram",
        account_id=env["account_id"],
        idempotency_key=f"prior-{suffix}",
        platform_media_id="m-prior",
        status="published",
        published_at=when,
    )


# --- forcing beats every cadence rule ---------------------------------------


def test_force_publishes_outside_the_posting_window(
    conn: sqlite3.Connection, env: dict[str, int]
) -> None:
    outside = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    brand = _brand(windows=["09:00-11:00"], min_gap_minutes=0)

    assert _publish(conn, env, brand=brand, now=outside, enforce_rate_limit=True) is None

    outcome = _publish(conn, env, brand=brand, now=outside, enforce_rate_limit=False)
    assert outcome is not None
    assert outcome.status == "published"


def test_force_publishes_before_min_gap_has_elapsed(
    conn: sqlite3.Connection, env: dict[str, int], tmp_path: Path
) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _record_prior_publication(
        conn, env, tmp_path, when=now - timedelta(minutes=30), suffix="prior-gap"
    )
    brand = _brand(min_gap_minutes=240)

    assert _publish(conn, env, brand=brand, now=now, enforce_rate_limit=True) is None

    outcome = _publish(conn, env, brand=brand, now=now, enforce_rate_limit=False)
    assert outcome is not None
    assert outcome.status == "published"


def test_force_publishes_past_the_daily_cap(
    conn: sqlite3.Connection, env: dict[str, int], tmp_path: Path
) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for i in range(2):
        _record_prior_publication(
            conn, env, tmp_path, when=now - timedelta(hours=i + 1), suffix=f"cap{i}"
        )
    brand = _brand(max_posts_per_day=2, min_gap_minutes=0)

    assert _publish(conn, env, brand=brand, now=now, enforce_rate_limit=True) is None

    outcome = _publish(conn, env, brand=brand, now=now, enforce_rate_limit=False)
    assert outcome is not None
    assert outcome.status == "published"


# --- ...and none of the correctness ones ------------------------------------


def test_force_still_refuses_an_uncleared_asset(
    conn: sqlite3.Connection, env: dict[str, int]
) -> None:
    """The licence gate is the last thing standing once the operator has
    deliberately skipped the rate limiter, so forcing must not skip it."""
    revision_id = repo.get_content_item(conn, env["item_id"])["current_revision_id"]
    asset_id = repo.upsert_asset(
        conn,
        path="assets/video/risky.mp4",
        kind="video",
        license="unknown",
        cleared_for_commercial=False,
    )
    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[asset_id], role="broll")

    outcome = _publish(
        conn,
        env,
        brand=_brand(min_gap_minutes=0),
        now=datetime.now(UTC),
        enforce_rate_limit=False,
    )
    assert outcome is not None
    assert outcome.status == "failed"
    assert "not cleared for commercial use" in (outcome.reason or "")

    row = repo.get_content_item(conn, env["item_id"])
    assert row["status"] == str(ContentStatus.APPROVED)  # never left the gate


def test_force_cannot_publish_an_unapproved_item(
    conn: sqlite3.Connection, env: dict[str, int], tmp_path: Path
) -> None:
    """Naming an item by id must never fall back to publishing whatever is
    oldest -- that would post something the operator did not ask for."""
    brand_id = env["brand_id"]
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', 'vid-pending', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute(
        "SELECT id FROM trends WHERE platform_video_id = 'vid-pending'"
    ).fetchone()["id"]
    pending_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)

    with pytest.raises(ItemNotPublishableError) as excinfo:
        _publish(
            conn,
            env,
            brand=_brand(min_gap_minutes=0),
            now=datetime.now(UTC),
            enforce_rate_limit=False,
            item_id=pending_id,
        )
    assert "not 'approved'" in str(excinfo.value)

    # the genuinely-approved item was left alone
    assert repo.get_content_item(conn, env["item_id"])["status"] == str(ContentStatus.APPROVED)


def test_force_on_a_missing_item_raises(conn: sqlite3.Connection, env: dict[str, int]) -> None:
    with pytest.raises(ItemNotPublishableError):
        _publish(
            conn,
            env,
            brand=_brand(min_gap_minutes=0),
            now=datetime.now(UTC),
            enforce_rate_limit=False,
            item_id=99999,
        )


# --- audit trail ------------------------------------------------------------


def test_forced_publish_is_recorded_in_status_events(
    conn: sqlite3.Connection, env: dict[str, int]
) -> None:
    """Editing config to force a post left no trace; this must."""
    _publish(
        conn,
        env,
        brand=_brand(min_gap_minutes=0),
        now=datetime.now(UTC),
        enforce_rate_limit=False,
    )
    events = repo.list_status_events(conn, env["item_id"])
    forced = [e for e in events if e["to_status"] == str(ContentStatus.PUBLISHING)]
    assert len(forced) == 1
    assert forced[0]["actor"] == "publisher:forced"
    assert "bypassed" in forced[0]["note"]


def test_unforced_publish_records_the_plain_actor(
    conn: sqlite3.Connection, env: dict[str, int]
) -> None:
    _publish(
        conn,
        env,
        brand=_brand(min_gap_minutes=0),
        now=datetime.now(UTC),
        enforce_rate_limit=True,
    )
    events = repo.list_status_events(conn, env["item_id"])
    publishing = [e for e in events if e["to_status"] == str(ContentStatus.PUBLISHING)]
    assert publishing[0]["actor"] == "publisher"
    assert publishing[0]["note"] is None


def test_item_id_targets_that_item_not_the_oldest_approved(
    conn: sqlite3.Connection, env: dict[str, int], tmp_path: Path
) -> None:
    newer_id = _make_approved_item(conn, tmp_path, brand_id=env["brand_id"], suffix="newer")

    outcome = _publish(
        conn,
        env,
        brand=_brand(min_gap_minutes=0),
        now=datetime.now(UTC),
        enforce_rate_limit=False,
        item_id=newer_id,
    )
    assert outcome is not None
    assert outcome.item_id == newer_id
    assert repo.get_content_item(conn, newer_id)["status"] == str(ContentStatus.PUBLISHED)
    assert repo.get_content_item(conn, env["item_id"])["status"] == str(ContentStatus.APPROVED)
