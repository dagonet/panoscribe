"""Unit tests for panoscribe.ocr.model_sets (pure parameter resolution, no rapidocr engine)."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

import pytest
import yaml
from rapidocr import LangRec, ModelType, OCRVersion
from rapidocr.utils.typings import LangDet

from panoscribe.config import PanoScribeConfig
from panoscribe.errors import PanoScribeError
from panoscribe.ocr.model_sets import V6_LANGS, build_model_params, resolve_iso
from panoscribe.ocr.rapid_ocr import _resolve_ocr_language

V4 = "PP-OCRv4"
V5 = "PP-OCRv5"
V6 = "PP-OCRv6"

_KEYS = {
    "Det.lang_type",
    "Det.ocr_version",
    "Det.model_type",
    "Rec.lang_type",
    "Rec.ocr_version",
    "Rec.model_type",
}


def _val(x: object) -> object:
    return x.value if isinstance(x, Enum) else x


def _config(**overrides: object) -> PanoScribeConfig:
    base: dict[str, object] = {"ocr_language": "en", "ocr_device": "cpu"}
    base.update(overrides)
    return PanoScribeConfig(**base)


def _build(
    detected: str | None = None, **overrides: object
) -> tuple[dict[str, tuple[object, object, object]], bool]:
    """Run the resolver the way the engine does; return ((lang, version, model_type) per task)."""
    config = _config(**overrides)
    lang = _resolve_ocr_language(config.ocr_language, detected_language=detected)
    iso = resolve_iso(config.ocr_language, detected)
    params, fell_back = build_model_params(config, lang, iso)
    assert set(params) == _KEYS
    view = {
        task: (
            _val(params[f"{task}.lang_type"]),
            _val(params[f"{task}.ocr_version"]),
            _val(params[f"{task}.model_type"]),
        )
        for task in ("Det", "Rec")
    }
    return view, fell_back


def test_v6_langs_matches_installed_rapidocr_small_list() -> None:
    import rapidocr

    yaml_path = Path(rapidocr.__file__).parent / "default_models.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    entries = data["model_routes"]["PP-OCRv6"]
    det_small = entries["det"]["small"][0]["supported_langs"]
    rec_small = entries["rec"]["small"][0]["supported_langs"]
    assert frozenset(det_small) == V6_LANGS
    assert frozenset(rec_small) == V6_LANGS


@pytest.mark.parametrize(
    ("overrides", "detected", "det", "rec", "fell_back"),
    [
        # classic keeps today's models; Latin script is detected with `en`.
        ({"ocr_language": "de"}, None, ("en", V4, "mobile"), ("latin", V4, "mobile"), False),
        ({"ocr_language": "latin"}, None, ("en", V4, "mobile"), ("latin", V4, "mobile"), False),
        ({"ocr_language": "en"}, None, ("en", V4, "mobile"), ("en", V4, "mobile"), False),
        ({"ocr_language": "ch"}, None, ("ch", V4, "mobile"), ("ch", V4, "mobile"), False),
        ({"ocr_language": "zh"}, None, ("ch", V4, "mobile"), ("ch", V4, "mobile"), False),
        ({"ocr_language": "ja"}, None, ("ch", V4, "mobile"), ("japan", V4, "mobile"), False),
        ({"ocr_language": "ko"}, None, ("multi", V4, "mobile"), ("korean", V4, "mobile"), False),
        ({"ocr_language": "ar"}, None, ("multi", V4, "mobile"), ("arabic", V4, "mobile"), False),
        (
            {"ocr_language": "hi"},
            None,
            ("multi", V4, "mobile"),
            ("devanagari", V4, "mobile"),
            False,
        ),
        ({"ocr_language": "bg"}, None, ("multi", V4, "mobile"), ("cyrillic", V4, "mobile"), False),
        ({"ocr_language": "ta"}, None, ("multi", V4, "mobile"), ("ta", V4, "mobile"), False),
        ({"ocr_language": "te"}, None, ("multi", V4, "mobile"), ("te", V4, "mobile"), False),
        ({"ocr_language": "kn"}, None, ("multi", V4, "mobile"), ("ka", V4, "mobile"), False),
        # eslav / th / el: the recognition models exist only for PP-OCRv5; detection stays v4.
        ({"ocr_language": "ru"}, None, ("multi", V4, "mobile"), ("eslav", V5, "mobile"), False),
        ({"ocr_language": "th"}, None, ("multi", V4, "mobile"), ("th", V5, "mobile"), False),
        ({"ocr_language": "el"}, None, ("multi", V4, "mobile"), ("el", V5, "mobile"), False),
        ({"ocr_language": "auto"}, "fr", ("en", V4, "mobile"), ("latin", V4, "mobile"), False),
        # v6 with a v6 code: ISO code for both tasks, small models.
        (
            {"ocr_language": "de", "ocr_model_set": "v6"},
            None,
            ("de", V6, "small"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "pt",
            ("pt", V6, "small"),
            ("pt", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "zh", "ocr_model_set": "v6"},
            None,
            ("ch", V6, "small"),
            ("ch", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "ja",
            ("japan", V6, "small"),
            ("japan", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "en", "ocr_model_set": "v6"},
            None,
            ("en", V6, "small"),
            ("en", V6, "small"),
            False,
        ),
        # Unmapped / missing detected language resolves to en (Review Focus 2).
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "xx",
            ("en", V6, "small"),
            ("en", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            None,
            ("en", V6, "small"),
            ("en", V6, "small"),
            False,
        ),
        # Georgian detected: no mapping, falls back to en like any unmapped code.
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "ka",
            ("en", V6, "small"),
            ("en", V6, "small"),
            False,
        ),
        # v6 requested, language has no v6 code: classic for BOTH tasks (Review Focus 1).
        (
            {"ocr_language": "latin", "ocr_model_set": "v6"},
            None,
            ("en", V4, "mobile"),
            ("latin", V4, "mobile"),
            True,
        ),
        (
            {"ocr_language": "ko", "ocr_model_set": "v6"},
            None,
            ("multi", V4, "mobile"),
            ("korean", V4, "mobile"),
            True,
        ),
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "ru",
            ("multi", V4, "mobile"),
            ("eslav", V5, "mobile"),
            True,
        ),
        # Knobs override the set per task.
        (
            {"ocr_language": "de", "ocr_rec_ocr_version": V6},
            None,
            ("en", V4, "mobile"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_det_ocr_version": V6},
            None,
            ("de", V6, "small"),
            ("latin", V4, "mobile"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_det_ocr_version": V4},
            None,
            ("en", V4, "mobile"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_rec_model_type": "medium"},
            None,
            ("de", V6, "small"),
            ("de", V6, "medium"),
            False,
        ),
        # A knob that pins a classic version keeps that task classic while the other task
        # (no v6 code, so it falls back) is classic too.
        (
            {"ocr_language": "ko", "ocr_model_set": "v6", "ocr_rec_ocr_version": V4},
            None,
            ("multi", V4, "mobile"),
            ("korean", V4, "mobile"),
            True,
        ),
        # Existing CH-det rule: v5 det or server det forces the CH detector.
        (
            {"ocr_language": "de", "ocr_det_ocr_version": V5},
            None,
            ("ch", V5, "mobile"),
            ("latin", V4, "mobile"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_det_model_type": "server"},
            None,
            ("ch", V4, "server"),
            ("latin", V4, "mobile"),
            False,
        ),
        # PANO_OCR_DET_LANG still selects the detector; the CH rule still beats it.
        (
            {"ocr_language": "de", "ocr_det_lang": "multi"},
            None,
            ("multi", V4, "mobile"),
            ("latin", V4, "mobile"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_det_lang": "multi", "ocr_det_model_type": "server"},
            None,
            ("ch", V4, "server"),
            ("latin", V4, "mobile"),
            False,
        ),
        # R14 (a): PANO_OCR_DET_LANG with a set-driven v6 Det keeps Det on classic v4 with
        # that language; Rec still follows the set. Not a fallback (de has a v6 code).
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_det_lang": "multi"},
            None,
            ("multi", V4, "mobile"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_det_lang": "ch"},
            None,
            ("ch", V4, "mobile"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_det_lang": "en"},
            None,
            ("en", V4, "mobile"),
            ("de", V6, "small"),
            False,
        ),
        (
            {
                "ocr_language": "de",
                "ocr_model_set": "v6",
                "ocr_det_lang": "multi",
                "ocr_det_model_type": "server",
            },
            None,
            ("ch", V4, "server"),
            ("de", V6, "small"),
            False,
        ),
        # DET_LANG with a language that has no v6 code: ordinary fallback, DET_LANG honoured.
        (
            {"ocr_language": "ko", "ocr_model_set": "v6", "ocr_det_lang": "ch"},
            None,
            ("ch", V4, "mobile"),
            ("korean", V4, "mobile"),
            True,
        ),
        # R14 (b): a Det version knob pinning v6 takes DET_LANG as the v6 Det language.
        (
            {"ocr_language": "de", "ocr_det_ocr_version": V6, "ocr_det_lang": "en"},
            None,
            ("en", V6, "small"),
            ("latin", V4, "mobile"),
            False,
        ),
        (
            {
                "ocr_language": "de",
                "ocr_model_set": "v6",
                "ocr_det_ocr_version": V6,
                "ocr_det_lang": "ch",
            },
            None,
            ("ch", V6, "small"),
            ("de", V6, "small"),
            False,
        ),
        (
            {"ocr_language": "ko", "ocr_det_ocr_version": V6, "ocr_det_lang": "en"},
            None,
            ("en", V6, "small"),
            ("korean", V4, "mobile"),
            False,
        ),
        # Auto-detected ISO code that v6 knows but _ISO_TO_LANGREC does not.
        (
            {"ocr_language": "auto", "ocr_model_set": "v6"},
            "hr",
            ("hr", V6, "small"),
            ("hr", V6, "small"),
            False,
        ),
        # Rec model-type knob alone keeps the classic version.
        (
            {"ocr_language": "de", "ocr_rec_model_type": "server"},
            None,
            ("en", V4, "mobile"),
            ("latin", V4, "server"),
            False,
        ),
    ],
)
def test_build_model_params(
    overrides: dict[str, object],
    detected: str | None,
    det: tuple[str, str, str],
    rec: tuple[str, str, str],
    fell_back: bool,
) -> None:
    view, got_fell_back = _build(detected, **overrides)
    assert view["Det"] == det
    assert view["Rec"] == rec
    assert got_fell_back is fell_back


def test_classic_params_use_enum_members_for_versions_and_types() -> None:
    config = _config(ocr_language="de")
    params, _ = build_model_params(config, LangRec.LATIN, "de")
    assert params["Rec.lang_type"] is LangRec.LATIN
    assert params["Rec.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Rec.model_type"] is ModelType.MOBILE
    assert params["Det.ocr_version"] is OCRVersion.PPOCRV4
    assert params["Det.model_type"] is ModelType.MOBILE
    assert isinstance(params["Det.lang_type"], Enum)


def test_v6_params_use_plain_strings_for_languages() -> None:
    config = _config(ocr_language="de", ocr_model_set="v6")
    params, _ = build_model_params(config, LangRec.LATIN, "de")
    assert params["Det.lang_type"] == "de"
    assert params["Rec.lang_type"] == "de"
    assert params["Det.ocr_version"] is OCRVersion.PPOCRV6
    assert params["Rec.model_type"] is ModelType.SMALL


def test_det_lang_knob_passes_a_langdet_member() -> None:
    config = _config(ocr_language="de", ocr_det_lang="multi")
    params, _ = build_model_params(config, LangRec.LATIN, "de")
    assert params["Det.lang_type"] is LangDet.MULTI


@pytest.mark.parametrize(
    ("overrides", "detected", "language_word"),
    [
        ({"ocr_language": "ko", "ocr_rec_ocr_version": V6}, None, "korean"),
        ({"ocr_language": "ko", "ocr_det_ocr_version": V6}, None, "korean"),
        ({"ocr_language": "latin", "ocr_rec_ocr_version": V6}, None, "latin"),
        # The knob wins over the set: no silent fallback even when the set is v6.
        (
            {"ocr_language": "ko", "ocr_model_set": "v6", "ocr_rec_ocr_version": V6},
            None,
            "korean",
        ),
        ({"ocr_language": "auto", "ocr_det_ocr_version": V6}, "ru", "eslav"),
    ],
)
def test_explicit_v6_knob_without_v6_code_raises(
    overrides: dict[str, object], detected: str | None, language_word: str
) -> None:
    with pytest.raises(PanoScribeError) as excinfo:
        _build(detected, **overrides)
    message = str(excinfo.value)
    assert f"'{language_word}'" in message
    assert "has no PP-OCRv6 model" in message
    assert "supported: af, az" in message  # the sorted V6_LANGS list starts here


@pytest.mark.parametrize(
    "overrides",
    [
        # R14 (b): DET_LANG=multi has no PP-OCRv6 model, so a pinned v6 Det cannot use it.
        {"ocr_language": "de", "ocr_det_ocr_version": V6, "ocr_det_lang": "multi"},
        {
            "ocr_language": "de",
            "ocr_model_set": "v6",
            "ocr_det_ocr_version": V6,
            "ocr_det_lang": "multi",
        },
    ],
)
def test_pinned_v6_det_with_multi_det_lang_names_the_knob(overrides: dict[str, object]) -> None:
    with pytest.raises(PanoScribeError) as excinfo:
        _build(None, **overrides)
    message = str(excinfo.value)
    assert "PANO_OCR_DET_LANG" in message
    assert "'multi'" in message
    assert "'en' or 'ch'" in message


@pytest.mark.parametrize(
    ("overrides", "detected", "env_name", "knob", "version", "language", "allowed"),
    [
        # v6 set + auto-detected ru falls back to Rec ESLAV / PP-OCRv5; `medium` is v6-only.
        (
            {"ocr_language": "auto", "ocr_model_set": "v6", "ocr_rec_model_type": "medium"},
            "ru",
            "PANO_OCR_REC_MODEL_TYPE",
            "medium",
            V5,
            "ru",
            "mobile, server",
        ),
        # Same for Det on a fallback language: ko -> classic PP-OCRv4 detector.
        (
            {"ocr_language": "ko", "ocr_model_set": "v6", "ocr_det_model_type": "small"},
            None,
            "PANO_OCR_DET_MODEL_TYPE",
            "small",
            V4,
            "ko",
            "mobile, server",
        ),
        # v6 + a classic-only type on a v6 language.
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_rec_model_type": "mobile"},
            None,
            "PANO_OCR_REC_MODEL_TYPE",
            "mobile",
            V6,
            "de",
            "tiny, small, medium",
        ),
        (
            {"ocr_language": "de", "ocr_model_set": "v6", "ocr_det_model_type": "server"},
            None,
            "PANO_OCR_DET_MODEL_TYPE",
            "server",
            V6,
            "de",
            "tiny, small, medium",
        ),
        # classic set + a v6 size.
        (
            {"ocr_language": "de", "ocr_rec_model_type": "tiny"},
            None,
            "PANO_OCR_REC_MODEL_TYPE",
            "tiny",
            V4,
            "de",
            "mobile, server",
        ),
    ],
)
def test_model_type_knob_that_does_not_fit_the_effective_version_raises(
    overrides: dict[str, object],
    detected: str | None,
    env_name: str,
    knob: str,
    version: str,
    language: str,
    allowed: str,
) -> None:
    with pytest.raises(PanoScribeError) as excinfo:
        _build(detected, **overrides)
    message = str(excinfo.value)
    assert f"{env_name}='{knob}'" in message
    assert version in message
    assert f"'{language}'" in message
    assert f"takes: {allowed}" in message


def test_det_lang_under_v6_set_does_not_log_the_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="panoscribe.ocr.model_sets")
    _view, fell_back = _build(None, ocr_language="de", ocr_model_set="v6", ocr_det_lang="multi")
    assert fell_back is False
    messages = [r.getMessage() for r in caplog.records if r.name == "panoscribe.ocr.model_sets"]
    assert not any("has no model" in m for m in messages)
    assert any("PANO_OCR_DET_LANG" in m for m in messages)


def test_fallback_logs_info_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="panoscribe.ocr.model_sets")
    _build(None, ocr_language="ko", ocr_model_set="v6")
    records = [r for r in caplog.records if r.name == "panoscribe.ocr.model_sets"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "korean" in records[0].getMessage()


def test_no_fallback_log_when_v6_code_exists(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="panoscribe.ocr.model_sets")
    _build(None, ocr_language="de", ocr_model_set="v6")
    assert [r for r in caplog.records if r.name == "panoscribe.ocr.model_sets"] == []


@pytest.mark.parametrize(
    ("ocr_language", "detected", "expected"),
    [
        ("auto", "pt", "pt"),
        ("auto", None, "en"),
        ("auto", "xx", "xx"),
        ("latin", "pt", None),
        ("en", "pt", None),
        ("ch", None, None),
        ("fr", None, "fr"),
        ("de", "pt", "de"),
        ("zh", None, "zh"),
    ],
)
def test_resolve_iso(ocr_language: str, detected: str | None, expected: str | None) -> None:
    assert resolve_iso(ocr_language, detected) == expected
