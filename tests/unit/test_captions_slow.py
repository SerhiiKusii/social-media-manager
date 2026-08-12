from pathlib import Path

import pytest

from trendstealer.captions import transcribe_word_timings
from trendstealer.tts.piper import PiperBackend


@pytest.mark.slow
def test_transcribe_generated_voiceover_matches_words(tmp_path: Path) -> None:
    """End-to-end: real Piper synthesis -> real faster-whisper word timing.
    Requires network on first run (downloads the tiny.en whisper model to
    the HF cache) plus the Piper voice model and ffmpeg. Run via
    `make test-slow`, never in CI."""
    tts = PiperBackend()
    voice_path = tmp_path / "voice.wav"
    tts.synthesize("Hello world, this is a test.", voice_path)

    timings = transcribe_word_timings(voice_path, model_size="tiny.en")
    words = [t.word.lower().strip(",.") for t in timings]
    assert "hello" in words
    assert "world" in words
    assert all(t.end > t.start for t in timings)
    assert all(t.end <= timings[-1].end + 0.01 for t in timings)
