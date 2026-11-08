"""Tests for the video downloader.

Patch :class:`yt_dlp.YoutubeDL` at its *import site* within
``panoscribe.acquire.downloader``. Patching at ``yt_dlp.YoutubeDL`` leaves the
already-bound alias inside the downloader module untouched and would execute
the real class.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from panoscribe.acquire.downloader import _FORMAT_SELECTOR, download_video
from panoscribe.errors import PanoScribeError


def test_local_file_passthrough(silence_wav_path: Path, tmp_path: Path) -> None:
    """Local files are returned unchanged; YoutubeDL is never instantiated."""
    with patch("panoscribe.acquire.downloader.YoutubeDL") as mock_ydl:
        result = download_video(str(silence_wav_path), tmp_path / "dl")

    assert result == silence_wav_path
    mock_ydl.assert_not_called()


def test_url_download(tmp_path: Path) -> None:
    """HTTP URLs are passed to yt-dlp and the prepared filename is returned."""
    with patch("panoscribe.acquire.downloader.YoutubeDL") as mock_ydl:
        instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = instance
        instance.extract_info.return_value = {"id": "abc", "ext": "mp4"}
        instance.prepare_filename.return_value = "/tmp/omni/abc.mp4"

        result = download_video("https://example.com/v/abc", tmp_path / "dl")

    assert result == Path("/tmp/omni/abc.mp4")
    instance.extract_info.assert_called_once_with("https://example.com/v/abc", download=True)


def test_invalid_source_raises_panoscribe_error(tmp_path: Path) -> None:
    """Unrecognised sources raise PanoScribeError so the CLI surfaces one line."""
    with pytest.raises(PanoScribeError, match="neither a file nor an http"):
        download_video("not a url or file", tmp_path / "dl")


def test_download_error_wrapped_as_panoscribe_error(tmp_path: Path) -> None:
    """yt-dlp DownloadError is surfaced as a clean single-line PanoScribeError."""
    with patch("panoscribe.acquire.downloader.YoutubeDL") as mock_ydl:
        instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = instance
        instance.extract_info.side_effect = DownloadError("blocked")

        with pytest.raises(PanoScribeError) as exc_info:
            download_video("https://example.com/v/abc", tmp_path / "dl")

    assert "Download failed" in str(exc_info.value)
    assert "blocked" in str(exc_info.value)
    # ``raise ... from None`` severs the explicit cause chain.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_download_passes_av1_avoiding_format_selector(tmp_path: Path) -> None:
    """The download asks yt-dlp to skip AV1 when another codec exists (OpenCV, #189)."""
    with patch("panoscribe.acquire.downloader.YoutubeDL") as mock_ydl:
        instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = instance
        instance.extract_info.return_value = {"id": "abc", "ext": "mp4"}
        instance.prepare_filename.return_value = "/tmp/omni/abc.mp4"

        download_video("https://example.com/v/abc", tmp_path / "dl")

    opts = mock_ydl.call_args.args[0]
    assert opts["format"] == "bv*[vcodec!^=av01]+ba/b[vcodec!^=av01]/bv*+ba/b"
    # yt-dlp's default sort (resolution first) is kept: no format_sort, no resolution cap.
    assert "format_sort" not in opts


def _fake_info(*video_codecs: tuple[str, int]) -> dict[str, object]:
    """Synthetic yt-dlp info dict: one video-only format per ``(vcodec, height)`` + audio."""
    formats: list[dict[str, object]] = [
        {
            "format_id": f"v-{vcodec[:4]}-{height}",
            "url": f"https://example.test/{vcodec}-{height}",
            "ext": "mp4" if vcodec.startswith(("avc1", "av01")) else "webm",
            "vcodec": vcodec,
            "acodec": "none",
            "height": height,
            "width": height * 16 // 9,
            "tbr": float(height),
            "protocol": "https",
        }
        for vcodec, height in video_codecs
    ]
    formats.append(
        {
            "format_id": "audio",
            "url": "https://example.test/audio",
            "ext": "m4a",
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "abr": 128.0,
            "protocol": "https",
        }
    )
    return {
        "id": "abc",
        "title": "t",
        "extractor": "generic",
        "extractor_key": "Generic",
        "webpage_url": "https://example.test/watch",
        "formats": formats,
    }


# yt-dlp's own default selector whenever ffmpeg can merge; the baseline before #189.
_DEFAULT_SELECTOR = "bv*+ba/b"


def _picked_formats(info: dict[str, object], selector: str) -> str:
    """Run the real yt-dlp sorter + selector offline; return the chosen format id(s).

    Spelling the selector out keeps the test independent of the host having ffmpeg.
    The sorter is yt-dlp's default one (resolution first): panoscribe sets no format_sort.
    """
    opts = {"format": selector, "quiet": True, "no_warnings": True}
    with YoutubeDL(opts) as ydl:
        result = ydl.process_ie_result(info, download=False)
    requested = result.get("requested_formats") or [result]
    return "+".join(str(f["format_id"]) for f in requested)


def _picked_video_format(info: dict[str, object]) -> str:
    """The video format id the panoscribe selector picks."""
    return _picked_formats(info, _FORMAT_SELECTOR).split("+")[0]


def test_selector_keeps_resolution_first_and_skips_higher_resolution_av1() -> None:
    """A lower-resolution H.264 does not beat a higher-resolution VP9 (small text needs pixels)."""
    info = _fake_info(("avc1.640028", 360), ("vp9", 1080), ("av01.0.12M.08", 1080))

    assert _picked_video_format(info) == "v-vp9-1080"


def test_selector_picks_h264_when_it_is_the_best_non_av1() -> None:
    info = _fake_info(("avc1.640028", 1080), ("av01.0.12M.08", 1080))

    assert _picked_video_format(info) == "v-avc1-1080"


def test_selector_falls_back_to_av1_when_nothing_else_exists() -> None:
    info = _fake_info(("av01.0.12M.08", 1080))

    assert _picked_video_format(info) == "v-av01-1080"


def test_selector_matches_the_default_when_no_av1_is_offered() -> None:
    info = _fake_info(("avc1.640028", 360), ("vp9", 1080))

    assert _picked_formats(info, _FORMAT_SELECTOR) == _picked_formats(info, _DEFAULT_SELECTOR)


def test_selector_matches_the_default_for_formats_without_codec_info() -> None:
    """yt-dlp's ``vcodec!^=av01`` filter drops formats with no ``vcodec``; the last
    alternative (the old default) must then restore today's choice."""
    formats = [
        {"format_id": f"f{h}", "url": f"https://example.test/{h}", "ext": "mp4", "height": h}
        for h in (360, 1080)
    ]
    info = {
        "id": "abc",
        "title": "t",
        "extractor": "generic",
        "extractor_key": "Generic",
        "webpage_url": "https://example.test/watch",
        "formats": formats,
    }

    picked = _picked_formats(info, _FORMAT_SELECTOR)

    assert picked == _picked_formats(info, _DEFAULT_SELECTOR)
    assert picked == "f1080"
