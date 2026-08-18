from pathlib import Path

import pytest

from trendstealer.publish.disclosure import (
    DisclosureError,
    ensure_caption_has_disclosure,
    preflight,
    try_embed_metadata,
    validate_disclosure,
)


def test_ensure_caption_has_disclosure_appends_marker_when_missing() -> None:
    result = ensure_caption_has_disclosure("check out this product")
    assert "#AIGenerated" in result


def test_ensure_caption_has_disclosure_is_idempotent() -> None:
    once = ensure_caption_has_disclosure("caption")
    twice = ensure_caption_has_disclosure(once)
    assert once == twice


def test_validate_disclosure_raises_when_marker_missing() -> None:
    with pytest.raises(DisclosureError):
        validate_disclosure("a caption with no marker")


def test_validate_disclosure_passes_when_marker_present() -> None:
    validate_disclosure("a caption #AIGenerated")  # must not raise


def test_try_embed_metadata_returns_false_when_exiftool_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.publish.disclosure as disclosure_module

    monkeypatch.setattr(disclosure_module.shutil, "which", lambda _name: None)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    assert try_embed_metadata(video_path) is False


def test_preflight_raises_when_caption_missing_disclosure(tmp_path: Path) -> None:
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    with pytest.raises(DisclosureError):
        preflight(video_path=video_path, caption="no marker here")


def test_preflight_passes_with_disclosed_caption_even_without_exiftool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trendstealer.publish.disclosure as disclosure_module

    monkeypatch.setattr(disclosure_module.shutil, "which", lambda _name: None)
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    preflight(video_path=video_path, caption="buy now #AIGenerated")  # must not raise
