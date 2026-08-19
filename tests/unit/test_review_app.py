import re
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from trendstealer import db, repo
from trendstealer.review.app import create_app
from trendstealer.states import ContentStatus

TOKEN = "test-token-123"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.upgrade(conn)
    conn.close()
    return path


@pytest.fixture
def render_root(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir()
    return root


@pytest.fixture
def seeded_item(db_path: Path, render_root: Path) -> dict[str, int | Path]:
    conn = db.connect(db_path)
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    conn.execute(
        """
        INSERT INTO scrape_runs (brand_id, platform, actor_id, started_at, status)
        VALUES (?, 'tiktok', 'test-actor', strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'succeeded')
        """,
        (brand_id,),
    )
    run_id = conn.execute("SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO trends
            (scrape_run_id, brand_id, platform, platform_video_id, caption, scraped_at)
        VALUES (?, ?, 'tiktok', 'vid123', 'original caption', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (run_id, brand_id),
    )
    trend_id = conn.execute("SELECT id FROM trends WHERE platform_video_id='vid123'").fetchone()[
        "id"
    ]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)

    video_path = render_root / str(item_id) / "out_r0.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"fake mp4 bytes")

    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="hook_transfer_v1",
        on_screen_hook="Wait for it",
        spoken_script="script text",
        video_path=str(video_path),
    )
    repo.set_current_revision(conn, item_id, revision_id)
    repo.transition(conn, item_id, ContentStatus.QUEUED, ContentStatus.SYNTHESIZING, actor="test")
    repo.transition(
        conn, item_id, ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY, actor="test"
    )
    repo.transition(
        conn, item_id, ContentStatus.SCRIPT_READY, ContentStatus.RENDERING, actor="test"
    )
    result = repo.transition(
        conn, item_id, ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW, actor="test"
    )
    conn.close()
    return {"item_id": item_id, "video_path": video_path, "version": result.version}


@pytest.fixture
def client(db_path: Path, render_root: Path) -> FlaskClient:
    app = create_app(
        db_path=db_path,
        render_root=render_root,
        token=TOKEN,
        allowed_hosts={"localhost"},
    )
    app.config["TESTING"] = True
    return app.test_client()


def _csrf_token(client: FlaskClient, item_id: int) -> str:
    resp = client.get(f"/item/{item_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    match = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
    assert match is not None
    return match.group(1).decode()


def test_missing_token_is_rejected(client: FlaskClient) -> None:
    resp = client.get("/queue")
    assert resp.status_code == 401


def test_wrong_host_is_rejected(db_path: Path, render_root: Path) -> None:
    app = create_app(
        db_path=db_path, render_root=render_root, token=TOKEN, allowed_hosts={"only-this-host"}
    )
    resp = app.test_client().get("/queue", headers=AUTH_HEADERS)
    assert resp.status_code == 400


def test_queue_lists_pending_review_item(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    resp = client.get("/queue", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert f"#{seeded_item['item_id']}".encode() in resp.data


def test_post_without_csrf_token_is_rejected(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    item_id = seeded_item["item_id"]
    resp = client.post(
        f"/item/{item_id}/action",
        data={"action": "approve", "version": "1"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 400


def test_status_injection_action_is_rejected(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    """The original architecture's bug: an action string mapped straight to
    an arbitrary status. 'published' is not in ACTION_TO_STATUS, so this
    must 400 even with a valid CSRF token and version."""
    item_id = seeded_item["item_id"]
    token = _csrf_token(client, item_id)
    resp = client.post(
        f"/item/{item_id}/action",
        data={"action": "published", "version": "1", "csrf_token": token},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 400


def test_approve_transitions_item_and_redirects(
    client: FlaskClient, seeded_item: dict[str, int | Path], db_path: Path
) -> None:
    item_id = seeded_item["item_id"]
    token = _csrf_token(client, item_id)
    resp = client.post(
        f"/item/{item_id}/action",
        data={"action": "approve", "version": str(seeded_item["version"]), "csrf_token": token},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 302

    conn = db.connect(db_path)
    row = repo.get_content_item(conn, item_id)
    assert row["status"] == str(ContentStatus.APPROVED)


def test_queue_still_shows_item_after_changes_requested(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    item_id = seeded_item["item_id"]
    token = _csrf_token(client, item_id)
    resp = client.post(
        f"/item/{item_id}/action",
        data={
            "action": "request_changes",
            "version": str(seeded_item["version"]),
            "note": "punchier hook",
            "csrf_token": token,
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 302

    resp = client.get("/queue", headers=AUTH_HEADERS)
    assert f"#{item_id}".encode() in resp.data
    assert b"changes_requested" in resp.data


def test_stale_version_is_rejected_with_409(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    item_id = seeded_item["item_id"]
    token = _csrf_token(client, item_id)
    resp = client.post(
        f"/item/{item_id}/action",
        data={"action": "approve", "version": "999", "csrf_token": token},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 409


def test_media_video_serves_the_real_file(
    client: FlaskClient, seeded_item: dict[str, int | Path]
) -> None:
    item_id = seeded_item["item_id"]
    resp = client.get(f"/media/{item_id}/video", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.data == b"fake mp4 bytes"


def test_media_video_outside_render_root_is_rejected(
    client: FlaskClient, seeded_item: dict[str, int | Path], db_path: Path, tmp_path: Path
) -> None:
    """Defense-in-depth: even if a revisions.video_path ever pointed outside
    render_root (bug elsewhere, corrupted row), this endpoint refuses to
    serve it rather than trusting the DB value blindly."""
    item_id = seeded_item["item_id"]
    outside_path = tmp_path / "outside" / "secret.mp4"
    outside_path.parent.mkdir()
    outside_path.write_bytes(b"should never be served")

    conn = db.connect(db_path)
    conn.execute(
        "UPDATE revisions SET video_path = ? WHERE content_item_id = ?",
        (str(outside_path), item_id),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/media/{item_id}/video", headers=AUTH_HEADERS)
    assert resp.status_code == 400
