from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TypedDict

from trendstealer import repo
from trendstealer.config import AppConfig, BrandConfig
from trendstealer.ingest.backend import ApifyBackend
from trendstealer.ingest.dedupe import is_audio_in_cooldown, is_near_duplicate
from trendstealer.ingest.normalize import TrendCandidate, normalize_instagram, normalize_tiktok
from trendstealer.ingest.simhash import hamming_distance, simhash64
from trendstealer.ingest.transcribe import download_and_transcribe
from trendstealer.ingest.virality import evaluate, passes_numeric_thresholds
from trendstealer.logging import get_logger
from trendstealer.states import ContentStatus

logger = get_logger(__name__)

ACTORS: dict[str, str] = {
    "tiktok": "clockworks/tiktok-scraper",
    "instagram": "apify/instagram-scraper",
}


@dataclass
class IngestSummary:
    trends_seen: int = 0
    items_new: int = 0
    items_skipped: int = 0


def _run_input_for(platform: str, brand: BrandConfig) -> dict[str, object] | None:
    if platform == "tiktok":
        if not brand.sources.tiktok_seed_accounts:
            return None
        return {
            "profiles": brand.sources.tiktok_seed_accounts,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        }
    if platform == "instagram":
        if not brand.sources.instagram_seed_hashtags:
            return None
        return {
            "hashtags": brand.sources.instagram_seed_hashtags,
            "resultsType": "posts",
            "shouldDownloadVideos": False,
        }
    raise ValueError(f"unknown platform: {platform}")


