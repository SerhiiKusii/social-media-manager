from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScriptPlan(BaseModel):
    """Structured output of the hook-transfer synthesis step.

    extra="forbid" so ScriptPlan.model_json_schema() emits
    additionalProperties: false, required by the Anthropic structured
    outputs strict schema mode.
    """

    model_config = ConfigDict(extra="forbid")

    on_screen_hook: str = Field(
        ...,
        description="Text overlay for the first 1-3 seconds; mirrors the source retention hook",
    )
    spoken_script: str = Field(
        ..., description="Full voiceover script, written for the brand's product"
    )
    caption: str = Field(..., description="Social caption / CTA to publish alongside the video")
    hashtags: list[str] = Field(default_factory=list)
    hook_pattern: str = Field(
        ...,
        description="Short label for the retention structure used, e.g. 'problem-agitate-solve'",
    )
    estimated_duration_secs: float = Field(..., gt=0)
