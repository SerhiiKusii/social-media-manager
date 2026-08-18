from __future__ import annotations

from trendstealer.intelligence.backend import LLMBackend, SynthesizeRequest, SynthesizeResult

DEFAULT_PROMPT_VERSION = "hook_transfer_v1"


def get_backend(
    llm_backend: str, *, model: str = "claude-opus-5", max_tokens: int = 16000
) -> LLMBackend:
    if llm_backend == "fixture":
        from trendstealer.intelligence.fixture_backend import FixtureBackend

        return FixtureBackend()
    if llm_backend == "anthropic":
        from trendstealer.intelligence.anthropic_backend import AnthropicBackend

        return AnthropicBackend(model=model, max_tokens=max_tokens)
    raise ValueError(f"unknown llm backend: {llm_backend!r}")


def synthesize(
    backend: LLMBackend,
    *,
    brand_brief: str,
    transcript: str,
    caption: str | None = None,
    change_request: str | None = None,
    hook_performance_note: str | None = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> SynthesizeResult:
    request = SynthesizeRequest(
        brand_brief=brand_brief,
        transcript=transcript,
        caption=caption,
        prompt_version=prompt_version,
        change_request=change_request,
        hook_performance_note=hook_performance_note,
    )
    return backend.synthesize(request)
