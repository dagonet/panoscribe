"""Video acquisition — local passthrough or yt-dlp download."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from panoscribe.errors import PanoScribeError

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Rank H.264 first: OpenCV's bundled FFmpeg only has a hardware AV1 decoder, so
# an AV1 download yields zero OCR frames on most machines (#189). With a limit,
# yt-dlp ranks codecs at or below h264 first and anything above (vp9, av01)
# after, so AV1 stays available as a last resort. No resolution cap.
_FORMAT_SORT: list[str] = ["vcodec:h264"]


def download_video(source: str, temp_dir: Path) -> Path:
    """Return a local path to the video referenced by ``source``.

    If ``source`` is an existing local file, it is returned unchanged.
    If it is an http(s) URL, yt-dlp downloads it into ``temp_dir`` and the
    resulting path is returned. Any yt-dlp failure — as well as an unrecognised
    source string — is raised as :class:`PanoScribeError` with a single-line
    message (no traceback chain) so the CLI can surface it cleanly.
    """
    if Path(source).is_file():
        logger.debug("Using local file passthrough: %s", source)
        return Path(source)

    if _URL_RE.match(source):
        temp_dir.mkdir(parents=True, exist_ok=True)
        ydl_opts = {
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "format_sort": list(_FORMAT_SORT),
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source, download=True)
                return Path(ydl.prepare_filename(info))
        except DownloadError as e:
            raise PanoScribeError(f"Download failed: {e}") from None

    raise PanoScribeError(f"Invalid source: {source!r} is neither a file nor an http(s) URL")
