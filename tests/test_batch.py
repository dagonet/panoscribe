"""Unit tests for ``panoscribe.batch`` (Sprint 5.4).

Pure data + IO — these tests do NOT spin up the transcribe pipeline. The CLI
end-to-end coverage lives in ``test_cli.py`` under the ``transcribe-many``
group.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from panoscribe.batch import (
    BatchItem,
    BatchState,
    _video_id_from_url,
    compute_output_path,
    load_state,
    parse_url_list,
    reconcile,
    save_state,
)
from panoscribe.cli import app
from panoscribe.errors import PanoScribeError

# ── parse_url_list ────────────────────────────────────────────────────────


def test_parse_url_list_strips_blanks_and_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "urls.txt"
    p.write_text(
        "  https://a/1  \n\nhttps://b/2\n    \nhttps://c/3\n",
        encoding="utf-8",
    )
    assert parse_url_list(p) == ["https://a/1", "https://b/2", "https://c/3"]


def test_parse_url_list_handles_bom_and_crlf(tmp_path: Path) -> None:
    """Notepad-on-Windows writes UTF-8 BOM + CRLF; both must be transparent."""
    p = tmp_path / "urls.txt"
    # Explicit BOM bytes + CRLF line separators.
    p.write_bytes(b"\xef\xbb\xbfhttps://a/1\r\nhttps://b/2\r\n")
    assert parse_url_list(p) == ["https://a/1", "https://b/2"]


def test_parse_url_list_handles_local_paths(tmp_path: Path) -> None:
    p = tmp_path / "urls.txt"
    p.write_text("/home/user/clip.mp4\nC:\\videos\\clip2.mkv\n", encoding="utf-8")
    assert parse_url_list(p) == ["/home/user/clip.mp4", "C:\\videos\\clip2.mkv"]


# ── compute_output_path ───────────────────────────────────────────────────


def test_compute_output_path_url(tmp_path: Path) -> None:
    """yt-dlp metadata returns a video ID; stem is that ID."""
    with patch("panoscribe.batch._video_id_from_url", return_value="abc123"):
        out = compute_output_path("https://example.com/v/abc123", tmp_path, ".md", set())
    assert out == tmp_path / "abc123.md"


def test_compute_output_path_local_file(tmp_path: Path) -> None:
    out = compute_output_path("/home/u/clip.mp4", tmp_path, ".json", set())
    assert out == tmp_path / "clip.json"


def test_compute_output_path_video_id_extraction_fails_uses_hash(tmp_path: Path) -> None:
    """When yt-dlp can't extract an ID, the stem is the 12-char sha256 hex prefix."""
    url = "https://example.com/some/weird/page"
    with patch("panoscribe.batch._video_id_from_url", return_value=None):
        out = compute_output_path(url, tmp_path, ".md", set())
    stem = out.stem
    # Expect 12 hex chars.
    assert len(stem) == 12
    assert all(c in "0123456789abcdef" for c in stem)


def test_compute_output_path_truncates_long_stems(tmp_path: Path) -> None:
    long_id = "x" * 300
    with patch("panoscribe.batch._video_id_from_url", return_value=long_id):
        out = compute_output_path("https://example.com/long", tmp_path, ".md", set())
    assert len(out.stem) <= 200


def test_compute_output_path_collision(tmp_path: Path) -> None:
    """Second item with the same stem gets a (2) suffix."""
    taken: set[Path] = set()
    with patch("panoscribe.batch._video_id_from_url", return_value="abc"):
        first = compute_output_path("https://x/1", tmp_path, ".md", taken)
    taken.add(first)
    with patch("panoscribe.batch._video_id_from_url", return_value="abc"):
        second = compute_output_path("https://x/2", tmp_path, ".md", taken)
    assert first == tmp_path / "abc.md"
    assert second == tmp_path / "abc(2).md"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only case-fold check")
def test_compute_output_path_collision_case_insensitive_on_windows(tmp_path: Path) -> None:
    """``Foo.md`` already taken; new ``foo`` stem collides on Windows."""
    taken: set[Path] = {tmp_path / "Foo.md"}
    out = compute_output_path("/data/foo.mp4", tmp_path, ".md", taken)
    # On Windows, "foo.md" collides with "Foo.md" → suffix added.
    assert out == tmp_path / "foo(2).md"


