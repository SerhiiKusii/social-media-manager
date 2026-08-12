"""Locates the ffmpeg/ffprobe binaries used by tts/piper.py and render/remotion.py.

Prefers whatever is on PATH; falls back to the portable static build
scripts/install-tools.sh downloads into .tools/ffmpeg/ (no sudo required).
"""

from __future__ import annotations

import shutil

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
