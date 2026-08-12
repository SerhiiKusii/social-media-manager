from pathlib import Path

from trendstealer.captions import WordTiming, load_captions, save_captions


def test_save_and_load_captions_round_trip(tmp_path: Path) -> None:
    timings = [
        WordTiming(word="hello", start=0.0, end=0.4),
        WordTiming(word="world", start=0.4, end=0.9),
    ]
    path = tmp_path / "captions.json"
    save_captions(timings, path)
    loaded = load_captions(path)
    assert loaded == timings
