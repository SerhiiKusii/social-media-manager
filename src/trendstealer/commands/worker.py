"""The revision loop.

Each worker invocation claims exactly one item (repo.claim_lease) and
drives it as far as it can go in one call: queued/changes_requested ->
synthesize -> script_ready -> render -> pending_review. The fallthrough
below is deliberately linear and re-entrant on current status, which is
what makes crash recovery work: if a prior run died mid-SYNTHESIZING or
mid-RENDERING, the next claim (once its lease expires) picks up from
wherever item["status"] actually is instead of needing separate resume
logic. Only the two intermediate transitions (-> SYNTHESIZING, -> RENDERING)
happen before the corresponding work; a crash before either transition
lands leaves the item in its original claimable state so it's retried
untouched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from trendstealer import repo
from trendstealer.captions import save_captions, transcribe_word_timings
from trendstealer.config import REPO_ROOT, BrandConfig, get_settings
from trendstealer.intelligence.backend import LLMBackend
from trendstealer.intelligence.feedback import format_hook_performance
from trendstealer.intelligence.synthesize import synthesize
from trendstealer.logging import get_logger
from trendstealer.render.props import IntroProps, build_render_props
from trendstealer.render.remotion import render_video
from trendstealer.states import ContentStatus
from trendstealer.tts.backend import TTSBackend

logger = get_logger(__name__)

DEFAULT_PROMPT_VERSION = "hook_transfer_v1"


def run_worker_once(
    conn: sqlite3.Connection,
    *,
    brand: BrandConfig,
    llm_backend: LLMBackend,
    tts_backend: TTSBackend,
    worker_id: str,
    lease_ttl_seconds: int = 600,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> int | None:
    """Claim and fully process one item. Returns its id, or None if there
    was nothing to claim."""
    item = repo.claim_lease(conn, owner=worker_id, ttl_seconds=lease_ttl_seconds)
    if item is None:
        return None

    item_id = item["id"]
    logger.info("worker_claimed_item", item_id=item_id, status=item["status"])
    try:
        _process_item(
            conn,
            item,
            brand=brand,
            llm_backend=llm_backend,
            tts_backend=tts_backend,
            prompt_version=prompt_version,
        )
    finally:
        repo.release_lease(conn, item_id)
    return item_id  # type: ignore[no-any-return]


def _process_item(
    conn: sqlite3.Connection,
    item: sqlite3.Row,
    *,
    brand: BrandConfig,
    llm_backend: LLMBackend,
    tts_backend: TTSBackend,
    prompt_version: str,
) -> None:
    item_id = item["id"]
    status = ContentStatus(item["status"])

    if status in (ContentStatus.QUEUED, ContentStatus.CHANGES_REQUESTED):
        repo.transition(conn, item_id, status, ContentStatus.SYNTHESIZING, actor="worker")
        status = ContentStatus.SYNTHESIZING

    if status == ContentStatus.SYNTHESIZING:
        _run_synthesis(
            conn, item_id, brand=brand, backend=llm_backend, prompt_version=prompt_version
        )
        repo.transition(
            conn, item_id, ContentStatus.SYNTHESIZING, ContentStatus.SCRIPT_READY, actor="worker"
        )
        status = ContentStatus.SCRIPT_READY

    if status == ContentStatus.SCRIPT_READY:
        repo.transition(
            conn, item_id, ContentStatus.SCRIPT_READY, ContentStatus.RENDERING, actor="worker"
        )
        status = ContentStatus.RENDERING

    if status == ContentStatus.RENDERING:
        refreshed_item = repo.get_content_item(conn, item_id)
        assert refreshed_item is not None
        _run_render(conn, refreshed_item, brand=brand, tts_backend=tts_backend)
        repo.transition(
            conn, item_id, ContentStatus.RENDERING, ContentStatus.PENDING_REVIEW, actor="worker"
        )


def _run_synthesis(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    brand: BrandConfig,
    backend: LLMBackend,
    prompt_version: str,
) -> None:
    item = repo.get_content_item(conn, item_id)
    assert item is not None
    trend = repo.get_trend(conn, item["trend_id"])
    assert trend is not None

    latest_no = repo.get_latest_revision_no(conn, item_id)
    revision_no = 0 if latest_no is None else latest_no + 1

    change_request = None
    if latest_no is not None:
        # The note on the most recent pending_review -> changes_requested
        # event is this revision's instruction. History-based, not
        # current-status-based, so it's correct even if this is a retry
        # after a crash mid-synthesis (item["status"] would already say
        # SYNTHESIZING by then, not changes_requested).
        events = repo.list_status_events(conn, item_id)
        change_request = next(
            (e["note"] for e in reversed(events) if e["to_status"] == "changes_requested"), None
        )

    hook_stats = repo.get_hook_pattern_performance(conn, brand_id=item["brand_id"])
    hook_performance_note = format_hook_performance(hook_stats)

    result = synthesize(
        backend,
        brand_brief=brand.brand.product_brief,
        transcript=trend["transcript"] or trend["caption"] or "",
        caption=trend["caption"],
        change_request=change_request,
        hook_performance_note=hook_performance_note,
        prompt_version=prompt_version,
    )
    plan = result.script_plan

    revision_id = repo.create_revision(
        conn,
        content_item_id=item_id,
        revision_no=revision_no,
        prompt_version=prompt_version,
        change_request=change_request,
        script_plan_json=plan.model_dump_json(),
        on_screen_hook=plan.on_screen_hook,
        spoken_script=plan.spoken_script,
        llm_input_tokens=result.input_tokens,
        llm_output_tokens=result.output_tokens,
        llm_cache_read_tokens=result.cache_read_tokens,
    )
    repo.set_current_revision(conn, item_id, revision_id)
    repo.record_api_usage(
        conn,
        brand_id=item["brand_id"],
        service="anthropic",
        operation=prompt_version,
        units=result.input_tokens + result.output_tokens,
        unit_kind="tokens",
    )


def _run_render(
    conn: sqlite3.Connection, item: sqlite3.Row, *, brand: BrandConfig, tts_backend: TTSBackend
) -> None:
    item_id = item["id"]
    revision = repo.get_revision(conn, item["current_revision_id"])
    assert revision is not None
    revision_no = revision["revision_no"]

    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    voiceover_path = work_dir / f"voice_r{revision_no}.wav"
    tts_result = tts_backend.synthesize(revision["spoken_script"], voiceover_path)

    captions = transcribe_word_timings(voiceover_path)
    captions_path = work_dir / f"captions_r{revision_no}.json"
    save_captions(captions, captions_path)

    broll_paths, broll_asset_ids = _select_broll(conn, brand=brand)
    intro, intro_asset_ids = _build_intro(
        conn,
        brand=brand,
        item_id=item_id,
        revision_no=revision_no,
        work_dir=work_dir,
        tts_backend=tts_backend,
    )

    render_props = build_render_props(
        item_id=item_id,
        revision_no=revision_no,
        on_screen_hook=revision["on_screen_hook"],
        captions=captions,
        voiceover_path=voiceover_path,
        duration_secs=tts_result.duration_secs,
        brand_name=brand.brand.name,
        palette=brand.brand.palette,
        broll_paths=broll_paths,
        intro=intro,
    )
    render_result = render_video(render_props)

    # Provenance before anything can be published: item_assets is what
    # preflight() reads to refuse an uncleared asset.
    if broll_asset_ids:
        repo.record_item_assets(
            conn, revision_id=revision["id"], asset_ids=broll_asset_ids, role="broll"
        )
    if intro_asset_ids:
        repo.record_item_assets(
            conn, revision_id=revision["id"], asset_ids=intro_asset_ids, role="intro"
        )
    for asset_id in [*broll_asset_ids, *intro_asset_ids]:
        repo.touch_asset_used(conn, asset_id)

    repo.update_revision_render(
        conn,
        revision["id"],
        voiceover_path=str(voiceover_path),
        captions_path=str(captions_path),
        video_path=str(render_result.path),
        render_ms=render_result.render_ms,
    )


def _select_broll(
    conn: sqlite3.Connection, *, brand: BrandConfig
) -> tuple[list[Path], list[int]]:
    """Least-recently-used cleared clips matching the brand's b-roll tag.

    Only cleared assets are considered, so an unlicensed clip can never be
    picked up here by accident -- preflight() is the backstop, not the
    first line of defence.
    """
    if brand.broll.tag is None:
        return [], []
    rows = repo.list_assets(
        conn, kind="video", tag=brand.broll.tag, limit=max(1, brand.broll.count)
    )
    paths = [REPO_ROOT / row["path"] for row in rows]
    return paths, [int(row["id"]) for row in rows]


def _build_intro(
    conn: sqlite3.Connection,
    *,
    brand: BrandConfig,
    item_id: int,
    revision_no: int,
    work_dir: Path,
    tts_backend: TTSBackend,
) -> tuple[IntroProps | None, list[int]]:
    config = brand.intro
    if not config.enabled or config.image_tag is None or not config.titles:
        return None, []

    rows = repo.list_assets(conn, kind="image", tag=config.image_tag, limit=1)
    if not rows:
        logger.warning("intro_skipped_no_image_asset", image_tag=config.image_tag)
        return None, []
    image_row = rows[0]

    # Deterministic per (item, revision): a re-render of the same revision
    # reproduces the same title, while a revision request rotates to the
    # next one -- so "make it different" actually changes something.
    title = config.titles[(item_id + revision_no) % len(config.titles)]

    spoken = title if config.voiceover_from_title else config.voiceover_text
    intro_voice_path: Path | None = None
    if spoken:
        intro_voice_path = work_dir / f"intro_voice_r{revision_no}.wav"
        tts_backend.synthesize(spoken, intro_voice_path)

    intro = IntroProps(
        image_path=REPO_ROOT / image_row["path"],
        title=title,
        duration_secs=config.duration_secs,
        voiceover_path=intro_voice_path,
    )
    return intro, [int(image_row["id"])]
