from __future__ import annotations

import subprocess
import wave
from pathlib import Path

from piper.voice import PiperVoice

from trendstealer.config import get_settings
from trendstealer.mediatools import ffmpeg_path, ffprobe_path
from trendstealer.tts.backend import TTSResult


class VoiceModelNotFoundError(FileNotFoundError):
    pass


class PiperBackend:
    """TTSBackend backed by local, offline Piper TTS.

    Piper's native output is mono at the voice model's training sample rate
    (22050 Hz for *-medium voices). ffmpeg resamples to the target rate and
    loudness-normalizes to target_lufs in the same pass, so callers always
    get a consistent, broadcast-safe wav regardless of voice model.
    """

    def __init__(
        self,
        *,
        voice: str = "en_US-lessac-medium",
        voices_dir: Path | None = None,
        target_lufs: float = -16.0,
        sample_rate_hz: int = 48000,
    ) -> None:
        self.voice_name = voice
        self.voices_dir = voices_dir or (get_settings().var_dir_abs / "piper-voices")
        self.target_lufs = target_lufs
        self.sample_rate_hz = sample_rate_hz
        self._voice: PiperVoice | None = None

    def _load_voice(self) -> PiperVoice:
        if self._voice is None:
            model_path = self.voices_dir / f"{self.voice_name}.onnx"
            if not model_path.exists():
                raise VoiceModelNotFoundError(
                    f"Piper voice model not found at {model_path}. Run: "
                    f"python -m piper.download_voices "
                    f"--download-dir {self.voices_dir} {self.voice_name}"
                )
            self._voice = PiperVoice.load(str(model_path))
        return self._voice

    def synthesize(self, text: str, output_path: Path) -> TTSResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path = output_path.with_suffix(".raw.wav")
        voice = self._load_voice()
        with wave.open(str(raw_path), "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)

        try:
            self._normalize(raw_path, output_path)
        finally:
            raw_path.unlink(missing_ok=True)

        duration = self._probe_duration(output_path)
        return TTSResult(
            path=output_path, duration_secs=duration, sample_rate_hz=self.sample_rate_hz
        )

    def _normalize(self, src: Path, dst: Path) -> None:
        subprocess.run(
            [
                ffmpeg_path(),
                "-y",
                "-i",
                str(src),
                "-af",
                f"loudnorm=I={self.target_lufs}:TP=-1.5:LRA=11",
                "-ar",
                str(self.sample_rate_hz),
                "-ac",
                "1",
                str(dst),
            ],
            check=True,
            capture_output=True,
        )

    def _probe_duration(self, path: Path) -> float:
        result = subprocess.run(
            [
                ffprobe_path(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
