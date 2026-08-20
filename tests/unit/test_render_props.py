import json
from pathlib import Path

import pytest

from trendstealer.captions import WordTiming
from trendstealer.config import get_settings
from trendstealer.render.props import (
    ASSETS_DIR,
    IntroProps,
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
        "brollDurationsSecs",
        "intro",
    }
    assert remotion_props["voiceoverStaticPath"] == f"generated/{item_id}-0/voice.wav"
    assert remotion_props["intro"] is None

    golden = json.loads(
        (Path(__file__).parents[1] / "golden" / "video_props.golden.json").read_text()
    )
    assert set(remotion_props) == set(golden)


def test_stage_and_serialize_stages_intro_media_and_matches_the_intro_golden(
    tmp_path: Path,
) -> None:
    item_id = 999996
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "voice.wav").write_bytes(b"fake wav bytes")
    (work_dir / "intro_voice.wav").write_bytes(b"fake intro wav")
    (work_dir / "carlos.png").write_bytes(b"fake png")

    props = build_render_props(
        item_id=item_id,
        revision_no=0,
        on_screen_hook="Carlos approves",
        captions=[WordTiming(word="Here's", start=0.0, end=0.4)],
        voiceover_path=work_dir / "voice.wav",
        duration_secs=28.0,
        brand_name="Acme",
        palette=["#111111", "#F5F5F5", "#FF5A1F"],
        intro=IntroProps(
            image_path=work_dir / "carlos.png",
            title="Carlos approves",
            duration_secs=5.0,
            voiceover_path=work_dir / "intro_voice.wav",
        ),
    )

    remotion_props = stage_and_serialize(props)
    intro = remotion_props["intro"]
    assert intro is not None
    assert intro["imageStaticPath"] == f"generated/{item_id}-0/intro.png"
    assert intro["voiceoverStaticPath"] == f"generated/{item_id}-0/intro_voice.wav"
    assert intro["durationSecs"] == 5.0

    golden = json.loads(
        (Path(__file__).parents[1] / "golden" / "video_props_intro.golden.json").read_text()
    )
    assert set(remotion_props) == set(golden)
    assert set(intro) == set(golden["intro"])


def test_intro_media_outside_the_boundary_is_refused() -> None:
    """An intro must not be a loophole around the compliance boundary."""
    item_id = 999995
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "voice.wav").write_bytes(b"fake wav bytes")

    with pytest.raises(UnclearedAssetPathError):
        build_render_props(
            item_id=item_id,
            revision_no=0,
            on_screen_hook="hook",
            captions=[],
            voiceover_path=work_dir / "voice.wav",
            duration_secs=10.0,
            brand_name="Acme",
            palette=[],
            intro=IntroProps(
                image_path=Path("/etc/passwd"),
                title="nope",
                duration_secs=5.0,
            ),
        )


def test_broll_durations_are_probed_and_emitted_alongside_the_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renderer tiles b-roll to fill the body, which it can only do if
    it knows how long each clip is -- clips run 6-10s against a 20-40s body.
    Before this, footage played once and the picture froze for the rest."""
    import trendstealer.render.props as props_module

    item_id = 999994
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "voice.wav").write_bytes(b"fake wav bytes")

    broll = ASSETS_DIR / "video" / "test_probe_clip.mp4"
    broll.parent.mkdir(parents=True, exist_ok=True)
    broll.write_bytes(b"fake mp4 bytes")

    monkeypatch.setattr(props_module, "probe_duration_secs", lambda _p: 7.25)
    try:
        props = build_render_props(
            item_id=item_id,
            revision_no=0,
            on_screen_hook="hook",
            captions=[],
            voiceover_path=work_dir / "voice.wav",
            duration_secs=30.0,
            brand_name="Acme",
            palette=[],
            broll_paths=[broll],
        )
        payload = stage_and_serialize(props)
    finally:
        broll.unlink(missing_ok=True)

    assert payload["brollDurationsSecs"] == [7.25]
    assert len(payload["brollDurationsSecs"]) == len(payload["brollStaticPaths"])


def test_unprobeable_broll_duration_serializes_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 is the renderer's "unknown, don't tile this" signal -- it must not
    become null or be dropped, which would break the parallel-array
    contract with brollStaticPaths."""
    import trendstealer.render.props as props_module

    item_id = 999993
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "voice.wav").write_bytes(b"fake wav bytes")

    broll = ASSETS_DIR / "video" / "test_unprobeable.mp4"
    broll.parent.mkdir(parents=True, exist_ok=True)
    broll.write_bytes(b"not really a video")

    monkeypatch.setattr(props_module, "probe_duration_secs", lambda _p: None)
    try:
        props = build_render_props(
            item_id=item_id,
            revision_no=0,
            on_screen_hook="hook",
            captions=[],
            voiceover_path=work_dir / "voice.wav",
            duration_secs=30.0,
            brand_name="Acme",
            palette=[],
            broll_paths=[broll],
        )
        payload = stage_and_serialize(props)
    finally:
        broll.unlink(missing_ok=True)

    assert payload["brollDurationsSecs"] == [0.0]
