"""Issue #164: non-UTF-8 console streams must degrade, not crash."""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pytest
import typer

from panoscribe.cli import _configure_console_streams, app
from panoscribe.output import TranscriptSegment
from tests.test_cli import _patched_pipeline


def _cp1252_stream(raw: io.BytesIO, errors: str = "strict") -> io.TextIOWrapper:
    return io.TextIOWrapper(raw, encoding="cp1252", errors=errors, write_through=True)


def test_transcribe_survives_cp1252_console_streams(tmp_path: Path, monkeypatch) -> None:
    """Redirected Windows stdout/stderr use cp1252 and cannot encode ``→``/emoji.

    Both the rich console ("Wrote N segment(s)") and the logging handler used
    to raise ``UnicodeEncodeError`` after the transcript was already written.
    """
    monkeypatch.setenv("PANO_TEMP_DIR", str(tmp_path / "omni"))
    monkeypatch.setenv("PANO_KEEP_TEMP_FILES", "true")
    monkeypatch.setenv("PANO_LOG_LEVEL", "INFO")  # the INFO log line must reach the handler
    output = tmp_path / "out.json"
    raw_out, raw_err = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(sys, "stdout", _cp1252_stream(raw_out))
    # Real Python stderr already uses backslashreplace; mirror that.
    monkeypatch.setattr(sys, "stderr", _cp1252_stream(raw_err, errors="backslashreplace"))
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers.clear()  # let main() install its own handler on the fake streams

    def noisy_transcribe(*_args: object, **_kwargs: object):
        logging.getLogger("panoscribe.test").info("auto-resolved: 'en' → en \U0001f600")
        return [TranscriptSegment(start=0.0, end=1.0, text="hi", language="en")], "en"

    dl, ex, wh, oc, lc, ac = _patched_pipeline(tmp_path)
    try:
        with dl, ex, wh as mock_whisper_cls, oc as mock_ocr_cls, lc, ac:
            mock_ocr_cls.return_value.extract.return_value = []
            mock_ocr_cls.return_value.last_frame_count = 0
            mock_whisper_cls.return_value.transcribe.side_effect = noisy_transcribe
            command = typer.main.get_command(app)
            with pytest.raises(SystemExit) as excinfo:
                command.main(["transcribe", "fake.mp4", "-o", str(output)], prog_name="panoscribe")
        assert excinfo.value.code in (0, None)
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

    assert output.is_file()
    stdout_text = raw_out.getvalue().decode("cp1252")
    stderr_text = raw_err.getvalue().decode("cp1252")
    assert "Wrote 1 segment(s)" in stdout_text
    assert "auto-resolved: 'en' \\u2192 en" in stdout_text
    assert "Logging error" not in stdout_text + stderr_text


def test_configure_console_streams_leaves_utf8_untouched(monkeypatch) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    _configure_console_streams()
    assert (out.errors, err.errors) == ("strict", "strict")


def test_configure_console_streams_only_touches_strict_streams(monkeypatch) -> None:
    strict = _cp1252_stream(io.BytesIO())
    chosen = _cp1252_stream(io.BytesIO(), errors="ignore")
    monkeypatch.setattr(sys, "stdout", strict)
    monkeypatch.setattr(sys, "stderr", chosen)
    _configure_console_streams()
    assert (strict.errors, chosen.errors) == ("backslashreplace", "ignore")


def test_configure_console_streams_tolerates_streams_without_reconfigure(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", None)
    _configure_console_streams()  # must not raise
