"""Exhaustive state-machine matrix test.

This is the test that protects the human review gate: it asserts
validate_transition() allows *exactly* the edges in TRANSITIONS and nothing
else, across every possible (from, to) pair. If someone tries to add a
shortcut edge (e.g. pending_review -> published, skipping approval),
this test fails.
"""

import itertools

import pytest

from trendstealer.states import (
    TERMINAL_STATES,
    TRANSITIONS,
    ContentStatus,
    InvalidTransitionError,
    validate_transition,
)

ALL_STATES = list(ContentStatus)


@pytest.mark.parametrize(
    "from_status,to_status", list(itertools.product(ALL_STATES, ALL_STATES))
)
def test_transition_matrix(from_status: ContentStatus, to_status: ContentStatus) -> None:
    allowed = to_status in TRANSITIONS.get(from_status, frozenset())
    if allowed:
        validate_transition(from_status, to_status)  # must not raise
    else:
        with pytest.raises(InvalidTransitionError):
            validate_transition(from_status, to_status)


def test_no_self_loops() -> None:
    for state, targets in TRANSITIONS.items():
        assert state not in targets, f"{state} has a self-loop"


def test_every_state_reachable_from_queued() -> None:
    reachable = {ContentStatus.QUEUED}
    frontier = [ContentStatus.QUEUED]
    while frontier:
        current = frontier.pop()
        for nxt in TRANSITIONS.get(current, frozenset()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    assert reachable == set(ALL_STATES), (
        f"unreachable from queued: {set(ALL_STATES) - reachable}"
    )


def test_terminal_states_have_no_outgoing_edges() -> None:
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()


def test_nothing_reaches_publishing_except_from_approved() -> None:
    sources = {s for s, targets in TRANSITIONS.items() if ContentStatus.PUBLISHING in targets}
    assert sources == {ContentStatus.APPROVED}


def test_nothing_reaches_published_except_from_publishing() -> None:
    sources = {s for s, targets in TRANSITIONS.items() if ContentStatus.PUBLISHED in targets}
    assert sources == {ContentStatus.PUBLISHING}


def test_pending_review_is_the_only_gate_into_approved() -> None:
    sources = {s for s, targets in TRANSITIONS.items() if ContentStatus.APPROVED in targets}
    assert sources == {ContentStatus.PENDING_REVIEW, ContentStatus.PUBLISH_FAILED}
