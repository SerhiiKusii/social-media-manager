"""Fast tests of worker orchestration (transitions, revision persistence,
lease release) using the fixture LLM backend and fakes/monkeypatches for
TTS/captions/render -- the real toolchain versions are exercised by the
slow acceptance test in tests/integration/test_worker_acceptance_slow.py.
"""

import sqlite3
import wave
from pathlib import Path

import pytest

from trendstealer import repo
from trendstealer.captions import WordTiming
from trendstealer.commands import worker as worker_module
from trendstealer.commands.worker import run_worker_once
from trendstealer.config import BrandConfig, BrandIdentity, PublishConfig, ViralityConfig
from trendstealer.intelligence.fixture_backend import FixtureBackend
from trendstealer.render.remotion import RenderResult
from trendstealer.states import ContentStatus
from trendstealer.tts.backend import TTSResult


class FakeTTSBackend:
    def synthesize(self, text: str, output_path: Path) -> TTSResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)  # 0.1s of silence
        return TTSResult(path=output_path, duration_secs=0.1, sample_rate_hz=16000)


@pytest.fixture(autouse=True)
def _stub_transcribe_and_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "transcribe_word_timings",
        lambda path: [WordTiming(word="hi", start=0.0, end=0.1)],
    )

    def _fake_render(props: object, *, composition_id: str = "MainVideo") -> RenderResult:
        out = Path("/tmp") / "fake_render_output.mp4"
        out.write_bytes(b"fake mp4")
        return RenderResult(path=out, render_ms=1)

    monkeypatch.setattr(worker_module, "render_video", _fake_render)


@pytest.fixture
def brand() -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="Acme sells widgets."),
        virality=ViralityConfig(),
        publish=PublishConfig(),
    )


@pytest.fixture
def queued_item(conn: sqlite3.Connection) -> int:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    conn.execute(
        """
        INSERT INTO trends (brand_id, platform, platform_video_id, transcript, caption, scraped_at)
        VALUES (?, 'tiktok', 'wv1', 'a spoken transcript for the source video', 'cap',
                strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """,
        (brand_id,),
    )
    trend_id = conn.execute("SELECT id FROM trends WHERE platform_video_id = 'wv1'").fetchone()[
        "id"
    ]
    return repo.create_content_item(conn, brand_id=brand_id, trend_id=trend_id)


def test_run_worker_once_takes_queued_item_all_the_way_to_pending_review(
    conn: sqlite3.Connection, brand: BrandConfig, queued_item: int
) -> None:
    claimed_id = run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="test-worker",
    )
    assert claimed_id == queued_item

    row = repo.get_content_item(conn, queued_item)
    assert row is not None
    assert row["status"] == str(ContentStatus.PENDING_REVIEW)
    assert row["lease_owner"] is None  # released after processing

    revisions = repo.list_revisions(conn, queued_item)
    assert len(revisions) == 1
    assert revisions[0]["revision_no"] == 0
    assert revisions[0]["video_path"] is not None


def test_run_worker_once_returns_none_when_nothing_to_claim(
    conn: sqlite3.Connection, brand: BrandConfig
) -> None:
    result = run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="test-worker",
    )
    assert result is None


def test_worker_lock_refuses_a_concurrent_holder(tmp_path: Path) -> None:
    """Both `worker run-once` (timer) and `generate now` (manual) take this
    lock, so a hand-triggered render cannot land on top of a scheduled one."""
    from trendstealer.commands.worker import WorkerBusyError, worker_lock

    with worker_lock(tmp_path):
        with pytest.raises(WorkerBusyError), worker_lock(tmp_path):
            pass  # pragma: no cover - the body never runs


def test_worker_lock_is_released_on_exit(tmp_path: Path) -> None:
    from trendstealer.commands.worker import worker_lock

    with worker_lock(tmp_path):
        pass
    with worker_lock(tmp_path):  # must not raise
        pass


def test_run_worker_once_can_target_a_specific_item(
    conn: sqlite3.Connection, brand: BrandConfig, queued_item: int
) -> None:
    """`generate now --item-id` -- processes the named item rather than the
    priority-ordered pick."""
    claimed_id = run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="test-worker",
        item_id=queued_item,
    )
    assert claimed_id == queued_item
    row = repo.get_content_item(conn, queued_item)
    assert row["status"] == str(ContentStatus.PENDING_REVIEW)


def test_run_worker_once_returns_none_for_an_unclaimable_target(
    conn: sqlite3.Connection, brand: BrandConfig, queued_item: int
) -> None:
    """A non-claimable id must not silently fall through to claiming
    whatever else happens to be queued."""
    result = run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="test-worker",
        item_id=99999,
    )
    assert result is None
    assert repo.get_content_item(conn, queued_item)["status"] == str(ContentStatus.QUEUED)


def test_revision_loop_uses_change_request_and_bumps_revision_no(
    conn: sqlite3.Connection, brand: BrandConfig, queued_item: int
) -> None:
    run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="w1",
    )
    row = repo.get_content_item(conn, queued_item)
    assert row is not None
    repo.transition(
        conn,
        queued_item,
        ContentStatus.PENDING_REVIEW,
        ContentStatus.CHANGES_REQUESTED,
        actor="dashboard",
        note="make the hook punchier",
        expected_version=row["version"],
    )

    run_worker_once(
        conn,
        brand=brand,
        llm_backend=FixtureBackend(),
        tts_backend=FakeTTSBackend(),
        worker_id="w1",
    )

    revisions = repo.list_revisions(conn, queued_item)
    assert len(revisions) == 2
    assert revisions[1]["revision_no"] == 1
    assert revisions[1]["change_request"] == "make the hook punchier"
    assert revisions[0]["on_screen_hook"] != revisions[1]["on_screen_hook"]

    final = repo.get_content_item(conn, queued_item)
    assert final is not None
    assert final["status"] == str(ContentStatus.PENDING_REVIEW)
