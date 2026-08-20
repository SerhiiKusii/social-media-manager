"""Locates the ffmpeg/ffprobe binaries used by tts/piper.py and render/remotion.py.

Prefers whatever is on PATH; falls back to the portable static build
scripts/install-tools.sh downloads into .tools/ffmpeg/ (no sudo required).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from trendstealer.config import REPO_ROOT


def _resolve(binary: str) -> str:
    found = shutil.which(binary)
    if found:
        return found
    local = REPO_ROOT / ".tools" / "ffmpeg" / binary
    if local.exists():
        return str(local)
    raise FileNotFoundError(
        f"{binary} not found on PATH or at {local}. Run `make tools` (scripts/install-tools.sh)."
    )


def ffmpeg_path() -> str:
    return _resolve("ffmpeg")


def ffprobe_path() -> str:
    return _resolve("ffprobe")


def probe_duration_secs(path: Path) -> float | None:
    """Container duration in seconds, or None if ffprobe can't determine it.

    The renderer needs this to tile b-roll: a clip is typically 6-10s while
    a body runs 20-40s, so without knowing the clip length there is no way
    to know how many repeats cover the segment.
    """
    try:
        result = subprocess.run(
            [
                ffprobe_path(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    raw = result.stdout.strip()
    try:
        duration = float(raw)
    except ValueError:
        return None
    return duration if duration > 0 else None
