from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from trendstealer.config import REPO_ROOT, get_settings
from trendstealer.render.props import VIDEO_RENDERER_DIR, RenderProps, stage_and_serialize


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderResult:
    path: Path
    render_ms: int


def _render_env() -> dict[str, str]:
    env = os.environ.copy()
    extra_bins = [REPO_ROOT / ".tools" / "node" / "bin", REPO_ROOT / ".tools" / "ffmpeg"]
    prefix = os.pathsep.join(str(p) for p in extra_bins if p.exists())
    if prefix:
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
    return env


def render_video(props: RenderProps, *, composition_id: str = "MainVideo") -> RenderResult:
    output_path = (
        get_settings().var_dir_abs / "work" / str(props.item_id) / f"out_r{props.revision_no}.mp4"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    remotion_props = stage_and_serialize(props)
    props_path = output_path.with_suffix(".props.json")
    props_path.write_text(json.dumps(remotion_props))

    start = time.monotonic()
    result = subprocess.run(
        [
            "npx",
            "remotion",
            "render",
            composition_id,
            str(output_path),
            "--props",
            str(props_path),
        ],
        cwd=VIDEO_RENDERER_DIR,
        env=_render_env(),
        capture_output=True,
        text=True,
    )
    render_ms = int((time.monotonic() - start) * 1000)

    if result.returncode != 0:
        raise RenderError(f"remotion render failed:\n{result.stdout}\n{result.stderr}")

    return RenderResult(path=output_path, render_ms=render_ms)
