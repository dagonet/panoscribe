"""Unit tests for panoscribe.device — CUDA availability probes.

Patch targets live at the import site:

* ``panoscribe.device.onnxruntime.get_available_providers``
* ``panoscribe.device.ctranslate2.get_cuda_device_count``
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from panoscribe.device import require_cuda_for_asr, require_cuda_for_ocr
from panoscribe.errors import PanoScribeError

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_require_cuda_for_ocr_passes_when_provider_present() -> None:
    with patch(
        "panoscribe.device.onnxruntime.get_available_providers",
        return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
    ):
        require_cuda_for_ocr()  # must not raise


def test_require_cuda_for_ocr_raises_when_provider_absent() -> None:
    with (
        patch(
            "panoscribe.device.onnxruntime.get_available_providers",
            return_value=["CPUExecutionProvider"],
        ),
        pytest.raises(PanoScribeError) as exc_info,
    ):
        require_cuda_for_ocr()

    message = str(exc_info.value)
    assert "PANO_WHISPER_DEVICE=cpu" in message
    assert "PANO_WHISPER_COMPUTE_TYPE=int8" in message
    assert "PANO_OCR_DEVICE=cpu" in message


def test_require_cuda_for_asr_passes_when_device_count_positive() -> None:
    with patch("panoscribe.device.ctranslate2.get_cuda_device_count", return_value=1):
        require_cuda_for_asr()  # must not raise


def test_require_cuda_for_asr_raises_when_device_count_zero() -> None:
    with (
        patch("panoscribe.device.ctranslate2.get_cuda_device_count", return_value=0),
        pytest.raises(PanoScribeError) as exc_info,
    ):
        require_cuda_for_asr()

    message = str(exc_info.value)
    assert "PANO_WHISPER_DEVICE=cpu" in message
    assert "PANO_WHISPER_COMPUTE_TYPE=int8" in message
    assert "PANO_OCR_DEVICE=cpu" in message


def test_error_message_troubleshooting_link_resolves() -> None:
    """The remedy points at docs/troubleshooting.md#cuda-not-found -- assert
    the referenced file and anchor target actually exist, so a future rename
    or move of that doc doesn't silently turn the user-facing error into a
    dead link."""
    with (
        patch(
            "panoscribe.device.onnxruntime.get_available_providers",
            return_value=["CPUExecutionProvider"],
        ),
        pytest.raises(PanoScribeError) as exc_info,
    ):
        require_cuda_for_ocr()

    message = str(exc_info.value)
    assert "docs/troubleshooting.md" in message

    troubleshooting_doc = _REPO_ROOT / "docs" / "troubleshooting.md"
    assert troubleshooting_doc.is_file()

    contents = troubleshooting_doc.read_text(encoding="utf-8")
    assert "## CUDA not found" in contents, (
        "the '#cuda-not-found' anchor referenced in the remedy message is "
        "produced by a '## CUDA not found' heading -- the heading text "
        "moved or was renamed"
    )


def test_require_cuda_for_asr_treats_probe_failure_as_no_cuda() -> None:
    """``get_cuda_device_count`` can legitimately be absent (silently-passing
    ``except ImportError`` in ``ctranslate2/__init__.py``); any failure to
    call it must be treated as "no CUDA", not propagated."""
    with (
        patch(
            "panoscribe.device.ctranslate2.get_cuda_device_count",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(PanoScribeError),
    ):
        require_cuda_for_asr()
