"""OCR settings are checked before any download (#191)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from panoscribe.config import PanoScribeConfig
from panoscribe.errors import PanoScribeError
from panoscribe.ocr.rapid_ocr import RapidOCREngine, validate_ocr_settings
from panoscribe.pipeline import process_single_video

CUDA_CHECK = "panoscribe.ocr.rapid_ocr.require_cuda_for_ocr"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [k for k in os.environ if k.startswith("PANO_")]:
        monkeypatch.delenv(name, raising=False)


def _cfg(tmp_path: Path, **over: object) -> PanoScribeConfig:
    values: dict[str, object] = {
        "temp_dir": tmp_path / "work",
        "ocr_language": "en",
        "ocr_device": "cpu",  # the default is cuda; keep these tests independent of the host
    }
    values.update(over)
    return PanoScribeConfig(_env_file=None, **values)  # type: ignore[arg-type]


# ── unit: the check itself ───────────────────────────────────────────────


def test_defaults_pass(tmp_path: Path) -> None:
    validate_ocr_settings(_cfg(tmp_path))
    validate_ocr_settings(_cfg(tmp_path, ocr_language="auto"))


@pytest.mark.parametrize("language", ["en", "auto"])
@pytest.mark.parametrize("knob", ["ocr_rec_model_type", "ocr_det_model_type"])
def test_v6_model_type_with_classic_set_fails_for_any_language(
    tmp_path: Path, knob: str, language: str
) -> None:
    cfg = _cfg(tmp_path, ocr_language=language, **{knob: "medium"})

    with pytest.raises(PanoScribeError, match="MODEL_TYPE"):
        validate_ocr_settings(cfg)


def test_classic_model_type_pinned_to_v6_version_fails(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path, ocr_language="auto", ocr_rec_ocr_version="PP-OCRv6", ocr_rec_model_type="server"
    )

    with pytest.raises(PanoScribeError, match="PANO_OCR_REC_MODEL_TYPE"):
        validate_ocr_settings(cfg)


def test_v6_model_type_pinned_to_v4_version_fails(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        ocr_language="auto",
        ocr_det_ocr_version="PP-OCRv4",
        ocr_det_model_type="small",
    )

    with pytest.raises(PanoScribeError, match="PANO_OCR_DET_MODEL_TYPE"):
        validate_ocr_settings(cfg)


def test_det_lang_multi_with_pinned_v6_detector_fails_for_auto(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="auto", ocr_det_ocr_version="PP-OCRv6", ocr_det_lang="multi")

    with pytest.raises(PanoScribeError, match="PANO_OCR_DET_LANG"):
        validate_ocr_settings(cfg)


def test_cuda_device_without_provider_fails(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="auto", ocr_device="cuda")

    with (
        patch(CUDA_CHECK, side_effect=PanoScribeError("no CUDA")) as cuda,
        pytest.raises(PanoScribeError, match="no CUDA"),
    ):
        validate_ocr_settings(cfg)

    cuda.assert_called_once()


def test_cpu_device_never_checks_cuda(tmp_path: Path) -> None:
    with patch(CUDA_CHECK) as cuda:
        validate_ocr_settings(_cfg(tmp_path))

    cuda.assert_not_called()


def test_explicit_language_runs_full_check(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="ko", ocr_rec_ocr_version="PP-OCRv6")

    with pytest.raises(PanoScribeError, match="no PP-OCRv6 model"):
        validate_ocr_settings(cfg)


def test_explicit_language_v6_set_with_server_type_fails(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="de", ocr_model_set="v6", ocr_rec_model_type="server")

    with pytest.raises(PanoScribeError, match="PANO_OCR_REC_MODEL_TYPE"):
        validate_ocr_settings(cfg)


def test_auto_language_leaves_language_dependent_problems_for_engine_start(
    tmp_path: Path,
) -> None:
    """v6 pinned for Rec: whether the language has a v6 model is unknown until detection."""
    cfg = _cfg(tmp_path, ocr_language="auto", ocr_rec_ocr_version="PP-OCRv6")

    validate_ocr_settings(cfg)  # must not raise

    engine = RapidOCREngine(cfg)
    with pytest.raises(PanoScribeError, match="no PP-OCRv6 model"):
        engine._ensure_loaded(detected_language="ko")


def test_auto_language_v6_set_mobile_type_is_left_for_engine_start(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="auto", ocr_model_set="v6", ocr_rec_model_type="mobile")

    validate_ocr_settings(cfg)  # fits the classic fallback, so not language independent


def test_check_loads_nothing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_language="de", ocr_model_set="v6")

    with patch("panoscribe.ocr.rapid_ocr.RapidOCR") as engine_cls:
        validate_ocr_settings(cfg)

    engine_cls.assert_not_called()


# ── process_single_video: fails before any download ──────────────────────


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"ocr_rec_model_type": "medium"}, "PANO_OCR_REC_MODEL_TYPE"),
        ({"ocr_language": "ko", "ocr_rec_ocr_version": "PP-OCRv6"}, "no PP-OCRv6 model"),
    ],
)
def test_bad_ocr_setting_fails_before_download(
    tmp_path: Path, over: dict[str, object], match: str
) -> None:
    cfg = _cfg(tmp_path, **over)

    with (
        patch("panoscribe.pipeline.download_video") as download_video,
        patch("panoscribe.pipeline.download_photo_post") as download_photo_post,
        patch("panoscribe.pipeline.WhisperTranscriber"),
        pytest.raises(PanoScribeError, match=match),
    ):
        process_single_video(
            "https://example.test/video",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    download_video.assert_not_called()
    download_photo_post.assert_not_called()


def test_bad_ocr_setting_fails_before_photo_download(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_rec_model_type="medium")

    with (
        patch("panoscribe.pipeline.download_photo_post") as download_photo_post,
        patch("panoscribe.pipeline.WhisperTranscriber"),
        pytest.raises(PanoScribeError, match="PANO_OCR_REC_MODEL_TYPE"),
    ):
        process_single_video(
            "https://www.tiktok.com/@u/photo/1",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    download_photo_post.assert_not_called()


def test_no_ocr_skips_the_check(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ocr_rec_model_type="medium")
    engine = MagicMock()
    engine.transcribe.return_value = ([], "en")
    output = tmp_path / "out.json"

    with (
        patch("panoscribe.pipeline.validate_ocr_settings") as check,
        patch("panoscribe.pipeline.download_video", return_value=tmp_path / "v.mp4"),
        patch("panoscribe.pipeline.extract_audio", return_value=tmp_path / "a.wav"),
        patch("panoscribe.pipeline.WhisperTranscriber", return_value=engine),
    ):
        process_single_video(
            "https://example.test/video", cfg, output, ocr_active=False, output_format="json"
        )

    check.assert_not_called()
    assert output.exists()


def test_check_runs_after_speech_engine_and_before_download(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    calls = MagicMock()

    with (
        patch("panoscribe.pipeline._build_asr_engine", calls.asr),
        patch("panoscribe.pipeline.validate_ocr_settings", calls.ocr),
        patch("panoscribe.pipeline.download_video", calls.download),
        pytest.raises(PanoScribeError, match="stop"),
    ):
        calls.download.side_effect = PanoScribeError("stop")
        process_single_video(
            "https://example.test/video",
            cfg,
            tmp_path / "out.json",
            ocr_active=True,
            output_format="json",
        )

    assert [c[0] for c in calls.mock_calls] == ["asr", "ocr", "download"]
