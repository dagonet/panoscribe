"""Unit tests for omniscribe.device — CUDA availability probes.

Patch targets live at the import site:

* ``omniscribe.device.onnxruntime.get_available_providers``
* ``omniscribe.device.ctranslate2.get_cuda_device_count``
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from omniscribe.device import require_cuda_for_asr, require_cuda_for_ocr
from omniscribe.errors import OmniScribeError


def test_require_cuda_for_ocr_passes_when_provider_present() -> None:
    with patch(
        "omniscribe.device.onnxruntime.get_available_providers",
        return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
    ):
        require_cuda_for_ocr()  # must not raise


def test_require_cuda_for_ocr_raises_when_provider_absent() -> None:
    with (
        patch(
            "omniscribe.device.onnxruntime.get_available_providers",
            return_value=["CPUExecutionProvider"],
        ),
        pytest.raises(OmniScribeError) as exc_info,
    ):
        require_cuda_for_ocr()

    message = str(exc_info.value)
    assert "OMNI_WHISPER_DEVICE=cpu" in message
    assert "OMNI_WHISPER_COMPUTE_TYPE=int8" in message
    assert "OMNI_OCR_DEVICE=cpu" in message


def test_require_cuda_for_asr_passes_when_device_count_positive() -> None:
    with patch("omniscribe.device.ctranslate2.get_cuda_device_count", return_value=1):
        require_cuda_for_asr()  # must not raise


def test_require_cuda_for_asr_raises_when_device_count_zero() -> None:
    with (
        patch("omniscribe.device.ctranslate2.get_cuda_device_count", return_value=0),
        pytest.raises(OmniScribeError) as exc_info,
    ):
        require_cuda_for_asr()

    message = str(exc_info.value)
    assert "OMNI_WHISPER_DEVICE=cpu" in message
    assert "OMNI_WHISPER_COMPUTE_TYPE=int8" in message
    assert "OMNI_OCR_DEVICE=cpu" in message


def test_require_cuda_for_asr_treats_probe_failure_as_no_cuda() -> None:
    """``get_cuda_device_count`` can legitimately be absent (silently-passing
    ``except ImportError`` in ``ctranslate2/__init__.py``); any failure to
    call it must be treated as "no CUDA", not propagated."""
    with (
        patch(
            "omniscribe.device.ctranslate2.get_cuda_device_count",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(OmniScribeError),
    ):
        require_cuda_for_asr()
