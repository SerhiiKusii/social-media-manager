from pathlib import Path

import pytest

from trendstealer.tts.piper import PiperBackend, VoiceModelNotFoundError


def test_missing_voice_model_raises(tmp_path: Path) -> None:
    backend = PiperBackend(voices_dir=tmp_path, voice="does-not-exist")
    with pytest.raises(VoiceModelNotFoundError):
        backend.synthesize("hello", tmp_path / "out.wav")


@pytest.mark.slow
def test_real_synthesis_produces_normalized_wav(tmp_path: Path) -> None:
    """Requires the downloaded en_US-lessac-medium voice model and ffmpeg
    (scripts/install-tools.sh). Run via `make test-slow`."""
    backend = PiperBackend(sample_rate_hz=48000)
    result = backend.synthesize("This is a short test sentence.", tmp_path / "voice.wav")
    assert result.path.exists()
    assert result.sample_rate_hz == 48000
    assert result.duration_secs > 0
