from __future__ import annotations

import json
from typing import Any

import anthropic

from trendstealer.intelligence.backend import SynthesizeRequest, SynthesizeResult
from trendstealer.intelligence.prompts import render_prompt
from trendstealer.intelligence.schemas import ScriptPlan


class RefusalError(RuntimeError):
    """The model (and its server-side fallback, if any) declined to synthesize a script."""


class AnthropicBackend:
    """LLMBackend backed by the real Anthropic API.

    Three gotchas this class exists to get right (see docs/M2 notes):
    thinking is on by default on claude-opus-5 and max_tokens caps
    thinking+output together, so max_tokens is set well above the ~800-token
    script; refusals return HTTP 200 with stop_reason == "refusal" and are
    checked before content is touched; and the brand brief is cached as a
    stable system-prompt prefix separate from the per-request transcript.
    """

    def __init__(
        self,
        *,
        model: str = "claude-opus-5",
        max_tokens: int = 16000,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic()

    def synthesize(self, request: SynthesizeRequest) -> SynthesizeResult:
        user_prompt = render_prompt(request)
        response: Any = self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[
                {
                    "type": "text",
                    "text": (
                        "You are a short-form video creative strategist working "
                        f"for this brand.\n\nBrand brief:\n{request.brand_brief}"
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            output_config={
                "format": {"type": "json_schema", "schema": ScriptPlan.model_json_schema()}
            },
        )

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise RefusalError(f"synthesis refused (category={category})")

        text = next(block.text for block in response.content if block.type == "text")
        script_plan = ScriptPlan.model_validate(json.loads(text))

        usage = response.usage
        return SynthesizeResult(
            script_plan=script_plan,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
