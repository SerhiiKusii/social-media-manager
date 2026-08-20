from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    # Deliberately a bare float, not Field(ge=...) / Field(gt=...): both
    # exclusiveMinimum and inclusive minimum are rejected by Anthropic's
    # structured-outputs strict schema mode ("property 'exclusiveMinimum'/
    # 'minimum' is not supported") -- confirmed against the live API, not
    # just docs. model_json_schema() is what gets sent as the response
    # schema, so any Field() numeric bound here reproduces the 400. The
    # positivity check instead runs client-side, after the API response is
    # parsed, via the validator below -- which never touches the schema.
    estimated_duration_secs: float

    @field_validator("estimated_duration_secs")
    @classmethod
    def _duration_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("estimated_duration_secs must be positive")
        return value
