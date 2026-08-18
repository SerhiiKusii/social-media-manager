"""M9's payoff: which hook patterns have worked for *this* account,
formatted for injection into the synthesize prompt. The join that
produces the raw numbers lives in repo.get_hook_pattern_performance();
this module just turns that into prompt text."""

from __future__ import annotations

from trendstealer.repo import HookPatternStat


def format_hook_performance(stats: list[HookPatternStat], *, top_n: int = 5) -> str | None:
    if not stats:
        return None
    ranked = sorted(stats, key=lambda s: s["avg_views"], reverse=True)[:top_n]
    lines = [
        f"- {s['hook_pattern']}: average {s['avg_views']:.0f} views over {s['sample_size']} post(s)"
        for s in ranked
    ]
    return "Hook patterns that have performed well for this account recently:\n" + "\n".join(lines)
