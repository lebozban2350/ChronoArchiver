"""
Sanity checks for workspace `Test_Files/` (read-only).

Do not delete or modify files under Test_Files/; these tests only assert presence and readability.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_test_photos_and_videos_exist(test_files_dir: Path):
    photos = test_files_dir / "Test_Photos"
    videos = test_files_dir / "Test_Videos"
    assert photos.is_dir(), f"Expected {photos} — add Test_Files/Test_Photos or fix path"
    assert videos.is_dir(), f"Expected {videos}"


def test_test_photos_has_image_files(test_files_dir: Path):
    photos = test_files_dir / "Test_Photos"
    jpgs = list(photos.glob("*.jpg")) + list(photos.glob("*.JPG"))
    webps = list(photos.glob("*.webp"))
    assert len(jpgs) + len(webps) >= 1, "Need at least one .jpg or .webp under Test_Photos"


def test_test_videos_has_media(test_files_dir: Path):
    videos = test_files_dir / "Test_Videos"
    any_video = (
        list(videos.glob("*.mp4"))
        + list(videos.glob("*.MP4"))
        + list(videos.glob("*.mov"))
        + list(videos.glob("*.MOV"))
    )
    assert len(any_video) >= 1, "Need at least one video under Test_Videos"


def test_sample_files_are_readable(test_files_dir: Path):
    """First bytes readable (non-destructive)."""
    photos = test_files_dir / "Test_Photos"
    first = next(iter(photos.glob("*.jpg")), None) or next(iter(photos.glob("*.JPG")), None)
    if first is None:
        first = next(iter(photos.glob("*.webp")), None)
    assert first is not None and first.is_file()
    assert first.read_bytes()[:4] != b""

    vdir = test_files_dir / "Test_Videos"
    vf = next(iter(vdir.iterdir()), None)
    assert vf is not None and vf.is_file()
    assert len(vf.read_bytes()[:64]) > 0
