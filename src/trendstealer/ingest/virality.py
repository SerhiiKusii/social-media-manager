from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from trendstealer.config import ViralityConfig
from trendstealer.ingest.normalize import TrendCandidate


@dataclass(frozen=True)
class ViralityVerdict:
    passed: bool
    score: float
    skip_reason: str | None


def _age_hours(posted_at: str | None) -> float | None:
    if not posted_at:
        return None
    try:
        posted = datetime.fromisoformat(posted_at)
    except ValueError:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    return (datetime.now(UTC) - posted).total_seconds() / 3600


def _numeric_reasons(candidate: TrendCandidate, config: ViralityConfig) -> list[str]:
    reasons: list[str] = []

    if candidate.views is None or candidate.views < config.min_views:
        reasons.append("views_below_threshold")

    age_hours = _age_hours(candidate.posted_at)
    if age_hours is None or age_hours > config.max_age_hours:
        reasons.append("too_old")

    # Only scored when the source actually supplies follower counts (TikTok
    # does; Instagram's hashtag/reels scrape does not, in the same call).
    # Treating a structurally-missing count as a fail would hard-block every
    # Instagram candidate regardless of real virality -- the other four
    # numeric checks (views, age, engagement, duration) still gate it.
    if candidate.source_follower_count:
        vpf = (candidate.views or 0) / candidate.source_follower_count
        if vpf < config.min_views_per_follower:
            reasons.append("views_per_follower_below_threshold")

    engagement = _engagement_rate(candidate)
    if engagement is None or engagement < config.min_engagement_rate:
        reasons.append("engagement_below_threshold")

    if candidate.duration_secs is None or not (
        config.min_duration_secs <= candidate.duration_secs <= config.max_duration_secs
    ):
        reasons.append("duration_out_of_range")

    return reasons


def _engagement_rate(candidate: TrendCandidate) -> float | None:
    if not candidate.views:
        return None
    likes = candidate.likes or 0
    comments = candidate.comments or 0
    shares = candidate.shares or 0
    return (likes + comments + shares) / candidate.views


def passes_numeric_thresholds(candidate: TrendCandidate, config: ViralityConfig) -> bool:
    """Cheap pre-check (no transcript needed) so we don't pay to transcribe
    a candidate that was never going to pass the views/age/engagement gate."""
    return not _numeric_reasons(candidate, config)


def evaluate(candidate: TrendCandidate, config: ViralityConfig) -> ViralityVerdict:
    reasons = _numeric_reasons(candidate, config)
    if not candidate.transcript:
        reasons.append("empty_transcript")

    score = (candidate.views / config.min_views) if candidate.views else 0.0
    return ViralityVerdict(
        passed=not reasons,
        score=score,
        skip_reason=", ".join(reasons) if reasons else None,
    )
