import sqlite3

import pytest

from trendstealer import repo
from trendstealer.commands.ingest import _run_input_for, run_ingest
from trendstealer.config import (
    AppConfig,
    BrandConfig,
    BrandIdentity,
    BrandSources,
    PublishConfig,
    ViralityConfig,
)
from trendstealer.ingest.dedupe import is_audio_in_cooldown, is_near_duplicate
from trendstealer.ingest.fixture_backend import ApifyFixtureBackend
from trendstealer.ingest.normalize import normalize_instagram, normalize_tiktok
from trendstealer.ingest.simhash import hamming_distance, simhash64
from trendstealer.ingest.virality import TrendCandidate, evaluate, passes_numeric_thresholds

# --- normalize ---------------------------------------------------------


def test_normalize_tiktok_maps_core_fields() -> None:
    raw = {
        "id": "abc123",
        "text": "caption text",
        "transcript": "spoken words",
        "playCount": 1000,
        "diggCount": 50,
        "commentCount": 5,
        "shareCount": 2,
        "authorMeta": {"name": "someone", "fans": 500},
        "musicMeta": {"musicId": "song-1"},
        "videoMeta": {"duration": 15},
        "webVideoUrl": "https://tiktok.com/x",
        "videoUrl": "https://cdn/x.mp4",
    }
    candidate = normalize_tiktok(raw)
    assert candidate.platform == "tiktok"
    assert candidate.platform_video_id == "abc123"
    assert candidate.views == 1000
    assert candidate.source_follower_count == 500
    assert candidate.duration_secs == 15
    assert candidate.audio_id == "song-1"


def test_normalize_instagram_maps_core_fields() -> None:
    raw = {
        "id": "xyz789",
        "caption": "ig caption",
        "videoPlayCount": 2000,
        "likesCount": 80,
        "commentsCount": 10,
        "videoDuration": 30,
        "ownerUsername": "igaccount",
        "url": "https://instagram.com/p/xyz789",
        "videoUrl": "https://cdn/y.mp4",
    }
    candidate = normalize_instagram(raw)
    assert candidate.platform == "instagram"
    assert candidate.platform_video_id == "xyz789"
    assert candidate.views == 2000
    assert candidate.source_account == "igaccount"


# --- simhash -------------------------------------------------------------


def test_simhash_identical_text_has_zero_distance() -> None:
    text = "this is a test sentence about productivity hacks"
    assert hamming_distance(simhash64(text), simhash64(text)) == 0


def test_simhash_similar_text_has_small_distance() -> None:
    # Default threshold (DedupeConfig.simhash_hamming_threshold) is 12,
    # calibrated against exactly this kind of single-word edit -- see the
    # comment on that field for the empirical numbers.
    a = "wait for it this simple morning routine trick changed everything for me try it today"
    b = "wait for it this simple morning routine trick changed everything for me try it now"
    assert hamming_distance(simhash64(a), simhash64(b)) <= 12


def test_simhash_different_text_has_large_distance() -> None:
    a = "wait for it this simple morning routine trick changed everything for me try it today"
    b = "an entirely different topic about kitchen gadgets that save time cooking dinner fast"
    assert hamming_distance(simhash64(a), simhash64(b)) > 12


# --- virality (table-driven boundary tests) -------------------------------

BASE_CONFIG = ViralityConfig(
    min_views=100_000,
    max_age_hours=96,
    min_views_per_follower=3.0,
    min_engagement_rate=0.03,
    min_duration_secs=8,
    max_duration_secs=90,
    max_items_per_run=3,
)


def _candidate(**overrides: object) -> TrendCandidate:
    from datetime import UTC, datetime, timedelta

    defaults: dict[str, object] = dict(
        platform="tiktok",
        platform_video_id="v1",
        source_account="acct",
        source_url="https://x",
        caption="cap",
        transcript="a reasonably long transcript with enough words to count",
        views=200_000,
        likes=10_000,
        comments=1_000,
        shares=500,
        source_follower_count=20_000,
        duration_secs=30.0,
        posted_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        audio_id="song",
        audio_url="https://cdn/x.mp4",
    )
    defaults.update(overrides)
    return TrendCandidate(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides,expected_passed",
    [
        ({}, True),
        ({"views": 99_999}, False),
        ({"views": 100_000}, True),
        ({"source_follower_count": 1_000_000}, False),  # vpf below threshold
        ({"source_follower_count": None}, True),  # unavailable (Instagram) -- not penalized
        ({"likes": 0, "comments": 0, "shares": 0}, False),  # engagement below threshold
        ({"duration_secs": 5.0}, False),  # too short
        ({"duration_secs": 91.0}, False),  # too long
        ({"duration_secs": 8.0}, True),  # boundary inclusive
        ({"duration_secs": 90.0}, True),  # boundary inclusive
        ({"transcript": ""}, False),
        ({"transcript": None}, False),
    ],
)
def test_virality_boundaries(overrides: dict[str, object], expected_passed: bool) -> None:
    verdict = evaluate(_candidate(**overrides), BASE_CONFIG)
    assert verdict.passed is expected_passed


