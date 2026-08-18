import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trendstealer import repo
from trendstealer.commands.publish import run_publish_once
from trendstealer.config import (
    BrandConfig,
    BrandIdentity,
    BrandPostingWindows,
    PublishConfig,
    ViralityConfig,
)
from trendstealer.publish.base import DryRunPublisher, PublishResult
from trendstealer.states import ContentStatus


def _brand() -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        posting_windows=BrandPostingWindows(windows=[], timezone="UTC"),
        virality=ViralityConfig(),
        publish=PublishConfig(max_posts_per_day=2, min_gap_minutes=0),
    )


@pytest.fixture
def approved_item(conn: sqlite3.Connection, tmp_path: Path) -> dict[str, int]:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1"
    )
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', 'vid1', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute("SELECT id FROM trends WHERE platform_video_id='vid1'").fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)

    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake mp4")
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook="hook",
        spoken_script="script",
        script_plan_json=json.dumps({"caption": "buy now"}),
        video_path=str(video_path),
    )
    repo.set_current_revision(conn, item_id, revision_id)

    for edge in [
        (ContentStatus.QUEUED, ContentStatus.SYNTHESIZING),
        (ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY),
        (ContentStatus.SCRIPT_READY, ContentStatus.RENDERING),
        (ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW),
        (ContentStatus.PENDING_REVIEW, ContentStatus.APPROVED),
    ]:
        repo.transition(conn, item_id, edge[0], edge[1], actor="test")

    return {"brand_id": brand_id, "account_id": account_id, "item_id": item_id}


def test_publish_dry_run_transitions_to_published(
    conn: sqlite3.Connection, approved_item: dict[str, int]
) -> None:
    outcome = run_publish_once(
        conn,
        brand=_brand(),
        brand_id=approved_item["brand_id"],
        account_id=approved_item["account_id"],
        publisher=DryRunPublisher(),
        access_token="dry-run",
        now=datetime.now(UTC),
    )
    assert outcome is not None
    assert outcome.status == "published"

    row = repo.get_content_item(conn, approved_item["item_id"])
    assert row is not None
    assert row["status"] == str(ContentStatus.PUBLISHED)


def test_publish_caption_gets_disclosure_marker_appended(
    conn: sqlite3.Connection, approved_item: dict[str, int]
) -> None:
    class RecordingPublisher:
        captions: list[str] = []

        def publish(self, *, video_path: Path, caption: str, access_token: str) -> PublishResult:
            self.captions.append(caption)
            return PublishResult(platform_media_id="m1", permalink=None)

    publisher = RecordingPublisher()
    run_publish_once(
        conn,
        brand=_brand(),
        brand_id=approved_item["brand_id"],
        account_id=approved_item["account_id"],
        publisher=publisher,
        access_token="tok",
        now=datetime.now(UTC),
    )
    assert "#AIGenerated" in publisher.captions[0]


def test_publish_failure_transitions_to_publish_failed_and_records_error(
    conn: sqlite3.Connection, approved_item: dict[str, int]
) -> None:
    class FailingPublisher:
        def publish(self, *, video_path: Path, caption: str, access_token: str) -> PublishResult:
            raise RuntimeError("simulated Graph API failure")

    outcome = run_publish_once(
        conn,
        brand=_brand(),
        brand_id=approved_item["brand_id"],
        account_id=approved_item["account_id"],
        publisher=FailingPublisher(),
        access_token="tok",
        now=datetime.now(UTC),
    )
    assert outcome is not None
    assert outcome.status == "failed"

    row = repo.get_content_item(conn, approved_item["item_id"])
    assert row is not None
    assert row["status"] == str(ContentStatus.PUBLISH_FAILED)

    pub = conn.execute(
        "SELECT * FROM publications WHERE content_item_id = ?", (approved_item["item_id"],)
    ).fetchone()
    assert pub["status"] == "failed"
    assert "simulated Graph API failure" in pub["error"]


def test_publish_returns_none_when_nothing_approved(conn: sqlite3.Connection) -> None:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    account_id = repo.upsert_account(
        conn, brand_id=brand_id, platform="instagram", platform_account_id="ig-1"
    )
    outcome = run_publish_once(
        conn,
        brand=_brand(),
        brand_id=brand_id,
        account_id=account_id,
        publisher=DryRunPublisher(),
        access_token="tok",
        now=datetime.now(UTC),
    )
    assert outcome is None


def test_publish_returns_none_when_rate_limited(
    conn: sqlite3.Connection, approved_item: dict[str, int]
) -> None:
    brand = BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        posting_windows=BrandPostingWindows(windows=[], timezone="UTC"),
        virality=ViralityConfig(),
        publish=PublishConfig(max_posts_per_day=0, min_gap_minutes=0),
    )
    outcome = run_publish_once(
        conn,
        brand=brand,
        brand_id=approved_item["brand_id"],
        account_id=approved_item["account_id"],
        publisher=DryRunPublisher(),
        access_token="tok",
        now=datetime.now(UTC),
    )
    assert outcome is None
    row = repo.get_content_item(conn, approved_item["item_id"])
    assert row is not None
    assert row["status"] == str(ContentStatus.APPROVED)  # untouched


def test_double_publish_with_same_idempotency_key_raises_integrity_error(
    conn: sqlite3.Connection, approved_item: dict[str, int]
) -> None:
    kwargs = dict(
        content_item_id=approved_item["item_id"],
        revision_id=repo.get_content_item(conn, approved_item["item_id"])["current_revision_id"],
        brand_id=approved_item["brand_id"],
        platform="instagram",
        account_id=approved_item["account_id"],
        idempotency_key="fixed-key",
        platform_media_id="m1",
        status="published",
    )
    repo.create_publication(conn, **kwargs)
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_publication(conn, **kwargs)
