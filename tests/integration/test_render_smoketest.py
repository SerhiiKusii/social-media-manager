import json
import os
import subprocess
from pathlib import Path

from trendstealer.config import REPO_ROOT
from trendstealer.mediatools import ffprobe_path
from trendstealer.render.props import VIDEO_RENDERER_DIR


def _render_env() -> dict[str, str]:
    env = os.environ.copy()
    extra_bins = [REPO_ROOT / ".tools" / "node" / "bin", REPO_ROOT / ".tools" / "ffmpeg"]
    prefix = os.pathsep.join(str(p) for p in extra_bins if p.exists())
    if prefix:
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
    return env


def test_smoketest_composition_renders_a_real_1080x1920_mp4(tmp_path: Path) -> None:
    """Fast render (60 frames, no external assets) used as the CI regression
    guard for the render pipeline, per the plan's verification table."""
    output_path = tmp_path / "smoke.mp4"
    result = subprocess.run(
        ["npx", "remotion", "render", "SmokeTest", str(output_path)],
        cwd=VIDEO_RENDERER_DIR,
        env=_render_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output_path.exists()

    probe = subprocess.run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["width"] == 1080
    assert stream["height"] == 1920