def test_passes_numeric_thresholds_ignores_missing_transcript() -> None:
    candidate = _candidate(transcript=None)
    assert passes_numeric_thresholds(candidate, BASE_CONFIG) is True
    assert evaluate(candidate, BASE_CONFIG).passed is False


# --- dedupe ----------------------------------------------------------------


@pytest.fixture
def brand_id(conn: sqlite3.Connection) -> int:
    return repo.upsert_brand(conn, "acme", "Acme")


def test_is_near_duplicate_true_for_similar_transcript_in_window(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    text = "wait for it this simple morning routine trick changed everything for me try it today"
    repo.insert_trend(
        conn,
        brand_id=brand_id,
        scrape_run_id=None,
        platform="tiktok",
        platform_video_id="seen-1",
        transcript=text,
        transcript_simhash=simhash64(text),
    )
    similar = "wait for it this simple morning routine trick changed everything for me try it now"
    assert is_near_duplicate(
        conn, brand_id=brand_id, transcript=similar, window_days=30, hamming_threshold=12
    )


def test_is_near_duplicate_false_for_unrelated_transcript(
    conn: sqlite3.Connection, brand_id: int
) -> None:
    text = "wait for it this simple morning routine trick changed everything for me try it today"
    repo.insert_trend(
        conn,
        brand_id=brand_id,
        scrape_run_id=None,
        platform="tiktok",
        platform_video_id="seen-2",
        transcript=text,
        transcript_simhash=simhash64(text),
    )
    unrelated = (
        "an entirely different topic about kitchen gadgets that save time cooking dinner fast"
    )
    assert not is_near_duplicate(
        conn, brand_id=brand_id, transcript=unrelated, window_days=30, hamming_threshold=12
    )


def test_audio_cooldown_true_within_window(conn: sqlite3.Connection, brand_id: int) -> None:
    repo.insert_trend(
        conn,
        brand_id=brand_id,
        scrape_run_id=None,
        platform="tiktok",
        platform_video_id="seen-3",
        audio_id="hot-sound",
    )
    assert is_audio_in_cooldown(conn, brand_id=brand_id, audio_id="hot-sound", cooldown_days=14)


def test_audio_cooldown_false_for_unseen_audio(conn: sqlite3.Connection, brand_id: int) -> None:
    assert not is_audio_in_cooldown(
        conn, brand_id=brand_id, audio_id="never-seen", cooldown_days=14
    )


# --- _run_input_for -- the shape actually sent to each Apify actor ---------


def _brand_with_sources(**source_kwargs: object) -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="brief"),
        sources=BrandSources(**source_kwargs),
        virality=ViralityConfig(),
        publish=PublishConfig(),
    )


def test_instagram_input_uses_directurls_not_a_hashtags_field() -> None:
    """apify/instagram-scraper's real input schema has no "hashtags"
    property -- only directUrls or a search+searchType query. Passing
    "hashtags" is silently ignored by the actor (extra properties don't
    error), so every live run would process zero URLs and report "no
    trends found", indistinguishable from a quiet niche."""
    brand = _brand_with_sources(instagram_seed_hashtags=["football", "#footballskills"])
    run_input = _run_input_for("instagram", brand)
    assert run_input is not None
    assert "hashtags" not in run_input
    assert run_input["directUrls"] == [
        "https://www.instagram.com/explore/tags/football/",
        "https://www.instagram.com/explore/tags/footballskills/",
    ]


def test_instagram_input_targets_reels_not_mixed_posts() -> None:
    """resultsType="posts" returns photos and carousels too, and those
    always fail the virality gate (duration_secs is required, photos have
    none) -- so "posts" silently wasted every non-video result."""
    brand = _brand_with_sources(instagram_seed_hashtags=["football"])
    run_input = _run_input_for("instagram", brand)
    assert run_input is not None
    assert run_input["resultsType"] == "reels"


