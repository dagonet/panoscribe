"""Unit tests for scripts/fetch_eval_samples.py — no network calls."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from panoscribe.acquire.photo import PhotoPost


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Point _FIXTURES_DIR to a temp dir for test isolation."""
    return tmp_path / "fixtures" / "eval"


def _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir):
    """Import scripts.fetch_eval_samples and override _FIXTURES_DIR."""
    import scripts.fetch_eval_samples as fetcher

    monkeypatch.setattr(fetcher, "_FIXTURES_DIR", fixtures_dir)
    return fetcher


def test_already_downloaded_skips(monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path) -> None:
    """When target files exist, the sample is skipped (no download call)."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    video_dir = fixtures_dir / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "sample-3.mp4").write_bytes(b"fake")

    mock_dl = MagicMock()
    monkeypatch.setattr(fetcher, "_download_video", mock_dl)
    monkeypatch.setattr(fetcher, "_download_photo", mock_dl)

    with patch.object(sys, "argv", ["fetch_eval_samples.py", "--sample", "3"]):
        fetcher.main()

    mock_dl.assert_not_called()


@pytest.mark.parametrize("sample_id", list(range(1, 17)))
def test_sample_filter(monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path, sample_id: int) -> None:
    """--sample N filters to exactly that sample; others skipped."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    called: list[int] = []

    def _track(sample: dict) -> None:
        called.append(sample["id"])

    monkeypatch.setattr(fetcher, "_download_photo", _track)
    monkeypatch.setattr(fetcher, "_download_video", _track)

    test_args = ["fetch_eval_samples.py", "--sample", str(sample_id)]
    with patch.object(sys, "argv", test_args):
        fetcher.main()

    assert called == [sample_id]


def test_photo_download_creates_slides_dir(
    monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path
) -> None:
    """_download_photo creates the target directory and moves images via shutil."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    fixtures_dir.mkdir(parents=True, exist_ok=True)

    post = PhotoPost(
        image_paths=(
            fixtures_dir / "img1.jpg",
            fixtures_dir / "img2.jpg",
        ),
        audio_path=None,
    )
    for p in post.image_paths:
        p.write_bytes(b"fake")

    sample = fetcher.SAMPLES[0]

    with patch("panoscribe.acquire.photo.download_photo_post", return_value=post):
        fetcher._download_photo(sample)

    dest = fixtures_dir / sample["target_dir"]
    assert dest.is_dir()
    assert (dest / "img1.jpg").exists()
    assert (dest / "img2.jpg").exists()


def test_photo_download_uses_shutil_move(
    monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path
) -> None:
    """_download_photo uses shutil.move (cross-drive-safe) not Path.rename."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    fixtures_dir.mkdir(parents=True, exist_ok=True)

    post = PhotoPost(
        image_paths=(fixtures_dir / "img.jpg",),
        audio_path=None,
    )
    post.image_paths[0].write_bytes(b"fake")

    sample = fetcher.SAMPLES[0]

    with (
        patch("panoscribe.acquire.photo.download_photo_post", return_value=post),
        patch("scripts.fetch_eval_samples.shutil.move") as mock_move,
    ):
        fetcher._download_photo(sample)

    dest = fixtures_dir / sample["target_dir"]
    mock_move.assert_called_once_with(str(post.image_paths[0]), str(dest / "img.jpg"))


def test_video_download_creates_parent_dir(
    monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path
) -> None:
    """_download_video creates the parent directory before downloading."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    sample = fetcher.SAMPLES[2]
    dest = fixtures_dir / sample["target_dir"]

    def _fake_download(url: str, temp_dir: Path) -> Path:
        dest.write_bytes(b"fake")
        return dest

    with patch(
        "panoscribe.acquire.downloader.download_video", side_effect=_fake_download
    ) as mock_dl:
        fetcher._download_video(sample)

    assert dest.parent.is_dir()
    mock_dl.assert_called_once_with(sample["url"], dest.parent)
    assert dest.exists()


def test_video_download_renames_on_mismatch(
    monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path
) -> None:
    """When download_video returns a path different from the target, shutil.move renames it."""
    fetcher = _import_and_patch_fixtures_dir(monkeypatch, fixtures_dir)

    sample = fetcher.SAMPLES[2]
    dest = fixtures_dir / sample["target_dir"]
    temp_path = fixtures_dir / "videos" / "abc123.mp4"  # yt-dlp naming

    with (
        patch("panoscribe.acquire.downloader.download_video", return_value=temp_path),
        patch("scripts.fetch_eval_samples.shutil.move") as mock_move,
    ):
        fetcher._download_video(sample)

    mock_move.assert_called_once_with(str(temp_path), str(dest))


_YOUTUBE_SHORTS: dict[int, str] = {
    7: "GJslGyaVJ-k",
    8: "nBS3iLeiByU",
    9: "XWQffp7qhRQ",
    10: "hjhaUcMtLX4",
    11: "7CKdfTeIoXo",
    12: "7lxiYXA_hwk",
    13: "-prSdejMkaI",
    14: "q9xy46qE94I",
    15: "3JbCfZGd2Sk",
    16: "JIeiriHBI2w",
}


def test_samples_include_youtube_ids_7_to_16() -> None:
    """Ids are unique; every design-table Short is a video sample at videos/sample-N.mp4."""
    import scripts.fetch_eval_samples as fetcher

    ids = [s["id"] for s in fetcher.SAMPLES]
    assert len(ids) == len(set(ids))

    by_id = {s["id"]: s for s in fetcher.SAMPLES}
    for sample_id, yt_id in _YOUTUBE_SHORTS.items():
        sample = by_id[sample_id]
        assert sample["url"] == f"https://www.youtube.com/shorts/{yt_id}"
        assert sample["type"] == "video"
        assert sample["target_dir"] == f"videos/sample-{sample_id}.mp4"
