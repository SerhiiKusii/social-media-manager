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


@dataclass(frozen=True)
class SynthesizeResult:
    script_plan: ScriptPlan
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class LLMBackend(Protocol):
    def synthesize(self, request: SynthesizeRequest) -> SynthesizeResult: ...
