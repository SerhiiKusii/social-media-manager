from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TTSResult:
    path: Path
    duration_secs: float
    sample_rate_hz: int


class TTSBackend(Protocol):
    def synthesize(self, text: str, output_path: Path) -> TTSResult: ...
