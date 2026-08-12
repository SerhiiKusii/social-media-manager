"""The Python half of the Python<->Remotion JSON contract.

video-renderer/src/types.ts holds the zod half; tests/golden/*.json is
parsed against both in CI as the drift guard between them.

build_render_props() is also the compliance boundary from client-answers
sec 4.2: every media path must resolve under assets/ (licensed/original) or
var/work/<item_id>/ (this item's own generated voiceover). A scraped source
video's path is never passed in here, so it is structurally unable to reach
the renderer through this function.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trendstealer.captions import WordTiming
from trendstealer.config import REPO_ROOT, get_settings

ASSETS_DIR = REPO_ROOT / "assets"
VIDEO_RENDERER_DIR = REPO_ROOT / "video-renderer"


class UnclearedAssetPathError(ValueError):
    pass


def _assert_within_boundary(path: Path, item_work_dir: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ASSETS_DIR.resolve()) or resolved.is_relative_to(
        item_work_dir.resolve()
    ):
        return resolved
    raise UnclearedAssetPathError(
        f"{path} does not resolve under assets/ or {item_work_dir} — refusing to render it"
    )


@dataclass(frozen=True)
class RenderProps:
    item_id: int
    revision_no: int
    on_screen_hook: str
    captions: list[WordTiming]
    voiceover_path: Path
    duration_secs: float
    brand_name: str
    palette: list[str]
    broll_paths: list[Path] = field(default_factory=list)


def build_render_props(
    *,
    item_id: int,
    revision_no: int,
    on_screen_hook: str,
    captions: list[WordTiming],
    voiceover_path: Path,
    duration_secs: float,
    brand_name: str,
    palette: list[str],
    broll_paths: list[Path] | None = None,
) -> RenderProps:
    item_work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    voiceover_path = _assert_within_boundary(voiceover_path, item_work_dir)
    resolved_broll = [_assert_within_boundary(p, item_work_dir) for p in (broll_paths or [])]
    return RenderProps(
        item_id=item_id,
        revision_no=revision_no,
        on_screen_hook=on_screen_hook,
        captions=captions,
        voiceover_path=voiceover_path,
        duration_secs=duration_secs,
        brand_name=brand_name,
        palette=palette,
        broll_paths=resolved_broll,
    )


def _stage(src: Path, staged_dir: Path, filename: str) -> str:
    """Copy an asset into video-renderer/public/ so Remotion can address it
    via staticFile(); returns the path staticFile() expects."""
    dst = staged_dir / filename
    shutil.copyfile(src, dst)
    return f"generated/{staged_dir.name}/{filename}"


def stage_and_serialize(props: RenderProps) -> dict[str, Any]:
    staged_dir = (
        VIDEO_RENDERER_DIR / "public" / "generated" / f"{props.item_id}-{props.revision_no}"
    )
    staged_dir.mkdir(parents=True, exist_ok=True)

    voiceover_static = _stage(props.voiceover_path, staged_dir, "voice.wav")
    broll_static = [
        _stage(p, staged_dir, f"broll_{i}{p.suffix}") for i, p in enumerate(props.broll_paths)
    ]

    return {
        "onScreenHook": props.on_screen_hook,
        "captions": [{"word": c.word, "start": c.start, "end": c.end} for c in props.captions],
        "voiceoverStaticPath": voiceover_static,
        "durationSecs": props.duration_secs,
        "brandName": props.brand_name,
        "palette": props.palette,
        "brollStaticPaths": broll_static,
    }
