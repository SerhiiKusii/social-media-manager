"""Word-level caption timing.

Runs on the *generated* voiceover, not the scraped source video, which is
what makes captions frame-accurate to the actual TTS audio going into the
render.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from faster_whisper import WhisperModel

_model_cache: dict[str, WhisperModel] = {}


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float


def _get_model(model_size: str) -> WhisperModel:
    if model_size not in _model_cache:
        _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model_cache[model_size]


def transcribe_word_timings(audio_path: Path, *, model_size: str = "base.en") -> list[WordTiming]:
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)
    model = _get_model(model_size)
    segments, _info = model.transcribe(str(audio_path), word_timestamps=True)
    timings: list[WordTiming] = []
    for segment in segments:
        for word in segment.words or []:
            timings.append(WordTiming(word=word.word.strip(), start=word.start, end=word.end))
    return timings


def transcribe_text(audio_path: Path, *, model_size: str = "base.en") -> str:
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)
    model = _get_model(model_size)
    segments, _info = model.transcribe(str(audio_path), word_timestamps=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


def save_captions(timings: list[WordTiming], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(t) for t in timings], indent=2))


def load_captions(path: Path) -> list[WordTiming]:
    data = json.loads(path.read_text())
    return [WordTiming(**entry) for entry in data]
