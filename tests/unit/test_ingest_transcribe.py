from pathlib import Path

import httpx
import pytest
import respx

from trendstealer.config import get_settings
from trendstealer.ingest import transcribe as transcribe_module


def _tmp_dir() -> Path:
    return get_settings().var_dir_abs / "tmp"


def test_var_tmp_is_emptied_even_when_transcription_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compliance guarantee: the downloaded file must never survive this
    call, even on failure -- it's analysis input only, not persisted media."""

    def _boom(path: Path, *, model_size: str = "base.en") -> str:
        raise RuntimeError("simulated whisper failure")

    monkeypatch.setattr(transcribe_module, "transcribe_text", _boom)

    tmp_dir = _tmp_dir()
    before = set(tmp_dir.glob("*")) if tmp_dir.exists() else set()

    with respx.mock:
        respx.get("https://example.com/video.mp4").mock(
            return_value=httpx.Response(200, content=b"fake media bytes")
        )
        with pytest.raises(RuntimeError):
            transcribe_module.download_and_transcribe("https://example.com/video.mp4")

    after = set(tmp_dir.glob("*")) if tmp_dir.exists() else set()
    assert after == before


@pytest.mark.slow
def test_real_download_and_transcribe(tmp_path: Path) -> None:
    """End-to-end: mocked HTTP download of a real Piper-generated wav ->
    real faster-whisper transcription -> var/tmp/ emptied afterwards.
    Requires network on first run to warm the whisper model cache. Run via
    `make test-slow`."""
    from trendstealer.tts.piper import PiperBackend

    voice_path = tmp_path / "source.wav"
    PiperBackend().synthesize("Hello world, this is a test clip.", voice_path)
    audio_bytes = voice_path.read_bytes()

    tmp_dir = _tmp_dir()
    before = set(tmp_dir.glob("*")) if tmp_dir.exists() else set()

    with respx.mock:
        respx.get("https://example.com/source.wav").mock(
            return_value=httpx.Response(200, content=audio_bytes)
        )
        transcript = transcribe_module.download_and_transcribe(
            "https://example.com/source.wav", model_size="tiny.en"
        )

    assert "hello" in transcript.lower()
    after = set(tmp_dir.glob("*")) if tmp_dir.exists() else set()
    assert after == before