def test_instagram_input_is_none_without_any_configured_source() -> None:
    assert _run_input_for("instagram", _brand_with_sources()) is None


def test_instagram_input_builds_profile_urls_from_seed_accounts() -> None:
    """Accounts are what produce volume: measured against the live actor, a
    profile reels scrape returns ~20 videos while a hashtag reels scrape
    returns exactly 1 regardless of resultsLimit. A hashtag-only config
    yields one candidate per tag per run -- the same top reel every time,
    which dedupe then rejects, so generation silently produces nothing."""
    brand = _brand_with_sources(instagram_seed_accounts=["brfootball", "@433"])
    run_input = _run_input_for("instagram", brand)
    assert run_input is not None
    assert run_input["directUrls"] == [
        "https://www.instagram.com/brfootball/",
        "https://www.instagram.com/433/",
    ]


def test_instagram_input_combines_accounts_and_hashtags() -> None:
    brand = _brand_with_sources(
        instagram_seed_accounts=["brfootball"], instagram_seed_hashtags=["football"]
    )
    run_input = _run_input_for("instagram", brand)
    assert run_input is not None
    assert run_input["directUrls"] == [
        "https://www.instagram.com/brfootball/",
        "https://www.instagram.com/explore/tags/football/",
    ]


def test_instagram_input_passes_a_results_limit() -> None:
    """Unset, the actor defaults low; the run is also capped platform-side
    by max_items, so this is the per-URL half of the same budget."""
    brand = _brand_with_sources(instagram_seed_accounts=["brfootball"])
    run_input = _run_input_for("instagram", brand, results_limit=60)
    assert run_input is not None
    assert run_input["resultsLimit"] == 60


def test_tiktok_input_passes_seed_profiles() -> None:
    brand = _brand_with_sources(tiktok_seed_accounts=["someaccount"])
    run_input = _run_input_for("tiktok", brand)
    assert run_input is not None
    assert run_input["profiles"] == ["someaccount"]


def test_tiktok_input_is_none_without_configured_accounts() -> None:
    assert _run_input_for("tiktok", _brand_with_sources()) is None


# --- run_ingest end to end (fixture backend, zero network) -----------------


@pytest.fixture
def relaxed_brand() -> BrandConfig:
    return BrandConfig(
        brand=BrandIdentity(id="acme", name="Acme", product_brief="test brief"),
        sources=BrandSources(tiktok_seed_accounts=["someaccount"]),
        virality=ViralityConfig(
            min_views=100_000,
            max_age_hours=10**7,  # fixture timestamps are fixed; avoid time-based flakiness
            min_views_per_follower=3.0,
            min_engagement_rate=0.03,
            min_duration_secs=8,
            max_duration_secs=90,
            max_items_per_run=3,
        ),
        publish=PublishConfig(),
    )


def test_run_ingest_queues_survivors_and_skips_the_rest(
    conn: sqlite3.Connection, relaxed_brand: BrandConfig
) -> None:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    summary = run_ingest(
        conn,
        brand=relaxed_brand,
        brand_id=brand_id,
        app_config=AppConfig(),
        backend=ApifyFixtureBackend(),
        dry_run=True,
    )
    assert summary.trends_seen == 4
    assert summary.items_new == 2  # tt-survivor-1, tt-survivor-2
    assert summary.items_skipped == 2  # near-dup + low-views

    counts = repo.count_content_items_by_status(conn)
    assert counts.get("queued") == 2


def test_run_ingest_is_idempotent_on_replay(
    conn: sqlite3.Connection, relaxed_brand: BrandConfig
) -> None:
    brand_id = repo.upsert_brand(conn, "acme", "Acme")
    app_config = AppConfig()
    backend = ApifyFixtureBackend()

    run_ingest(
        conn,
        brand=relaxed_brand,
        brand_id=brand_id,
        app_config=app_config,
        backend=backend,
        dry_run=True,
    )
    second = run_ingest(
        conn,
        brand=relaxed_brand,
        brand_id=brand_id,
        app_config=app_config,
        backend=backend,
        dry_run=True,
    )

    assert second.trends_seen == 4
    assert second.items_new == 0  # natural-key dedupe: all already seen
