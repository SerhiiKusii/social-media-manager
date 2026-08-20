from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trendstealer.intelligence.schemas import ScriptPlan


@dataclass(frozen=True)
class SynthesizeRequest:
    brand_brief: str
    transcript: str
    prompt_version: str
    caption: str | None = None
    change_request: str | None = None  # None for revision 0, else the human's note
    hook_performance_note: str | None = None  # M9 feedback loop, see intelligence/feedback.py
    # Target spoken length. The voiceover drives the composition duration,
    # so this is effectively the length of the finished Reel minus the
    # intro -- the single biggest lever on whether it holds attention.
    min_script_secs: int = 15
    max_script_secs: int = 20


@dataclass(frozen=True)
class SynthesizeResult:
    script_plan: ScriptPlan
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class LLMBackend(Protocol):
    def synthesize(self, request: SynthesizeRequest) -> SynthesizeResult: ...