def run_ingest(
    conn: sqlite3.Connection,
    *,
    brand: BrandConfig,
    brand_id: int,
    app_config: AppConfig,
    backend: ApifyBackend,
    dry_run: bool = False,
) -> IngestSummary:
    summary = IngestSummary()

    for platform in ("tiktok", "instagram"):
        run_input = _run_input_for(platform, brand)
        if run_input is None:
            continue

        actor_id = ACTORS[platform]
        scrape_run_id = repo.create_scrape_run(
            conn, brand_id=brand_id, platform=platform, actor_id=actor_id
        )
        try:
            result = backend.scrape(
                platform=platform,
                actor_id=actor_id,
                run_input=run_input,
                max_items=app_config.virality.max_items_per_run * 20,
                timeout_secs=app_config.ingest.scrape_actor_timeout_secs,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            repo.finish_scrape_run(
                conn, scrape_run_id, status="failed", items_scraped=0, error=str(exc)
            )
            raise

        repo.record_api_usage(
            conn,
            brand_id=brand_id,
            service="apify",
            operation=actor_id,
            units=result.compute_units,
            unit_kind="compute_units",
        )

        candidates = [
            normalize_tiktok(raw) if platform == "tiktok" else normalize_instagram(raw)
            for raw in result.items
        ]
        summary.trends_seen += len(candidates)
        _process_candidates(
            conn,
            candidates,
            brand=brand,
            brand_id=brand_id,
            app_config=app_config,
            scrape_run_id=scrape_run_id,
            dry_run=dry_run,
            summary=summary,
        )

        repo.finish_scrape_run(
            conn,
            scrape_run_id,
            status="succeeded",
            items_scraped=len(candidates),
            compute_units=result.compute_units,
        )

    return summary


def _process_candidates(
    conn: sqlite3.Connection,
    candidates: list[TrendCandidate],
    *,
    brand: BrandConfig,
    brand_id: int,
    app_config: AppConfig,
    scrape_run_id: int,
    dry_run: bool,
    summary: IngestSummary,
) -> None:
    survivors: list[tuple[TrendCandidate, float]] = []
    survivor_hashes: list[int] = []

    for candidate in candidates:
        if repo.get_trend_by_platform_id(conn, candidate.platform, candidate.platform_video_id):
            continue  # dedupe layer 1: already seen this exact video

        if not passes_numeric_thresholds(candidate, brand.virality):
            verdict = evaluate(candidate, brand.virality)
            repo.insert_trend(
                conn,
                brand_id=brand_id,
                scrape_run_id=scrape_run_id,
                skip_reason=verdict.skip_reason,
                virality_score=verdict.score,
                **_candidate_kwargs(candidate),
            )
            summary.items_skipped += 1
            continue

        if candidate.audio_id and is_audio_in_cooldown(
            conn,
            brand_id=brand_id,
            audio_id=candidate.audio_id,
            cooldown_days=app_config.dedupe.audio_cooldown_days,
        ):
            repo.insert_trend(
                conn,
                brand_id=brand_id,
                scrape_run_id=scrape_run_id,
                skip_reason="audio_cooldown",
                **_candidate_kwargs(candidate),
            )
            summary.items_skipped += 1
            continue

        transcript = candidate.transcript
        if not transcript and candidate.audio_url and not dry_run:
            try:
                transcript = download_and_transcribe(candidate.audio_url)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "transcription_failed", platform_video_id=candidate.platform_video_id
                )
                transcript = None

        # Near-duplicate check: against prior-run history (DB) *and* other
        # candidates already accepted from this same batch -- a naive
        # DB-only check would miss the same format reposted by two accounts
        # in a single scrape run, since survivors aren't persisted until
        # after ranking below.
        candidate_hash = simhash64(transcript) if transcript else None
        in_batch_duplicate = candidate_hash is not None and any(
            hamming_distance(candidate_hash, h) <= app_config.dedupe.simhash_hamming_threshold
            for h in survivor_hashes
        )
        if transcript and (
            in_batch_duplicate
            or is_near_duplicate(
                conn,
                brand_id=brand_id,
                transcript=transcript,
                window_days=app_config.dedupe.simhash_window_days,
                hamming_threshold=app_config.dedupe.simhash_hamming_threshold,
            )
        ):
            repo.insert_trend(
                conn,
                brand_id=brand_id,
                scrape_run_id=scrape_run_id,
                transcript=transcript,
                skip_reason="near_duplicate",
                **_candidate_kwargs_no_transcript(candidate),
            )
            summary.items_skipped += 1
            continue

        final = TrendCandidate(**{**candidate.__dict__, "transcript": transcript})
        verdict = evaluate(final, brand.virality)
        if verdict.passed:
            survivors.append((final, verdict.score))
            if candidate_hash is not None:
                survivor_hashes.append(candidate_hash)
        else:
            simhash_value = simhash64(transcript) if transcript else None
            repo.insert_trend(
                conn,
                brand_id=brand_id,
                scrape_run_id=scrape_run_id,
                transcript=transcript,
                transcript_simhash=simhash_value,
                skip_reason=verdict.skip_reason,
                virality_score=verdict.score,
                **_candidate_kwargs_no_transcript(candidate),
            )

    survivors.sort(key=lambda pair: pair[1], reverse=True)
    top_n = survivors[: app_config.virality.max_items_per_run]
    skipped_overflow = survivors[app_config.virality.max_items_per_run :]

    for candidate, score in top_n:
        simhash_value = simhash64(candidate.transcript) if candidate.transcript else None
        trend_id = repo.insert_trend(
            conn,
            brand_id=brand_id,
            scrape_run_id=scrape_run_id,
            transcript=candidate.transcript,
            transcript_simhash=simhash_value,
            virality_score=score,
            **_candidate_kwargs_no_transcript(candidate),
        )
        item_id = repo.try_create_content_item(
            conn, brand_id=brand_id, trend_id=trend_id, initial_status=ContentStatus.QUEUED
        )
        if item_id is not None:
            summary.items_new += 1

    for candidate, score in skipped_overflow:
        simhash_value = simhash64(candidate.transcript) if candidate.transcript else None
        repo.insert_trend(
            conn,
            brand_id=brand_id,
            scrape_run_id=scrape_run_id,
            transcript=candidate.transcript,
            transcript_simhash=simhash_value,
            virality_score=score,
            skip_reason="ranked_below_top_n",
            **_candidate_kwargs_no_transcript(candidate),
        )
        summary.items_skipped += 1


class _CandidateKwargsNoTranscript(TypedDict):
    platform: str
    platform_video_id: str
    source_account: str | None
    source_url: str | None
    caption: str | None
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    source_follower_count: int | None
    duration_secs: float | None
    posted_at: str | None
    audio_id: str | None


class _CandidateKwargs(_CandidateKwargsNoTranscript):
    transcript: str | None


def _candidate_kwargs_no_transcript(candidate: TrendCandidate) -> _CandidateKwargsNoTranscript:
    """For call sites that pass `transcript=` explicitly (it may differ from
    candidate.transcript, e.g. after post-scrape transcription) -- omitting
    the key here, rather than conditionally including it, is what lets mypy
    see there's no duplicate keyword at those call sites."""
    return {
        "platform": candidate.platform,
        "platform_video_id": candidate.platform_video_id,
        "source_account": candidate.source_account,
        "source_url": candidate.source_url,
        "caption": candidate.caption,
        "views": candidate.views,
        "likes": candidate.likes,
        "comments": candidate.comments,
        "shares": candidate.shares,
        "source_follower_count": candidate.source_follower_count,
        "duration_secs": candidate.duration_secs,
        "posted_at": candidate.posted_at,
        "audio_id": candidate.audio_id,
    }


def _candidate_kwargs(candidate: TrendCandidate) -> _CandidateKwargs:
    return {**_candidate_kwargs_no_transcript(candidate), "transcript": candidate.transcript}
