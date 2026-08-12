"""The M7 acceptance test from the implementation plan, verbatim:

fixture Apify + fixture LLM -> item renders -> dashboard "request changes:
make the hook punchier and cut the intro" -> within 2 minutes revision 1
exists with a different on_screen_hook, a new MP4, and status back to
pending_review. Loop 4x and confirm the cap engages.

Real Piper TTS, real faster-whisper captions, real Remotion render --
only the LLM is a fixture. Requires the toolchain from
scripts/install-tools.sh plus the downloaded Piper voice model. Run via
`make test-slow`, never in CI.
"""

import re
from pathlib import Path

import pytest

from trendstealer import db, repo
from trendstealer.commands.worker import run_worker_once
from trendstealer.config import (
    BrandConfig,
    BrandIdentity,
    PublishConfig,
    ViralityConfig,
    get_settings,
)
from trendstealer.intelligence.fixture_backend import FixtureBackend
from trendstealer.review.app import create_app
from trendstealer.states import MAX_REVISIONS, ContentStatus
from trendstealer.tts.piper import PiperBackend

TOKEN = "acceptance-test-token"


@pytest.fixture
def brand() -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(
            id="acme", name="Acme", product_brief="Acme sells time-saving kitchen gadgets."
        ),
        virality=ViralityConfig(),
        publish=PublishConfig(),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "acceptance.db"
    conn = db.connect(path)
    db.upgrade(conn)
    conn.close()
    return path


@pytest.fixture
def seeded_item(db_path: Path) -> int:
    conn = db.connect(db_path)
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, transcript, caption, scraped_at)
        VALUES (?, 'tiktok', 'acceptance-vid', 'wait for it this simple trick saves so much time',
                'a caption', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute(
        "SELECT id FROM trends WHERE platform_video_id = 'acceptance-vid'"
    ).fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)
    conn.close()
    return item_id


@pytest.mark.slow
def test_full_revision_loop_with_real_toolchain_then_cap_engages(
    db_path: Path, seeded_item: int, brand: BrandConfig
) -> None:
    conn = db.connect(db_path)
    llm_backend = FixtureBackend()
    tts_backend = PiperBackend()

    # 1. First worker tick takes the queued item all the way to pending_review.
    claimed = run_worker_once(
        conn, brand=brand, llm_backend=llm_backend, tts_backend=tts_backend, worker_id="w1"
    )
    assert claimed == seeded_item

    item = repo.get_content_item(conn, seeded_item)
    assert item is not None
    assert item["status"] == str(ContentStatus.PENDING_REVIEW)

    revision_0 = repo.list_revisions(conn, seeded_item)[0]
    assert revision_0["video_path"] is not None

    flask_app = create_app(
        db_path=db_path,
        render_root=get_settings().var_dir_abs / "work",
        token=TOKEN,
        allowed_hosts={"localhost"},
    )
    client = flask_app.test_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    def csrf_token() -> str:
        resp = client.get(f"/item/{seeded_item}", headers=headers)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
        assert match is not None
        return match.group(1).decode()

    # 2-4. Request changes MAX_REVISIONS times; each time the worker must
    # produce a new revision with a different hook and land back on
    # pending_review.
    for loop in range(MAX_REVISIONS):
        row = repo.get_content_item(conn, seeded_item)
        assert row is not None
        token = csrf_token()
        resp = client.post(
            f"/item/{seeded_item}/action",
            data={
                "action": "request_changes",
                "version": str(row["version"]),
                "note": f"make the hook punchier, attempt {loop}",
                "csrf_token": token,
            },
            headers=headers,
        )
        assert resp.status_code == 302, resp.data

        claimed = run_worker_once(
            conn, brand=brand, llm_backend=llm_backend, tts_backend=tts_backend, worker_id="w1"
        )
        assert claimed == seeded_item

        item = repo.get_content_item(conn, seeded_item)
        assert item is not None
        assert item["status"] == str(ContentStatus.PENDING_REVIEW)

        revisions = repo.list_revisions(conn, seeded_item)
        assert len(revisions) == loop + 2
        newest = revisions[-1]
        assert newest["revision_no"] == loop + 1
        assert newest["on_screen_hook"] != revisions[-2]["on_screen_hook"]
        assert newest["video_path"] is not None

    # 5. A 4th request_changes must be rejected -- the cap has engaged.
    row = repo.get_content_item(conn, seeded_item)
    assert row is not None
    token = csrf_token()
    resp = client.post(
        f"/item/{seeded_item}/action",
        data={
            "action": "request_changes",
            "version": str(row["version"]),
            "note": "one more please",
            "csrf_token": token,
        },
        headers=headers,
    )
    assert resp.status_code == 409

    # the item must be unchanged by the rejected attempt
    unchanged = repo.get_content_item(conn, seeded_item)
    assert unchanged is not None
    assert unchanged["status"] == str(ContentStatus.PENDING_REVIEW)
    assert len(repo.list_revisions(conn, seeded_item)) == MAX_REVISIONS + 1
