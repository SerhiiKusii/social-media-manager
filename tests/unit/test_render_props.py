import json
from pathlib import Path

import pytest

from trendstealer.captions import WordTiming
from trendstealer.config import get_settings
from trendstealer.render.props import (
    UnclearedAssetPathError,
    build_render_props,
    stage_and_serialize,
)


def test_voiceover_outside_boundary_is_rejected(tmp_path: Path) -> None:
    rogue_path = tmp_path / "scraped_audio.wav"
    rogue_path.write_bytes(b"fake wav")
    with pytest.raises(UnclearedAssetPathError):
        build_render_props(
            item_id=999999,
            revision_no=0,
            on_screen_hook="hook",
            captions=[],
            voiceover_path=rogue_path,
            duration_secs=10.0,
            brand_name="Acme",
            palette=["#111"],
        )


def test_voiceover_inside_item_work_dir_is_accepted() -> None:
    item_id = 999998
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    voiceover_path = work_dir / "voice.wav"
    voiceover_path.write_bytes(b"fake wav")

    props = build_render_props(
        item_id=item_id,
        revision_no=0,
        on_screen_hook="hook",
        captions=[WordTiming(word="hi", start=0.0, end=0.3)],
        voiceover_path=voiceover_path,
        duration_secs=5.0,
        brand_name="Acme",
        palette=["#111", "#fff"],
    )
    assert props.voiceover_path == voiceover_path.resolve()


def test_stage_and_serialize_copies_files_and_matches_golden_shape(tmp_path: Path) -> None:
    item_id = 999997
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    voiceover_path = work_dir / "voice.wav"
    voiceover_path.write_bytes(b"fake wav bytes")

    props = build_render_props(
        item_id=item_id,
        revision_no=0,
        on_screen_hook="Wait, THIS is why it works",
        captions=[WordTiming(word="Here's", start=0.0, end=0.4)],
        voiceover_path=voiceover_path,
        duration_secs=28.0,
        brand_name="Acme",
        palette=["#111111", "#F5F5F5", "#FF5A1F"],
    )

    remotion_props = stage_and_serialize(props)

    assert set(remotion_props) == {
        "onScreenHook",
        "captions",
        "voiceoverStaticPath",
        "durationSecs",
        "brandName",
        "palette",
        "brollStaticPaths",
    }
    assert remotion_props["voiceoverStaticPath"] == f"generated/{item_id}-0/voice.wav"

    golden = json.loads(
        (Path(__file__).parents[1] / "golden" / "video_props.golden.json").read_text()
    )
    assert set(remotion_props) == set(golden)
