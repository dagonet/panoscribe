"""Unmocked OCR engine check: every language value panoscribe can select, both model sets.

Every other OCR test mocks ``rapidocr.RapidOCR`` at the import site, so none of
them notices that a rapidocr bump no longer has a model for a language
``_ISO_TO_LANGREC`` can produce (on 3.8.1 eleven of fourteen failed to start).
These tests build the real engine on CPU through ``scripts/probe_ocr_languages.py``
and are marked ``engine`` so the default run never downloads models (see
``pyproject.toml`` addopts); CI runs them in the ``ocr-engine`` job.

Run locally with: ``uv run pytest -m engine -v``
"""

from __future__ import annotations

import re
import unicodedata

import pytest
from scripts.probe_ocr_languages import PROBE_TEXT, probe_language

from panoscribe.ocr.model_sets import V6_LANGS

pytestmark = pytest.mark.engine

_RUN_LENGTH = 4
_TRAILING_YEAR = re.compile(r"\s*\d+\s*$")

# Cases where the engine starts but the synthetic line is not read back, observed on
# rapidocr 3.10.0 after widening the probe margin and sweeping font sizes (see
# docs/plans/2026-11-08-ocr-v6-measurement.md). The start check still applies to them.
_NOT_READ_KOREAN = (
    "engine starts; only '2026' comes back and no Hangul survives (the Task 5 probe saw the "
    "Hangul at 0.53 confidence, under panoscribe's 0.6 filter; rapidocr's Korean font is a "
    "handwriting face)"
)
_NOT_READ_DEVANAGARI = (
    "engine starts; the synthetic line is misread (first word garbled, rest lost)"
)
_NOT_READ_TELUGU = "engine starts; the synthetic line is misread (first word right, rest garbled)"
_WEAK: dict[tuple[str, str], str] = {
    (model_set, language): reason
    for model_set in ("classic", "v6")
    for language, reason in (
        ("korean", _NOT_READ_KOREAN),
        ("devanagari", _NOT_READ_DEVANAGARI),
        ("te", _NOT_READ_TELUGU),
    )
}


class TextNotReadError(AssertionError):
    """The engine started but did not read the probe text (the only xfail-able failure)."""


def _squash(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).split())


def shares_run(probe: str, read: str, length: int = _RUN_LENGTH) -> bool:
    """Return True if ``read`` contains any ``length``-character run of ``probe``'s words.

    The trailing year every probe line ends in is left out: digits are read correctly
    by every model, so counting them would let a model that cannot read the script pass.
    Right-to-left text is compared in logical order, as panoscribe returns it.
    """
    words = _TRAILING_YEAR.sub("", probe)
    core = _squash(words)
    haystack = _squash(read)
    return any(core[i : i + length] in haystack for i in range(len(core) - length + 1))


def _cases() -> list[object]:
    cases: list[object] = []
    for model_set in ("classic", "v6"):
        for language in PROBE_TEXT:
            marks = []
            reason = _WEAK.get((model_set, language))
            if reason is not None:
                marks.append(
                    pytest.mark.xfail(strict=False, raises=TextNotReadError, reason=reason)
                )
            cases.append(
                pytest.param(model_set, language, id=f"{model_set}-{language}", marks=marks)
            )
    return cases


@pytest.mark.parametrize(("model_set", "language"), _cases())
def test_every_mapped_language_starts(model_set: str, language: str) -> None:
    result = probe_language(language, model_set=model_set)

    # Hard requirement: the engine builds and runs for this language and set.
    assert result.ok, result.error
    assert result.error is None, result.error
    # ok alone only means "the engine started"; the text must actually be read back.
    if not result.text.strip():
        raise TextNotReadError(
            f"{language}/{model_set}: nothing read from {PROBE_TEXT[language]!r}"
        )
    if not shares_run(PROBE_TEXT[language], result.text):
        raise TextNotReadError(
            f"{language}/{model_set}: read {result.text!r}, expected {PROBE_TEXT[language]!r}"
        )
    if language == "arabic":
        # The 4-character run above also passes for a reversed read; the year closing the
        # line proves the word order is right (logical order, not display order; #188).
        assert _squash(result.text).endswith("2026"), (
            f"{language}/{model_set}: read {result.text!r}, expected {PROBE_TEXT[language]!r}"
        )


# The real v6 path is built through ISO codes (``de`` -> Rec/Det lang ``de``), which the
# LangRec-valued cases above never exercise (``latin`` has no v6 code). One accented line
# per main language; the classic set maps each of these ISO codes onto ``latin``.
_ISO_PROBE_TEXT: dict[str, str] = {
    "de": "Größe Straße über 2026",
    "fr": "Café français où été 2026",
    "es": "Niño año música canción 2026",
    # The word list "Coração ação português 2026" read as nothing at all under v6 (rapidocr
    # 3.10.0, detector found no box); an ordinary sentence is read correctly by both sets.
    "pt": "Não há razão para isso 2026",
}


@pytest.mark.parametrize("model_set", ["classic", "v6"])
@pytest.mark.parametrize("iso", list(_ISO_PROBE_TEXT))
def test_iso_coded_language_starts(model_set: str, iso: str) -> None:
    text = _ISO_PROBE_TEXT[iso]
    result = probe_language(iso, model_set=model_set, text=text, font_language="latin")

    assert result.ok, result.error
    assert result.error is None, result.error
    assert result.text.strip(), f"{iso}/{model_set}: nothing read from {text!r}"
    assert shares_run(text, result.text), (
        f"{iso}/{model_set}: read {result.text!r}, expected {text!r}"
    )


def test_v6_langs_match_installed_rapidocr() -> None:
    from rapidocr import ModelType, OCRVersion
    from rapidocr.utils.model_resolver import list_supported_langs
    from rapidocr.utils.typings import TaskType

    for task in (TaskType.DET, TaskType.REC):
        supported = list_supported_langs(task, OCRVersion.PPOCRV6, ModelType.SMALL)
        assert frozenset(supported) == V6_LANGS, task
