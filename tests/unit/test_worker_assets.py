"""B-roll and intro selection in the render step.

These decide what actually appears on screen, so the load-bearing
assertions are that an uncleared asset is never selected and that
provenance is recorded for the ones that are.
"""

from __future__ import annotations

import sqlite3
import wave
from pathlib import Path

from trendstealer import repo
from trendstealer.commands.worker import _build_intro, _select_broll
from trendstealer.config import (
    BrandBroll,
    BrandConfig,
    BrandIdentity,
    BrandIntro,
    PublishConfig,
    ViralityConfig,
)
from trendstealer.tts.backend import TTSResult


class FakeTTSBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, output_path: Path) -> TTSResult:
        self.calls.append(text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)
        return TTSResult(path=output_path, duration_secs=0.1, sample_rate_hz=16000)


def _brand(*, intro: BrandIntro | None = None, broll: BrandBroll | None = None) -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        intro=intro or BrandIntro(),
        broll=broll or BrandBroll(),
        virality=ViralityConfig(),
        publish=PublishConfig(),
    )


def test_select_broll_returns_nothing_when_no_tag_configured(conn: sqlite3.Connection) -> None:
    repo.upsert_asset(
        conn, path="assets/video/a.mp4", kind="video", license="Pexels", cleared_for_commercial=True
    )
    paths, ids = _select_broll(conn, brand=_brand())
    assert paths == []
    assert ids == []


def test_select_broll_never_picks_an_uncleared_clip(conn: sqlite3.Connection) -> None:
    repo.upsert_asset(
        conn,
        path="assets/video/risky.mp4",
        kind="video",
        license="unknown",
        tags="football",
        cleared_for_commercial=False,
    )
    paths, ids = _select_broll(conn, brand=_brand(broll=BrandBroll(tag="football")))
    assert paths == []
    assert ids == []


def test_select_broll_honours_the_tag_and_count(conn: sqlite3.Connection) -> None:
    for i in range(3):
        repo.upsert_asset(
            conn,
            path=f"assets/video/f{i}.mp4",
            kind="video",
            license="Pexels",
            tags="football",
            cleared_for_commercial=True,
        )
    repo.upsert_asset(
        conn,
        path="assets/video/other.mp4",
        kind="video",
        license="Pexels",
        tags="cooking",
        cleared_for_commercial=True,
    )

    paths, ids = _select_broll(conn, brand=_brand(broll=BrandBroll(tag="football", count=2)))
    assert len(paths) == 2
    assert len(ids) == 2
    assert all("f" in p.name for p in paths)


def test_intro_is_skipped_when_disabled(conn: sqlite3.Connection, tmp_path: Path) -> None:
    intro, ids = _build_intro(
        conn,
        brand=_brand(),
        item_id=1,
        revision_no=0,
        work_dir=tmp_path,
        tts_backend=FakeTTSBackend(),
    )
    assert intro is None
    assert ids == []


def test_intro_is_skipped_when_no_matching_image_exists(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Missing art must not abort the render -- a video without the branded
    lead-in still beats no video at all."""
    config = BrandIntro(enabled=True, image_tag="carlos", titles=["Carlos approves"])
    intro, ids = _build_intro(
        conn,
        brand=_brand(intro=config),
        item_id=1,
        revision_no=0,
        work_dir=tmp_path,
        tts_backend=FakeTTSBackend(),
    )
    assert intro is None
    assert ids == []


def test_intro_builds_from_a_cleared_image_and_synthesizes_its_voiceover(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    asset_id = repo.upsert_asset(
        conn,
        path="assets/photos/carlos2.png",
        kind="image",
        license="user-asserted",
        tags="carlos,intro",
        cleared_for_commercial=True,
    )
    config = BrandIntro(
        enabled=True,
        image_tag="carlos",
        titles=["Carlos approves"],
        voiceover_text="Carlos likes it",
        duration_secs=5.0,
    )
    tts = FakeTTSBackend()
    intro, ids = _build_intro(
        conn,
        brand=_brand(intro=config),
        item_id=1,
        revision_no=0,
        work_dir=tmp_path,
        tts_backend=tts,
    )
    assert intro is not None
    assert intro.title == "Carlos approves"
    assert intro.duration_secs == 5.0
    assert intro.image_path.name == "carlos2.png"
    assert intro.voiceover_path is not None
    assert intro.voiceover_path.exists()
    assert tts.calls == ["Carlos likes it"]
    assert ids == [asset_id]


def test_intro_title_rotates_across_revisions_but_is_stable_per_revision(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A re-render of the same revision must reproduce the same title, while
    a requested change rotates to the next one -- otherwise "make it
    different" can come back identical."""
    repo.upsert_asset(
        conn,
        path="assets/photos/carlos2.png",
        kind="image",
        license="user-asserted",
        tags="carlos",
        cleared_for_commercial=True,
    )
    titles = ["Carlos approves", "Carlos is watching it", "Carlos love it"]
    config = BrandIntro(enabled=True, image_tag="carlos", titles=titles)

    def title_for(revision_no: int) -> str:
        intro, _ = _build_intro(
            conn,
            brand=_brand(intro=config),
            item_id=1,
            revision_no=revision_no,
            work_dir=tmp_path,
            tts_backend=FakeTTSBackend(),
        )
        assert intro is not None
        return intro.title

    assert title_for(0) == title_for(0)  # stable
    assert len({title_for(0), title_for(1), title_for(2)}) == 3  # rotates


def test_voiceover_from_title_speaks_exactly_what_the_title_card_shows(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo.upsert_asset(
        conn,
        path="assets/photos/carlos2.png",
        kind="image",
        license="user-asserted",
        tags="carlos",
        cleared_for_commercial=True,
    )
    config = BrandIntro(
        enabled=True,
        image_tag="carlos",
        titles=["Carlos approves it", "Carlos is watching it", "Carlos loves it"],
        voiceover_from_title=True,
    )
    tts = FakeTTSBackend()
    intro, _ = _build_intro(
        conn,
        brand=_brand(intro=config),
        item_id=1,
        revision_no=0,
        work_dir=tmp_path,
        tts_backend=tts,
    )
    assert intro is not None
    assert tts.calls == [intro.title]


def test_intro_without_titles_is_skipped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo.upsert_asset(
        conn,
        path="assets/photos/carlos2.png",
        kind="image",
        license="x",
        tags="carlos",
        cleared_for_commercial=True,
    )
    config = BrandIntro(enabled=True, image_tag="carlos", titles=[])
    intro, ids = _build_intro(
        conn,
        brand=_brand(intro=config),
        item_id=1,
        revision_no=0,
        work_dir=tmp_path,
        tts_backend=FakeTTSBackend(),
    )
    assert intro is None
    assert ids == []
