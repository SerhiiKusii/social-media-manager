"""Compliance boundary: scraped source audio/video is analysis input only.

download_and_transcribe() writes to var/tmp/, transcribes, and deletes the
file in `finally` -- even on error. The `trends` table has no media-path
column, so a scraped file can never persist past this function call
(client-answers-1.md sec 4.2).
"""

from __future__ import annotations

import uuid

import httpx

from trendstealer.captions import transcribe_text
from trendstealer.config import get_settings


def download_and_transcribe(url: str, *, model_size: str = "base.en", timeout: float = 60.0) -> str:
    tmp_dir = get_settings().var_dir_abs / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}.media"
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        return transcribe_text(tmp_path, model_size=model_size)
    finally:
        tmp_path.unlink(missing_ok=True)
