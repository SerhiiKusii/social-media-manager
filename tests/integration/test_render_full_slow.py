import json
import subprocess

import pytest

from trendstealer.captions import transcribe_word_timings
from trendstealer.config import get_settings
from trendstealer.intelligence.fixture_backend import FixtureBackend
from trendstealer.intelligence.synthesize import synthesize
from trendstealer.mediatools import ffprobe_path
from trendstealer.render.props import build_render_props
from trendstealer.render.remotion import render_video
from trendstealer.tts.piper import PiperBackend


@pytest.mark.slow
def test_full_pipeline_produces_a_real_mp4_with_audio() -> None:
    """End-to-end: fixture LLM -> real Piper voiceover -> real faster-whisper
    captions -> real Remotion render. Requires the toolchain from
    scripts/install-tools.sh plus the downloaded Piper voice model. Run via
    `make test-slow`, never in CI."""
    item_id = 999990
    work_dir = get_settings().var_dir_abs / "work" / str(item_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    synth = synthesize(
        FixtureBackend(),
        brand_brief="Acme sells productivity widgets.",
        transcript="wait for it... this hack saves me an hour every single day",
    )
    plan = synth.script_plan

    tts = PiperBackend()
    voiceover_path = work_dir / "voice.wav"
    tts.synthesize(plan.spoken_script, voiceover_path)

    captions = transcribe_word_timings(voiceover_path, model_size="tiny.en")

    props = build_render_props(
        item_id=item_id,
        revision_no=0,
        on_screen_hook=plan.on_screen_hook,
        captions=captions,
        voiceover_path=voiceover_path,
        duration_secs=captions[-1].end if captions else plan.estimated_duration_secs,
        brand_name="Acme",
        palette=["#111111", "#F5F5F5", "#FF5A1F"],
    )

    result = render_video(props)
    assert result.path.exists()
    assert result.render_ms > 0

    probe = subprocess.run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            str(result.path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    video_streams = [s for s in streams if s["codec_type"] == "video"]
    audio_streams = [s for s in streams if s["codec_type"] == "audio"]
    assert video_streams and video_streams[0]["width"] == 1080
    assert video_streams[0]["height"] == 1920
    assert audio_streams, "render is missing an audio track"
