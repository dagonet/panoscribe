"""A video OpenCV opens but cannot decode (AV1 without a decoder) raises a clear error (#189).

Without this, ``sample_frames`` yielded zero frames and OCR returned nothing, silently.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from panoscribe.config import PanoScribeConfig
from panoscribe.errors import PanoScribeError
from panoscribe.ocr.frame_sampler import ensure_frames_decodable, sample_frames
from panoscribe.pipeline import process_single_video

VIDEO_CAPTURE = "panoscribe.ocr.frame_sampler.cv2.VideoCapture"
_AV01 = int.from_bytes(b"av01", "little")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [k for k in os.environ if k.startswith("PANO_")]:
        monkeypatch.delenv(name, raising=False)


def _undecodable_capture(fourcc: int = _AV01) -> MagicMock:
    """Opens fine, reports frames and a codec, but every ``read()`` fails (AV1 case)."""
    cap = MagicMock(name="VideoCapture")
    cap.isOpened.return_value = True

    def _get(prop: int) -> float:
        # cv2.CAP_PROP_FPS == 5, CAP_PROP_FRAME_COUNT == 7, CAP_PROP_FOURCC == 6.
        return {5: 30.0, 6: float(fourcc), 7: 90.0}.get(prop, 0.0)

    cap.get.side_effect = _get
    cap.read.return_value = (False, None)
    return cap


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    return video


# -- helper + sampler guard (mocked cv2) ------------------------------------


def test_helper_raises_naming_file_codec_and_way_out(tmp_path: Path) -> None:
    video = _video(tmp_path)
    cap = _undecodable_capture()

    with patch(VIDEO_CAPTURE, return_value=cap), pytest.raises(PanoScribeError) as exc_info:
        ensure_frames_decodable(video)

    message = str(exc_info.value)
    assert "clip.mp4" in message
    assert "av01" in message
    assert "--no-ocr" in message
    assert '"ocr": false' in message  # the API equivalent
    assert "libx264" in message
    cap.release.assert_called_once()


def test_helper_passes_when_a_frame_reads(tmp_path: Path) -> None:
    cap = _undecodable_capture()
    cap.read.return_value = (True, object())

    with patch(VIDEO_CAPTURE, return_value=cap):
        ensure_frames_decodable(_video(tmp_path))

    cap.release.assert_called_once()


def test_helper_keeps_open_failure_text(tmp_path: Path) -> None:
    cap = _undecodable_capture()
    cap.isOpened.return_value = False

    with (
        patch(VIDEO_CAPTURE, return_value=cap),
        pytest.raises(PanoScribeError, match="Failed to open video for OCR sampling"),
    ):
        ensure_frames_decodable(_video(tmp_path))


def test_helper_unknown_codec_still_gives_the_error(tmp_path: Path) -> None:
    cap = _undecodable_capture(fourcc=0)

    with patch(VIDEO_CAPTURE, return_value=cap), pytest.raises(PanoScribeError) as exc_info:
        ensure_frames_decodable(_video(tmp_path))

    assert "unknown" in str(exc_info.value)
    assert "--no-ocr" in str(exc_info.value)


@pytest.mark.parametrize("scene_change_enabled", [True, False])
def test_sample_frames_raises_when_no_frame_can_be_read(
    tmp_path: Path, scene_change_enabled: bool
) -> None:
    cap = _undecodable_capture()

    with (
        patch(VIDEO_CAPTURE, return_value=cap),
        pytest.raises(PanoScribeError, match="av01") as exc_info,
    ):
        list(sample_frames(_video(tmp_path), fps=1.0, scene_change_enabled=scene_change_enabled))

    assert "--no-ocr" in str(exc_info.value)
    cap.release.assert_called_once()


# -- pipeline ordering -------------------------------------------------------


def _cfg(tmp_path: Path) -> PanoScribeConfig:
    return PanoScribeConfig(_env_file=None, temp_dir=tmp_path / "work")  # type: ignore[call-arg]


def test_pipeline_stops_before_audio_and_speech_when_frames_undecodable(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    engine = MagicMock()

    with (
        patch("panoscribe.pipeline.validate_ocr_settings"),
        patch("panoscribe.pipeline.download_video", return_value=tmp_path / "v.mp4"),
        patch(
            "panoscribe.pipeline.ensure_frames_decodable", side_effect=PanoScribeError("no frames")
        ),
        patch("panoscribe.pipeline.extract_audio") as extract_audio,
        patch("panoscribe.pipeline._build_asr_engine", return_value=engine),
        pytest.raises(PanoScribeError, match="no frames"),
    ):
        process_single_video(
            "https://example.test/video",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    extract_audio.assert_not_called()
    engine.transcribe.assert_not_called()


def test_pipeline_checks_the_downloaded_path_before_extracting_audio(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    video = tmp_path / "v.mp4"
    calls = MagicMock()

    with (
        patch("panoscribe.pipeline.validate_ocr_settings"),
        patch("panoscribe.pipeline._build_asr_engine"),
        patch("panoscribe.pipeline.download_video", calls.download),
        patch("panoscribe.pipeline.ensure_frames_decodable", calls.check),
        patch("panoscribe.pipeline.extract_audio", calls.audio),
        pytest.raises(PanoScribeError, match="stop"),
    ):
        calls.download.return_value = video
        calls.audio.side_effect = PanoScribeError("stop")
        process_single_video(
            "https://example.test/video",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    names = [c[0] for c in calls.mock_calls]
    assert names == ["download", "check", "audio"]
    assert calls.check.call_args.args == (video,)


def test_pipeline_skips_the_check_with_no_ocr(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    engine = MagicMock()
    engine.transcribe.return_value = ([], "en")
    output = tmp_path / "out.json"

    with (
        patch("panoscribe.pipeline._build_asr_engine", return_value=engine),
        patch("panoscribe.pipeline.download_video", return_value=tmp_path / "v.mp4"),
        patch("panoscribe.pipeline.ensure_frames_decodable") as check,
        patch("panoscribe.pipeline.extract_audio", return_value=tmp_path / "a.wav"),
    ):
        process_single_video(
            "https://example.test/video", cfg, output, ocr_active=False, output_format="json"
        )

    check.assert_not_called()
    assert output.exists()


def test_pipeline_photo_branch_does_not_run_the_check(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    engine = MagicMock()
    engine.transcribe.return_value = ([], "en")
    post = MagicMock(image_paths=[], audio_path=None)

    with (
        patch("panoscribe.pipeline.validate_ocr_settings"),
        patch("panoscribe.pipeline._build_asr_engine", return_value=engine),
        patch("panoscribe.pipeline.is_photo_post", return_value=True),
        patch("panoscribe.pipeline.download_photo_post", return_value=post),
        patch("panoscribe.pipeline.RapidOCREngine") as ocr_engine,
        patch("panoscribe.pipeline.ensure_frames_decodable") as check,
    ):
        ocr_engine.return_value.extract_images.return_value = []
        ocr_engine.return_value.last_frame_count = 0
        process_single_video(
            "https://example.test/photo/1",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    check.assert_not_called()


# -- real AV1 clip ----------------------------------------------------------


def _make_av1_clip(tmp_path: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg not installed")
    for encoder in ("libsvtav1", "libaom-av1"):
        clip = tmp_path / f"av1-{encoder}.mp4"
        cmd = [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=10",
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ]
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=120)
        if result.returncode == 0 and clip.is_file():
            return clip
    pytest.skip("ffmpeg has no working AV1 encoder (libsvtav1 / libaom-av1)")


def test_real_av1_clip_decodes_or_raises_our_error(tmp_path: Path) -> None:
    """Whether OpenCV can decode AV1 depends on its build; either outcome must be clean."""
    clip = _make_av1_clip(tmp_path)

    try:
        ensure_frames_decodable(clip)
    except PanoScribeError as exc:
        message = str(exc)
        assert "av01" in message
        assert "--no-ocr" in message
        with pytest.raises(PanoScribeError, match="--no-ocr"):
            list(sample_frames(clip, fps=1.0))
    else:
        assert len(list(sample_frames(clip, fps=1.0))) >= 1
