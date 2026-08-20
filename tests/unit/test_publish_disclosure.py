import sqlite3
from pathlib import Path

import pytest

from trendstealer import repo
from trendstealer.publish.disclosure import (
    DisclosureError,
    ensure_caption_has_disclosure,
    preflight,
    try_embed_metadata,
    validate_disclosure,
)


def test_ensure_caption_has_disclosure_appends_marker_when_missing() -> None:
    result = ensure_caption_has_disclosure("check out this product")
    assert "#AIGenerated" in result


def test_ensure_caption_has_disclosure_is_idempotent() -> None:
    once = ensure_caption_has_disclosure("caption")
    twice = ensure_caption_has_disclosure(once)
    assert once == twice


def test_validate_disclosure_raises_when_marker_missing() -> None:
    with pytest.raises(DisclosureError):
        validate_disclosure("a caption with no marker")


def test_validate_disclosure_passes_when_marker_present() -> None:
    validate_disclosure("a caption #AIGenerated")  # must not raise


def test_try_embed_metadata_returns_false_when_exiftool_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.publish.disclosure as disclosure_module

    monkeypatch.setattr(disclosure_module.shutil, "which", lambda _name: None)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    assert try_embed_metadata(video_path) is False


def test_preflight_raises_when_caption_missing_disclosure(tmp_path: Path) -> None:
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    with pytest.raises(DisclosureError):
        preflight(video_path=video_path, caption="no marker here")


def test_preflight_passes_with_disclosed_caption_even_without_exiftool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.publish.disclosure as disclosure_module

    monkeypatch.setattr(disclosure_module.shutil, "which", lambda _name: None)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    preflight(video_path=video_path, caption="buy now #AIGenerated")  # must not raise


def _revision_with_asset(
    conn: sqlite3.Connection, *, cleared: bool
) -> int:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, scraped_at)
        VALUES (?, 'tiktok', 'v1', strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute("SELECT id FROM trends WHERE platform_video_id='v1'").fetchone()["id"]
    item_id = repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)
    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=0,
        prompt_version="v1",
        on_screen_hook="hook",
        spoken_script="script",
    )
    asset_id = repo.upsert_asset(
        conn,
        path="assets/video/clip.mp4",
        kind="video",
        license="Pexels" if cleared else "unknown",
        cleared_for_commercial=cleared,
    )
    repo.record_item_assets(conn, revision_id=revision_id, asset_ids=[asset_id], role="broll")
    return revision_id


def test_preflight_refuses_a_revision_containing_an_uncleared_asset(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """The licence gate the architecture promised. Until this was wired up,
    repo.list_uncleared_assets_for_revision had no production caller at all
    -- the check existed but nothing ran it."""
    revision_id = _revision_with_asset(conn, cleared=False)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")

    with pytest.raises(DisclosureError, match="not cleared for commercial use"):
        preflight(
            video_path=video_path,
            caption="buy now #AIGenerated",
            conn=conn,
            revision_id=revision_id,
        )


def test_preflight_allows_a_revision_whose_assets_are_all_cleared(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.publish.disclosure as disclosure_module

    monkeypatch.setattr(disclosure_module.shutil, "which", lambda _name: None)
    revision_id = _revision_with_asset(conn, cleared=True)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")

    preflight(
        video_path=video_path,
        caption="buy now #AIGenerated",
        conn=conn,
        revision_id=revision_id,
    )  # must not raise
