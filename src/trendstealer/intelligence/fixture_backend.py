from __future__ import annotations

import hashlib
import json
from pathlib import Path

from trendstealer.intelligence.backend import SynthesizeRequest, SynthesizeResult
from trendstealer.intelligence.schemas import ScriptPlan

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm"


def fixture_key(request: SynthesizeRequest) -> str:
    payload = f"{request.prompt_version}|{request.transcript}|{request.change_request or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()


class FixtureBackend:
    """Zero-network LLMBackend.

    Replays a recorded fixture (tests/fixtures/llm/<sha>.json, refreshed via
    `RECORD=1 pytest -k llm_live` against the real API, never in CI) if one
    exists for this exact (prompt_version, transcript, change_request).
    Otherwise deterministically synthesizes a plausible ScriptPlan from the
    inputs, so the whole pipeline is runnable offline for any scraped trend
    — not only ones someone has recorded a fixture for.
    """

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or FIXTURES_DIR

    def synthesize(self, request: SynthesizeRequest) -> SynthesizeResult:
        key = fixture_key(request)
        recorded = self.fixtures_dir / f"{key}.json"
        if recorded.exists():
            data = json.loads(recorded.read_text())
            return SynthesizeResult(
                script_plan=ScriptPlan.model_validate(data["script_plan"]),
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                cache_read_tokens=data.get("cache_read_tokens", 0),
                cache_creation_tokens=data.get("cache_creation_tokens", 0),
            )
        return self._synthetic(request, key)

    def _synthetic(self, request: SynthesizeRequest, key: str) -> SynthesizeResult:
        seed = key[:8]
        revised = request.change_request is not None
        note = f" (revised: {request.change_request})" if revised else ""
        plan = ScriptPlan(
            on_screen_hook=f"Wait, THIS is why it works{note}"[:80],
            spoken_script=(
                f"Here's the thing nobody tells you about this.{note} "
                "Our product solves it in seconds, not hours. "
                "Try it today and see the difference for yourself."
            ),
            caption=f"You won't believe this trick. Link in bio. #{seed}",
            hashtags=["#trending", f"#{seed}"],
            hook_pattern="before-after" if revised else "pattern-interrupt",
            estimated_duration_secs=28.0,
        )
        input_tokens = len(request.brand_brief.split()) + len(request.transcript.split())
        output_tokens = len(plan.spoken_script.split()) + len(plan.caption.split())
        return SynthesizeResult(
            script_plan=plan, input_tokens=input_tokens, output_tokens=output_tokens
        )
