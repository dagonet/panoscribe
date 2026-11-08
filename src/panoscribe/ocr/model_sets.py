"""Model-set resolution for the RapidOCR engine (rapidocr >= 3.10).

Turns ``PanoScribeConfig`` (``ocr_model_set`` plus the per-task knobs) and the
resolved OCR language into the six ``Det.*`` / ``Rec.*`` parameters rapidocr
needs. Pure functions, no rapidocr engine is built here.

Two sets (design ``docs/plans/2026-11-08-ocr-newer-library-design.md``):

* ``classic`` -- today's models: PP-OCRv4 mobile, with the recognition language
  as a :class:`rapidocr.LangRec` member. ``eslav``, ``th`` and ``el`` only have
  PP-OCRv5 recognition models, so those three use PP-OCRv5 mobile for
  *recognition* while detection stays PP-OCRv4.
* ``v6`` -- PP-OCRv6 ``small`` for detection and recognition, addressed by ISO
  code (``de``, ``fr``, ``en``, ``ch``, ``japan``, ...). A language without a
  v6 code falls back to ``classic`` for both tasks -- but only when v6 came from
  the model *set*. An explicit ``PANO_OCR_*_OCR_VERSION=PP-OCRv6`` knob is never
  changed silently; it raises :class:`PanoScribeError` instead.

Explicit knobs (``PANO_OCR_{DET,REC}_{MODEL_TYPE,OCR_VERSION}``,
``PANO_OCR_DET_LANG``) always win over the set, per task.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rapidocr import LangRec, ModelType, OCRVersion
from rapidocr.utils.typings import LangDet

from panoscribe.errors import PanoScribeError

if TYPE_CHECKING:
    from enum import Enum

    from panoscribe.config import PanoScribeConfig

logger = logging.getLogger(__name__)

# PP-OCRv6 ``small`` language list, copied verbatim from rapidocr 3.10
# ``default_models.yaml`` (``ppocrv6_langs``; det and rec share it).
# ``tests/test_model_sets.py`` compares it with the installed wheel.
V6_LANGS: frozenset[str] = frozenset(
    {
        "ch",
        "chinese_cht",
        "en",
        "japan",
        "af",
        "az",
        "bs",
        "ca",
        "cs",
        "cy",
        "da",
        "de",
        "es",
        "et",
        "eu",
        "fi",
        "fr",
        "ga",
        "gl",
        "hr",
        "hu",
        "id",
        "is",
        "it",
        "ku",
        "la",
        "lb",
        "lt",
        "lv",
        "mi",
        "ms",
        "mt",
        "nl",
        "no",
        "oc",
        "pl",
        "pt",
        "qu",
        "rm",
        "ro",
        "rs_latin",
        "sk",
        "sl",
        "sq",
        "sv",
        "sw",
        "tl",
        "tr",
        "uz",
        "vi",
        "french",
        "german",
    }
)

# ISO codes whose PP-OCRv6 name differs (rapidocr's own v6 aliases).
_V6_ISO_ALIASES: dict[str, str] = {"zh": "ch", "ja": "japan"}

# Recognition languages whose models ship only for PP-OCRv5 (no PP-OCRv4 route).
_V5_REC_ONLY: frozenset[str] = frozenset({"eslav", "th", "el"})

# Classic detector per recognition language. ``en`` covers Latin script (as it has
# since 0.x); Chinese-family scripts use ``ch``; every other script uses ``multi``.
_CLASSIC_DET_BY_LANG: dict[str, str] = {
    "en": "en",
    "latin": "en",
    "ch": "ch",
    "chinese_cht": "ch",
    "japan": "ch",
}
_CLASSIC_DET_DEFAULT = "multi"


def resolve_iso(ocr_language: str, detected_language: str | None) -> str | None:
    """Return the ISO code in effect, or ``None`` when ``ocr_language`` is a ``LangRec`` value.

    ``"auto"`` yields the detected language (``"en"`` when there is none, as
    :func:`panoscribe.ocr.rapid_ocr._resolve_ocr_language` does). A configured
    ISO code is returned as is. A value such as ``"latin"`` or ``"en"`` that is
    already a ``LangRec`` member carries no ISO code.
    """
    try:
        LangRec(ocr_language)
    except ValueError:
        pass
    else:
        return None
    if ocr_language == "auto":
        return detected_language or "en"
    return ocr_language


def _v6_code(lang: LangRec, iso: str | None) -> str | None:
    """Return the PP-OCRv6 language code for this language, or ``None`` if v6 has none."""
    if iso is not None:
        if iso in V6_LANGS:
            return iso
        alias = _V6_ISO_ALIASES.get(iso)
        if alias is not None and alias in V6_LANGS:
            return alias
    if lang.value in V6_LANGS:
        return lang.value
    return None


def _det_member(value: str) -> Enum:
    """Return the enum member to pass as ``Det.lang_type`` for a classic detector.

    ``en`` and ``ch`` stay :class:`LangRec` members, the type this engine has always
    passed for them; ``multi`` only exists in :class:`LangDet`. rapidocr resolves the
    language by ``.value`` (``utils/model_resolver.normalize_lang``), so both work.
    """
    if value in {"en", "ch"}:
        return LangRec(value)
    return LangDet(value)


def _classic_det_value(
    config: PanoScribeConfig, lang: LangRec, version: OCRVersion, model_type: ModelType
) -> Enum:
    # No non-ch det model ships for v5 or server: force ch (wins over PANO_OCR_DET_LANG).
    if version is OCRVersion.PPOCRV5 or model_type is ModelType.SERVER:
        logger.info(
            "Server/v5 det selected: forcing Det.lang_type to CH "
            "(rapidocr model registry limitation -- only ch_* det models ship for these variants)"
        )
        return _det_member("ch")
    if config.ocr_det_lang is not None:
        return LangDet(config.ocr_det_lang)
    return _det_member(_CLASSIC_DET_BY_LANG.get(lang.value, _CLASSIC_DET_DEFAULT))


def build_model_params(
    config: PanoScribeConfig, lang: LangRec, iso: str | None
) -> tuple[dict[str, object], bool]:
    """Resolve the rapidocr ``Det.*`` / ``Rec.*`` model parameters.

    Returns ``(params, fell_back)``: ``params`` holds exactly ``Det.lang_type``,
    ``Det.ocr_version``, ``Det.model_type`` and the same three ``Rec.*`` keys;
    ``fell_back`` is True when the ``v6`` set was asked for but ``lang`` has no
    PP-OCRv6 code, so the set's tasks use the classic models instead.

    Raises :class:`PanoScribeError` when a PP-OCRv6 *knob* is set but ``lang`` has
    no v6 code (explicit settings are never changed silently).
    """
    code = _v6_code(lang, iso)
    det_knob = OCRVersion(config.ocr_det_ocr_version) if config.ocr_det_ocr_version else None
    rec_knob = OCRVersion(config.ocr_rec_ocr_version) if config.ocr_rec_ocr_version else None

    if code is None and OCRVersion.PPOCRV6 in (det_knob, rec_knob):
        supported = ", ".join(sorted(V6_LANGS))
        raise PanoScribeError(
            f"OCR language {lang.value!r} has no PP-OCRv6 model; supported: {supported}"
        )

    want_v6 = config.ocr_model_set == "v6"
    set_driven = det_knob is None or rec_knob is None
    fell_back = want_v6 and code is None and set_driven
    if fell_back:
        logger.info(
            "PP-OCRv6 has no model for OCR language %r; using the classic models "
            "for detection and recognition",
            lang.value,
        )
    set_version = OCRVersion.PPOCRV6 if want_v6 and code is not None else None

    rec_classic = OCRVersion.PPOCRV5 if lang.value in _V5_REC_ONLY else OCRVersion.PPOCRV4
    det_version = det_knob or set_version or OCRVersion.PPOCRV4
    rec_version = rec_knob or set_version or rec_classic

    det_type = _model_type(config.ocr_det_model_type, det_version)
    rec_type = _model_type(config.ocr_rec_model_type, rec_version)

    det_lang: object
    rec_lang: object
    if det_version is OCRVersion.PPOCRV6:
        det_lang = code
    else:
        det_lang = _classic_det_value(config, lang, det_version, det_type)
    rec_lang = code if rec_version is OCRVersion.PPOCRV6 else lang

    params: dict[str, object] = {
        "Det.lang_type": det_lang,
        "Det.ocr_version": det_version,
        "Det.model_type": det_type,
        "Rec.lang_type": rec_lang,
        "Rec.ocr_version": rec_version,
        "Rec.model_type": rec_type,
    }
    return params, fell_back


def _model_type(knob: str | None, version: OCRVersion) -> ModelType:
    """Return the knob if set, else ``small`` for PP-OCRv6 and ``mobile`` for v4/v5."""
    if knob is not None:
        return ModelType(knob)
    return ModelType.SMALL if version is OCRVersion.PPOCRV6 else ModelType.MOBILE
