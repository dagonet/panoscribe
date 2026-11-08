"""Pure-function tests for scripts/probe_ocr_languages.py -- no network, no real OCR engine."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from scripts.probe_ocr_languages import (
    PROBE_TEXT,
    ProbeResult,
    parse_model_names,
    render_probe_image,
    results_to_markdown,
)

from panoscribe.ocr.rapid_ocr import _ISO_TO_LANGREC


def test_probe_text_covers_every_mapped_value() -> None:
    assert set(PROBE_TEXT) == {v.value for v in _ISO_TO_LANGREC.values()}


def test_render_probe_image_writes_png(tmp_path: Path) -> None:
    out = render_probe_image("panoscribe 2026", tmp_path / "probe.png")

    assert out.exists()
    with Image.open(out) as img:
        width, height = img.size
    assert width > height


def test_render_probe_image_accepts_explicit_font(tmp_path: Path) -> None:
    dejavu = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not dejavu.exists():
        pytest.skip("DejaVuSans not installed")

    out = render_probe_image("Größe 2026", tmp_path / "probe.png", font_path=dejavu)

    assert out.exists()


def test_parse_model_names_picks_det_and_rec_ignoring_cls() -> None:
    messages = [
        "Using /x/models/en_PP-OCRv3_det_mobile.onnx",
        "Using /x/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "Using /x/models/latin_PP-OCRv3_rec_mobile.onnx",
        "Using engine_name: onnxruntime",
    ]

    assert parse_model_names(messages) == (
        "en_PP-OCRv3_det_mobile.onnx",
        "latin_PP-OCRv3_rec_mobile.onnx",
    )


def test_parse_model_names_returns_none_when_nothing_logged() -> None:
    assert parse_model_names(["Using engine_name: onnxruntime"]) == (None, None)


def test_results_to_markdown_has_one_row_per_result_and_escapes_pipes() -> None:
    results = [
        ProbeResult("en", True, None, "d.onnx", "r.onnx", "a|b 2026"),
        ProbeResult("ka", False, "boom", None, None, ""),
    ]

    lines = results_to_markdown(results).splitlines()

    assert len(lines) == 2 + len(results)
    assert "a\\|b 2026" in lines[2]
    assert "boom" in lines[3]
