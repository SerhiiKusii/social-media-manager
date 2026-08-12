import json
from pathlib import Path

import pytest

from trendstealer.intelligence.backend import SynthesizeRequest
from trendstealer.intelligence.fixture_backend import FixtureBackend, fixture_key
from trendstealer.intelligence.prompts import render_prompt
from trendstealer.intelligence.schemas import ScriptPlan
from trendstealer.intelligence.synthesize import get_backend, synthesize

TRANSCRIPT = "wait for it... this hack saves me an hour every single day"


def test_synthesize_returns_valid_script_plan() -> None:
    backend = FixtureBackend()
    result = synthesize(
        backend, brand_brief="Acme sells productivity widgets.", transcript=TRANSCRIPT
    )
    assert isinstance(result.script_plan, ScriptPlan)
    assert result.script_plan.spoken_script
    assert result.script_plan.estimated_duration_secs > 0
    assert result.input_tokens > 0
    assert result.output_tokens > 0


def test_synthesize_is_deterministic_for_same_inputs() -> None:
    backend = FixtureBackend()
    r1 = synthesize(backend, brand_brief="Acme", transcript=TRANSCRIPT)
    r2 = synthesize(backend, brand_brief="Acme", transcript=TRANSCRIPT)
    assert r1.script_plan == r2.script_plan


def test_change_request_produces_a_different_hook() -> None:
    backend = FixtureBackend()
    original = synthesize(backend, brand_brief="Acme", transcript=TRANSCRIPT)
    revised = synthesize(
        backend, brand_brief="Acme", transcript=TRANSCRIPT, change_request="make the hook punchier"
    )
    assert original.script_plan.on_screen_hook != revised.script_plan.on_screen_hook
    assert original.script_plan.hook_pattern != revised.script_plan.hook_pattern


def test_different_transcripts_produce_different_fixture_keys() -> None:
    req_a = SynthesizeRequest(brand_brief="Acme", transcript="a", prompt_version="hook_transfer_v1")
    req_b = SynthesizeRequest(brand_brief="Acme", transcript="b", prompt_version="hook_transfer_v1")
    assert fixture_key(req_a) != fixture_key(req_b)


def test_recorded_fixture_is_replayed_verbatim(tmp_path: Path) -> None:
    request = SynthesizeRequest(
        brand_brief="Acme", transcript=TRANSCRIPT, prompt_version="hook_transfer_v1"
    )
    key = fixture_key(request)
    recorded = {
        "script_plan": {
            "on_screen_hook": "recorded hook",
            "spoken_script": "recorded script",
            "caption": "recorded caption",
            "hashtags": ["#recorded"],
            "hook_pattern": "curiosity-gap",
            "estimated_duration_secs": 30.0,
        },
        "input_tokens": 111,
        "output_tokens": 222,
        "cache_read_tokens": 50,
    }
    (tmp_path / f"{key}.json").write_text(json.dumps(recorded))

    backend = FixtureBackend(fixtures_dir=tmp_path)
    result = backend.synthesize(request)

    assert result.script_plan.on_screen_hook == "recorded hook"
    assert result.input_tokens == 111
    assert result.cache_read_tokens == 50


def test_get_backend_fixture() -> None:
    backend = get_backend("fixture")
    assert isinstance(backend, FixtureBackend)


def test_get_backend_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_backend("not-a-real-backend")


def test_render_prompt_includes_transcript_and_change_request() -> None:
    request = SynthesizeRequest(
        brand_brief="Acme",
        transcript=TRANSCRIPT,
        prompt_version="hook_transfer_v1",
        change_request="cut the intro",
    )
    rendered = render_prompt(request)
    assert TRANSCRIPT in rendered
    assert "cut the intro" in rendered


def test_render_prompt_omits_change_request_section_when_none() -> None:
    request = SynthesizeRequest(
        brand_brief="Acme", transcript=TRANSCRIPT, prompt_version="hook_transfer_v1"
    )
    rendered = render_prompt(request)
    assert "requested this change" not in rendered