def test_compute_output_path_resume_honors_existing(tmp_path: Path) -> None:
    """Resume rule: if a state item already carries an output_path, callers do
    NOT call compute_output_path for it. This test confirms compute is only
    invoked for items lacking an output_path — verified by checking that an
    existing path in ``taken`` makes the function pick a new name (i.e. it is
    NOT recomputed for the prior item; only new items see compute_output_path).
    """
    existing = tmp_path / "abc.md"
    taken = {existing}
    with patch("panoscribe.batch._video_id_from_url", return_value="abc"):
        # New item with the same derived stem must skip the existing path.
        new_path = compute_output_path("https://other", tmp_path, ".md", taken)
    assert new_path != existing
    assert new_path == tmp_path / "abc(2).md"


# ── State round-trip and load semantics ───────────────────────────────────


def _sample_state(tmp_path: Path) -> BatchState:
    return BatchState(
        version=1,
        started_at=datetime(2026, 4, 30, 15, 0, 0, tzinfo=UTC),
        input_file=tmp_path / "urls.txt",
        output_dir=tmp_path / "out",
        format="md",
        items=[
            BatchItem(
                source="https://a/1",
                status="done",
                output_path=tmp_path / "out" / "a1.md",
            ),
            BatchItem(source="https://b/2", status="failed", error="boom"),
            BatchItem(source="https://c/3", status="pending"),
        ],
    )


def test_state_round_trip(tmp_path: Path) -> None:
    state = _sample_state(tmp_path)
    sf = tmp_path / ".panoscribe-batch-state.json"
    save_state(state, sf)
    loaded = load_state(sf)
    assert loaded is not None
    assert loaded.version == 1
    assert loaded.format == "md"
    assert [it.source for it in loaded.items] == ["https://a/1", "https://b/2", "https://c/3"]
    assert [it.status for it in loaded.items] == ["done", "failed", "pending"]
    assert loaded.items[0].output_path == tmp_path / "out" / "a1.md"
    assert loaded.items[1].error == "boom"
    assert loaded.started_at == state.started_at


def test_state_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_state(tmp_path / "no-such-file.json") is None


def test_state_load_version_mismatch_returns_none(tmp_path: Path, caplog) -> None:
    sf = tmp_path / "state.json"
    sf.write_text(json.dumps({"version": 99, "items": []}), encoding="utf-8")
    import logging

    with caplog.at_level(logging.WARNING, logger="panoscribe.batch"):
        assert load_state(sf) is None
    assert any("version" in r.message for r in caplog.records)


def test_state_load_corrupt_returns_none(tmp_path: Path, caplog) -> None:
    """Truncated / non-JSON content yields None plus a WARNING (not an exception)."""
    sf = tmp_path / "state.json"
    sf.write_text("{not json at all", encoding="utf-8")
    import logging

    with caplog.at_level(logging.WARNING, logger="panoscribe.batch"):
        result = load_state(sf)
    assert result is None
    assert any("unreadable" in r.message for r in caplog.records)


def test_save_state_atomic(tmp_path: Path) -> None:
    """Simulate ``os.replace`` raising mid-write; the original file must be
    untouched and the temp file must be cleaned up.
    """
    sf = tmp_path / "state.json"
    # Seed an existing valid state so we can confirm it survives the failure.
    original = BatchState(format="md", items=[BatchItem(source="x")])
    save_state(original, sf)
    pre_bytes = sf.read_bytes()

    new_state = BatchState(format="srt", items=[BatchItem(source="y")])

    def _boom(*_a, **_kw):
        raise OSError("disk full")

    with patch("panoscribe.batch.os.replace", side_effect=_boom), pytest.raises(OSError):
        save_state(new_state, sf)

    # Original file untouched.
    assert sf.read_bytes() == pre_bytes
    # No leftover temp files in the parent dir.
    leftovers = list(tmp_path.glob(".panoscribe-batch-state.*.tmp"))
    assert leftovers == []


