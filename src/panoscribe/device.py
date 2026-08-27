"""CUDA availability probes for the ASR (CTranslate2) and OCR (ONNXRuntime) engines.

The two runtimes answer "is CUDA available?" differently and must not be
conflated:

* ASR / CTranslate2 -- ``ctranslate2.get_cuda_device_count() > 0``.
  ``faster-whisper`` never routes inference through ONNXRuntime, so probing
  ORT here would fail a perfectly working CPU-ORT/CUDA-CTranslate2 setup.
  ``get_cuda_device_count`` itself is imported in ``ctranslate2/__init__.py``
  under a silently-passing ``except ImportError``, so it can legitimately be
  absent from a given build; any failure to call it is treated as "no CUDA".
* OCR / ONNXRuntime -- ``"CUDAExecutionProvider" in
  onnxruntime.get_available_providers()``.

Both probes are only meant to run when the caller's configured device is
``"cuda"`` -- callers must guard the call themselves so a ``"cpu"`` config
never imports or touches a CUDA symbol. See ``asr/whisper.py:_ensure_loaded``
and ``ocr/rapid_ocr.py:_ensure_loaded`` for the call sites.

Scope: these probes detect an absent CUDA *runtime*. They do not detect
cuDNN sub-library resolution failures (the most likely Windows failure mode),
which stay ``logger.debug``-only in ``asr/whisper.py``. A box with CUDA but
broken cuDNN still reaches a raw CTranslate2 error past this check.
"""

from __future__ import annotations

import ctranslate2
import onnxruntime

from panoscribe.errors import PanoScribeError

_REMEDY = (
    "No CUDA-capable device was found. Run on CPU instead: set "
    "PANO_WHISPER_DEVICE=cpu and PANO_WHISPER_COMPUTE_TYPE=int8 for ASR, "
    "and PANO_OCR_DEVICE=cpu for OCR. See docs/troubleshooting.md#cuda-not-found "
    "for details."
)


def require_cuda_for_asr() -> None:
    """Raise :class:`PanoScribeError` if CTranslate2 reports no CUDA device.

    Callers must only invoke this when ``whisper_device == "cuda"``.
    """
    try:
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        has_cuda = False
    if not has_cuda:
        raise PanoScribeError(f"ASR (CTranslate2): {_REMEDY}")


def require_cuda_for_ocr() -> None:
    """Raise :class:`PanoScribeError` if ONNXRuntime reports no CUDA provider.

    Callers must only invoke this when ``ocr_device == "cuda"``.
    """
    if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
        raise PanoScribeError(f"OCR (ONNXRuntime): {_REMEDY}")
