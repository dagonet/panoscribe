#!/usr/bin/env python3
"""Probe every OCR language panoscribe can select against the installed rapidocr.

For each distinct ``LangRec`` value that ``_ISO_TO_LANGREC`` can produce, this
builds the real :class:`panoscribe.ocr.rapid_ocr.RapidOCREngine` (CPU), runs it
on one rendered test image and records whether the engine started, which
detection and recognition model files it loaded and what text it read back.

Run it once per rapidocr version / model set to compare them::

    python scripts/probe_ocr_languages.py                       # table to stdout
    python scripts/probe_ocr_languages.py --model-set v6        # needs ``ocr_model_set``
    python scripts/probe_ocr_languages.py --json /tmp/probe.json

First runs download the ONNX models and the per-language fonts that rapidocr
ships for drawing results. When no font covers a script the engine start is
still probed, with ``text=""`` and the error ``"no font"``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

logger = logging.getLogger(__name__)

# One short, common phrase with a 4-digit year per LangRec value the mapping produces.
PROBE_TEXT: dict[str, str] = {
    "en": "panoscribe 2026",
    "latin": "Größe Straße 2026",
    "eslav": "Привет мир 2026",
    "cyrillic": "Добър ден 2026",
    "ch": "你好世界 2026",
    "japan": "こんにちは世界 2026",
    "korean": "안녕하세요 2026",
    "arabic": "مرحبا بالعالم 2026",
    "devanagari": "नमस्ते दुनिया 2026",
    "th": "สวัสดีชาวโลก 2026",
    "el": "Καλημέρα κόσμε 2026",
    "ta": "வணக்கம் உலகம் 2026",
    "te": "హలో ప్రపంచం 2026",
    # rapidocr's LangRec.KA is Kannada (kannada.ttf / ka_PP-OCRv3 rec), not Georgian.
    "ka": "ನಮಸ್ಕಾರ ಜಗತ್ತು 2026",
}

_FONT_SIZE = 60
_PADDING = 40
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
# Scripts the system DejaVu Sans covers, used only if rapidocr's own font is unavailable.
_DEJAVU_SCRIPTS = frozenset({"en", "latin", "eslav", "cyrillic", "el"})
_MODEL_LOG_RE = re.compile(r"^Using (?P<path>.+\.onnx)$")


@dataclass(frozen=True)
class ProbeResult:
    language: str
    ok: bool
    error: str | None
    det_model: str | None
    rec_model: str | None
    text: str


def _load_font(font_path: Path | None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path is None and _DEJAVU.exists():
        font_path = _DEJAVU
    if font_path is not None:
        return ImageFont.truetype(str(font_path), _FONT_SIZE)
    return ImageFont.load_default(size=_FONT_SIZE)


def render_probe_image(text: str, path: Path, *, font_path: Path | None = None) -> Path:
    """Draw ``text`` in black on white at ~60 px and save it as ``path``."""
    font = _load_font(font_path)
    left, top, right, bottom = font.getbbox(text)
    width = right - left + 2 * _PADDING
    height = bottom - top + 2 * _PADDING
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).text((_PADDING - left, _PADDING - top), text, fill="black", font=font)
    image.save(path)
    return path


def font_for_language(language: str) -> Path | None:
    """Return a font file covering ``language``'s script, or ``None`` if none is available."""
    try:
        from rapidocr import LangRec
        from rapidocr.utils.vis_res import get_font_path

        font = Path(get_font_path(None, LangRec(language)))
        if font.exists():
            return font
    except Exception as exc:  # download/registry failure: fall through to system font
        logger.warning("rapidocr font for %r unavailable: %s", language, exc)
    if language in _DEJAVU_SCRIPTS and _DEJAVU.exists():
        return _DEJAVU
    return None


def parse_model_names(messages: Iterable[str]) -> tuple[str | None, str | None]:
    """Pick the detection and recognition model file names out of rapidocr's log lines."""
    det: str | None = None
    rec: str | None = None
    for message in messages:
        match = _MODEL_LOG_RE.match(message)
        if match is None:
            continue
        name = Path(match.group("path")).name
        if re.search(r"[_-]det[_.-]", name):
            det = name
        elif re.search(r"[_-]rec[_.-]", name):
            rec = name
    return det, rec


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _capture_rapidocr_log() -> Iterator[_Capture]:
    capture = _Capture()
    rapid_logger = logging.getLogger("RapidOCR")
    rapid_logger.addHandler(capture)
    try:
        yield capture
    finally:
        rapid_logger.removeHandler(capture)


def probe_language(ocr_language: str, *, model_set: str | None = None) -> ProbeResult:
    """Start the real engine for ``ocr_language`` and read one rendered probe image."""
    from panoscribe.config import PanoScribeConfig
    from panoscribe.ocr.rapid_ocr import RapidOCREngine

    text = PROBE_TEXT[ocr_language]
    config_kwargs: dict[str, object] = {"ocr_language": ocr_language, "ocr_device": "cpu"}
    if model_set is not None:
        config_kwargs["ocr_model_set"] = model_set
    with _capture_rapidocr_log() as capture, tempfile.TemporaryDirectory() as tmp:
        font = font_for_language(ocr_language)
        image = render_probe_image(text, Path(tmp) / "probe.png", font_path=font)
        try:
            engine = RapidOCREngine(PanoScribeConfig(**config_kwargs))
            segments = engine.extract_images([image])
        except Exception as exc:
            det, rec = parse_model_names(capture.messages)
            return ProbeResult(ocr_language, False, f"{type(exc).__name__}: {exc}", det, rec, "")
    det, rec = parse_model_names(capture.messages)
    if font is None:
        return ProbeResult(ocr_language, True, "no font", det, rec, "")
    read = " ".join(segment.text for segment in segments)
    return ProbeResult(ocr_language, True, None, det, rec, read)


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def results_to_markdown(results: Sequence[ProbeResult]) -> str:
    """Render ``results`` as a Markdown table (one row per language)."""
    lines = [
        "| language | ok | det model | rec model | probe text | recognised text | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        cells = [
            r.language,
            "yes" if r.ok else "no",
            r.det_model,
            r.rec_model,
            PROBE_TEXT.get(r.language),
            r.text,
            r.error,
        ]
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-set", choices=["classic", "v6"], default=None)
    parser.add_argument("--json", type=Path, default=None, metavar="OUT")
    args = parser.parse_args(argv)

    results = [probe_language(lang, model_set=args.model_set) for lang in PROBE_TEXT]
    rapidocr_version = version("rapidocr")
    print(f"rapidocr {rapidocr_version}, model_set={args.model_set}")
    print(results_to_markdown(results))
    if args.json is not None:
        payload = {
            "rapidocr_version": rapidocr_version,
            "model_set": args.model_set,
            "results": [asdict(r) for r in results],
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