def test_save_state_uses_same_volume_tempfile(tmp_path: Path, monkeypatch) -> None:
    """``mkstemp`` must be called with ``dir=path.parent`` to keep the temp
    on the same volume as the target (Windows ``os.replace`` constraint).
    """
    import panoscribe.batch as batch_mod

    sf = tmp_path / "state.json"
    captured: dict[str, str] = {}
    real_mkstemp = batch_mod.tempfile.mkstemp

    def _spy_mkstemp(*args, **kwargs):
        captured["dir"] = kwargs.get("dir", "")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(batch_mod.tempfile, "mkstemp", _spy_mkstemp)

    save_state(BatchState(items=[BatchItem(source="x")]), sf)

    assert captured["dir"] == str(sf.parent)


# ── version / shape error paths in load_state ──────────────────────────────


@pytest.mark.parametrize(
    "version_value",
    [
        "abc",  # ValueError from int("abc")
        [1, 2],  # TypeError from int([1, 2])
    ],
)
def test_state_load_non_integer_version_returns_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, version_value: object
) -> None:
    """version field that int() rejects -> None + WARNING."""
    sf = tmp_path / "state.json"
    sf.write_text(json.dumps({"version": version_value, "items": []}), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="panoscribe.batch"):
        assert load_state(sf) is None
    assert any("non-integer version" in r.message for r in caplog.records)


