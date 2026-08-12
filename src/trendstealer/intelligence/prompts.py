from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from trendstealer.intelligence.backend import SynthesizeRequest

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_prompt_template(prompt_version: str) -> str:
    path = PROMPTS_DIR / f"{prompt_version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt template at {path}")
    return path.read_text()


def render_prompt(request: SynthesizeRequest) -> str:
    template = load_prompt_template(request.prompt_version)
    change_request_section = (
        f"The human reviewer requested this change to a previous draft: {request.change_request}"
        if request.change_request
        else ""
    )
    return template.format(
        transcript=request.transcript,
        caption=request.caption or "",
        change_request_section=change_request_section,
    )
