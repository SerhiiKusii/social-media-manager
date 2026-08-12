"""The content-item state machine.

This module is the *only* place transitions are defined. Every write to
content_items.status must go through repo.transition(), which performs a
conditional `UPDATE ... WHERE id=? AND status=?` guarded by TRANSITIONS
below and rejects anything not listed here. This is what makes the human
review gate structural rather than a convention someone can bypass with a
crafted request — see repo.transition() and review/app.py's action→status
whitelist, which is the other half of the same guard.

    queued -> synthesizing -> script_ready -> rendering -> pending_review
                                                                |
                       +----------------+---------------------+------------------+
                       v                v                                        v
                   approved         rejected                            changes_requested
                       |                |                                        |
                       v                v                          (revision_no+1, cap 3)
                  publishing        archived                                     |
                    |    |                                                       v
                    v    v                                                 synthesizing
              published  publish_failed --> approved (retry) | rejected
"""

from __future__ import annotations

from enum import StrEnum


class ContentStatus(StrEnum):
    QUEUED = "queued"
    SYNTHESIZING = "synthesizing"
    SCRIPT_READY = "script_ready"
    RENDERING = "rendering"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    ARCHIVED = "archived"


# Terminal states: no outgoing transitions.
TERMINAL_STATES: frozenset[ContentStatus] = frozenset(
    {ContentStatus.PUBLISHED, ContentStatus.ARCHIVED}
)

# States the review dashboard is allowed to write to. Anything not in this
# set cannot be reached from a dashboard POST, no matter what `action` value
# is submitted — this is the fix for the status-injection bug in the
# original architecture doc (UPDATE ... SET status = ? from request.form).
DASHBOARD_WRITABLE_STATES: frozenset[ContentStatus] = frozenset(
    {ContentStatus.APPROVED, ContentStatus.REJECTED, ContentStatus.CHANGES_REQUESTED}
)

# States the worker is allowed to claim a lease on and act from.
# Priority order matters: revision requests jump the queue ahead of fresh
# items, and script_ready lets a crashed worker resume without re-synthesizing.
# SYNTHESIZING/RENDERING are included last, gated by lease expiry only (a
# worker holds an unexpired lease on those while genuinely in progress) --
# they let a worker that crashed mid-stage be retried by the next tick
# instead of leaving the item stuck with no route back to a stable state.
WORKER_CLAIMABLE_STATES: tuple[ContentStatus, ...] = (
    ContentStatus.CHANGES_REQUESTED,
    ContentStatus.QUEUED,
    ContentStatus.SCRIPT_READY,
    ContentStatus.SYNTHESIZING,
    ContentStatus.RENDERING,
)

MAX_REVISIONS = 3

TRANSITIONS: dict[ContentStatus, frozenset[ContentStatus]] = {
    ContentStatus.QUEUED: frozenset({ContentStatus.SYNTHESIZING}),
    ContentStatus.SYNTHESIZING: frozenset({ContentStatus.SCRIPT_READY}),
    ContentStatus.SCRIPT_READY: frozenset({ContentStatus.RENDERING}),
    ContentStatus.RENDERING: frozenset({ContentStatus.PENDING_REVIEW}),
    ContentStatus.PENDING_REVIEW: frozenset(
        {ContentStatus.APPROVED, ContentStatus.REJECTED, ContentStatus.CHANGES_REQUESTED}
    ),
    ContentStatus.APPROVED: frozenset({ContentStatus.PUBLISHING}),
    ContentStatus.REJECTED: frozenset({ContentStatus.ARCHIVED}),
    ContentStatus.CHANGES_REQUESTED: frozenset({ContentStatus.SYNTHESIZING}),
    ContentStatus.PUBLISHING: frozenset({ContentStatus.PUBLISHED, ContentStatus.PUBLISH_FAILED}),
    ContentStatus.PUBLISHED: frozenset(),
    ContentStatus.PUBLISH_FAILED: frozenset({ContentStatus.APPROVED, ContentStatus.REJECTED}),
    ContentStatus.ARCHIVED: frozenset(),
}


class InvalidTransitionError(ValueError):
    """Attempted a transition not present in TRANSITIONS."""

    def __init__(self, from_status: ContentStatus, to_status: ContentStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"cannot transition {from_status!s} -> {to_status!s}")


class StaleStateError(RuntimeError):
    """The row's status no longer matched the expected `from` status when the
    guarded UPDATE ran — someone else transitioned it first."""

    def __init__(self, item_id: int, expected_from: ContentStatus) -> None:
        self.item_id = item_id
        self.expected_from = expected_from
        super().__init__(
            f"content_item {item_id} was not in status {expected_from!s} "
            "when the transition was attempted (raced or already moved on)"
        )


def validate_transition(from_status: ContentStatus, to_status: ContentStatus) -> None:
    """Raise InvalidTransitionError if to_status is not reachable from from_status.

    Pure and DB-free so it can guard callers before they ever touch a
    connection, and so the exhaustive N x N matrix test can run without a DB.
    """
    if to_status not in TRANSITIONS.get(from_status, frozenset()):
        raise InvalidTransitionError(from_status, to_status)