def test_state_load_shape_error_returns_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid version but _state_from_jsonable raises (missing 'source') -> None."""
    sf = tmp_path / "state.json"
    data = {
        "version": 1,
        "started_at": "2026-01-01T00:00:00+00:00",
        "input_file": "x",
        "output_dir": "x",
        "items": [{"status": "pending"}],  # missing "source" -> KeyError
    }
    sf.write_text(json.dumps(data), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="panoscribe.batch"):
        assert load_state(sf) is None
    assert any("unexpected shape" in r.message for r in caplog.records)


# ── _video_id_from_url ────────────────────────────────────────────────────


def test_video_id_from_url_success() -> None:
    """yt-dlp extracts a valid video ID -> returns it."""
    mock_info = {"id": "abc123"}
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = mock_info
        result = _video_id_from_url("https://example.com/v/abc")
    assert result == "abc123"


def test_video_id_from_url_info_none() -> None:
    """extract_info returns None -> returns None."""
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = None
        result = _video_id_from_url("https://example.com/v/abc")
    assert result is None


def test_video_id_from_url_empty_id_returns_none() -> None:
    """info has empty string id -> returns None."""
    mock_info = {"id": ""}
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = mock_info
        result = _video_id_from_url("https://example.com/v/abc")
    assert result is None


def test_video_id_from_url_download_error_returns_none() -> None:
    """DownloadError during extraction -> returns None."""
    from yt_dlp.utils import DownloadError

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("err")
        result = _video_id_from_url("https://example.com/v/abc")
    assert result is None


def test_video_id_from_url_generic_exception_returns_none() -> None:
    """Non-DownloadError exception -> returns None (logged at DEBUG)."""
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = ValueError("bad")
        result = _video_id_from_url("https://example.com/v/abc")
    assert result is None


# ── reconcile ─────────────────────────────────────────────────────────────


def test_reconcile_drops_orphan_items_not_in_list(tmp_path: Path) -> None:
    state = BatchState(
        items=[
            BatchItem(source="A", status="done"),
            BatchItem(source="B", status="failed"),
            BatchItem(source="C", status="pending"),
        ]
    )
    out = reconcile(state, ["B", "C"])
    assert [it.source for it in out.items] == ["B", "C"]


def test_reconcile_appends_new_urls_as_pending() -> None:
    state = BatchState(items=[BatchItem(source="A", status="done")])
    out = reconcile(state, ["A", "B", "C"])
    sources = [it.source for it in out.items]
    statuses = [it.status for it in out.items]
    assert sources == ["A", "B", "C"]
    assert statuses == ["done", "pending", "pending"]


def test_reconcile_preserves_done_status_for_existing_urls() -> None:
    state = BatchState(
        items=[
            BatchItem(source="A", status="done"),
            BatchItem(source="B", status="failed", error="x"),
        ]
    )
    out = reconcile(state, ["A", "B"])
    a, b = out.items
    assert a.status == "done"
    assert b.status == "failed"
    assert b.error == "x"


def test_reconcile_none_state_returns_all_pending() -> None:
    out = reconcile(None, ["A", "B"])
    assert all(it.status == "pending" for it in out.items)
    assert [it.source for it in out.items] == ["A", "B"]


# ── transcribe-many failure reporting (#184) ──────────────────────────────


def _write_batch_urls(tmp_path: Path, urls: list[str]) -> Path:
    p = tmp_path / "urls.txt"
    p.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return p


def _fake_compute_output_path(source: str, output_dir: Path, ext: str, taken: set[Path]) -> Path:
    stem = source.rstrip("/").rsplit("/", 1)[-1]
    return output_dir / f"{stem}{ext}"


@pytest.fixture
def clean_batch_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate a CLI batch run from the developer's shell and ``.env``.

    Drops every ``PANO_*`` variable and runs from an empty directory, so
    neither the environment nor a ``.env`` in the repo root can change the
    backend or any other setting.
    """
    for name in [k for k in os.environ if k.startswith("PANO_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("PANO_TEMP_DIR", str(tmp_path / "omni"))
    # The default OCR device is cuda, which the #191 pre-check probes; pin cpu so these
    # tests do not depend on the host's onnxruntime listing a CUDA provider.
    monkeypatch.setenv("PANO_OCR_DEVICE", "cpu")
    monkeypatch.chdir(tmp_path)


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_prints_failure_reason(tmp_path: Path) -> None:
    """A failed item's reason and the final tally reach the console; exit stays 0."""
    urls_file = _write_batch_urls(tmp_path, ["https://a/1", "https://a/2"])
    out_dir = tmp_path / "out"

    def _fake_proc(source: str, *_a, **_kw) -> None:
        if source == "https://a/1":
            raise PanoScribeError("[Errno 2] no such file: x")

    with (
        patch("panoscribe.pipeline.process_single_video", side_effect=_fake_proc),
        patch("panoscribe.cli.compute_output_path", side_effect=_fake_compute_output_path),
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            ["transcribe-many", str(urls_file), "--output-dir", str(out_dir), "--format", "md"],
        )

    assert result.exit_code == 0, result.output
    failed_lines = [line for line in result.output.splitlines() if "failed:" in line]
    assert len(failed_lines) == 1
    assert "https://a/1" in failed_lines[0]
    # Brackets must survive rich markup parsing.
    assert "[Errno 2] no such file: x" in failed_lines[0]
    assert "1 done, 1 failed, 0 pending" in result.output


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_all_ok_prints_summary_only(tmp_path: Path) -> None:
    """No failures: no error line, a clean tally, and the state-file path."""
    urls_file = _write_batch_urls(tmp_path, ["https://a/1", "https://a/2"])
    out_dir = tmp_path / "out"

    with (
        patch("panoscribe.pipeline.process_single_video"),
        patch("panoscribe.cli.compute_output_path", side_effect=_fake_compute_output_path),
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            ["transcribe-many", str(urls_file), "--output-dir", str(out_dir), "--format", "md"],
        )

    assert result.exit_code == 0, result.output
    assert "failed:" not in result.output
    assert "2 done, 0 failed, 0 pending" in result.output
    assert str(out_dir / ".panoscribe-batch-state.json") in result.output


# ── transcribe-many checks speech settings before any download (#183) ─────


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_stops_before_first_download_on_bad_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """Misconfigured remote speech: message once, exit 1, no download, items stay pending."""
    monkeypatch.setenv("PANO_ASR_BACKEND", "remote")
    monkeypatch.setenv("PANO_ASR_REMOTE_BASE_URL", "https://asr.example.test/v1")
    urls_file = _write_batch_urls(tmp_path, ["https://a/1", "https://a/2"])
    out_dir = tmp_path / "out"

    with (
        patch("panoscribe.pipeline.download_video") as download_video,
        patch("panoscribe.cli.compute_output_path", side_effect=_fake_compute_output_path),
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            ["transcribe-many", str(urls_file), "--output-dir", str(out_dir), "--format", "md"],
        )

    assert result.exit_code == 1, result.output
    download_video.assert_not_called()
    assert result.output.count("PANO_ASR_REMOTE_MODEL") == 1
    assert "PANO_ASR_REMOTE_MODEL" in result.stderr  # fatal errors go to stderr
    assert "failed:" not in result.output
    assert "done," not in result.output  # no batch summary on this path
    state = json.loads((out_dir / ".panoscribe-batch-state.json").read_text(encoding="utf-8"))
    assert [it["status"] for it in state["items"]] == ["pending", "pending"]


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_resume_of_finished_batch_needs_no_speech_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """Nothing pending or failed: the engine is never built, so bad settings don't matter."""
    monkeypatch.setenv("PANO_ASR_BACKEND", "remote")
    monkeypatch.setenv("PANO_ASR_REMOTE_BASE_URL", "https://asr.example.test/v1")
    urls_file = _write_batch_urls(tmp_path, ["https://a/1", "https://a/2"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = BatchState(
        version=1,
        started_at=datetime.now(UTC),
        input_file=urls_file.resolve(),
        output_dir=out_dir.resolve(),
        format="md",
        items=[
            BatchItem(source=src, status="done", output_path=out_dir / f"{i}.md")
            for i, src in enumerate(["https://a/1", "https://a/2"], start=1)
        ],
    )
    save_state(state, out_dir / ".panoscribe-batch-state.json")

    with (
        patch("panoscribe.pipeline._build_asr_engine") as build,
        patch("panoscribe.pipeline.process_single_video") as process,
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            ["transcribe-many", str(urls_file), "--output-dir", str(out_dir), "--format", "md"],
        )

    assert result.exit_code == 0, result.output
    build.assert_not_called()
    process.assert_not_called()
    assert "2 done, 0 failed, 0 pending" in result.output


# ── transcribe-many checks OCR settings before any download (#191) ────────


def _run_many_with_bad_ocr(tmp_path: Path, monkeypatch, *extra_args: str):
    monkeypatch.setenv("PANO_OCR_REC_MODEL_TYPE", "medium")  # v6-only size on the classic set
    urls_file = _write_batch_urls(tmp_path, ["https://a/1", "https://a/2"])
    out_dir = tmp_path / "out"

    with (
        patch("panoscribe.pipeline.download_video", side_effect=PanoScribeError("dl")) as dl,
        patch("panoscribe.pipeline.WhisperTranscriber"),
        patch("panoscribe.cli.compute_output_path", side_effect=_fake_compute_output_path),
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            [
                "transcribe-many",
                str(urls_file),
                "--output-dir",
                str(out_dir),
                "--format",
                "md",
                *extra_args,
            ],
        )
    return result, dl, out_dir


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_stops_before_first_download_on_bad_ocr_settings(
    tmp_path: Path, monkeypatch
) -> None:
    result, download_video, out_dir = _run_many_with_bad_ocr(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.output
    download_video.assert_not_called()
    assert result.output.count("PANO_OCR_REC_MODEL_TYPE") == 1
    assert "PANO_OCR_REC_MODEL_TYPE" in result.stderr
    assert "failed:" not in result.output
    assert "done," not in result.output
    state = json.loads((out_dir / ".panoscribe-batch-state.json").read_text(encoding="utf-8"))
    assert [it["status"] for it in state["items"]] == ["pending", "pending"]


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_no_ocr_does_not_check_ocr_settings(tmp_path: Path, monkeypatch) -> None:
    result, download_video, _ = _run_many_with_bad_ocr(tmp_path, monkeypatch, "--no-ocr")

    assert "PANO_OCR_REC_MODEL_TYPE" not in result.output
    assert download_video.call_count == 2  # the run proceeded to the (mocked) downloads


@pytest.mark.usefixtures("clean_batch_env")
def test_transcribe_many_resume_of_finished_batch_needs_no_ocr_settings(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PANO_OCR_REC_MODEL_TYPE", "medium")
    urls_file = _write_batch_urls(tmp_path, ["https://a/1"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = BatchState(
        version=1,
        started_at=datetime.now(UTC),
        input_file=urls_file.resolve(),
        output_dir=out_dir.resolve(),
        format="md",
        items=[BatchItem(source="https://a/1", status="done", output_path=out_dir / "1.md")],
    )
    save_state(state, out_dir / ".panoscribe-batch-state.json")

    with (
        patch("panoscribe.pipeline.validate_ocr_settings") as check,
        patch("panoscribe.cli.expand_url_list", side_effect=lambda urls: urls),
    ):
        result = CliRunner().invoke(
            app,
            ["transcribe-many", str(urls_file), "--output-dir", str(out_dir), "--format", "md"],
        )

    assert result.exit_code == 0, result.output
    check.assert_not_called()
