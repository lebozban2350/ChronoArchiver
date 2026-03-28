"""Pytest configuration: ensure `src/` is on path (mirrors [tool.pytest.ini_options] pythonpath)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def test_files_dir(repo_root: Path) -> Path:
    """Read-only workspace fixtures (do not delete or modify). Skips on CI when ``Test_Files/`` is absent."""
    p = repo_root / "Test_Files"
    if not p.is_dir():
        pytest.skip(
            "Test_Files/ not in checkout (optional local media; clone with media or run integration tests locally)"
        )
    return p


@pytest.fixture(scope="session")
def sample_photo_jpg(test_files_dir: Path) -> Path:
    """One JPEG from ``Test_Files/Test_Photos``."""
    photos = test_files_dir / "Test_Photos"
    for pat in ("*.jpg", "*.JPG"):
        found = list(photos.glob(pat))
        if found:
            return found[0]
    pytest.skip("No .jpg under Test_Files/Test_Photos")


@pytest.fixture(scope="session")
def sample_video_path(test_files_dir: Path) -> Path:
    """One video file from ``Test_Files/Test_Videos``."""
    vdir = test_files_dir / "Test_Videos"
    for pat in ("*.mp4", "*.MP4", "*.mov", "*.MOV", "*.mkv"):
        found = list(vdir.glob(pat))
        if found:
            return found[0]
    pytest.skip("No video under Test_Files/Test_Videos")
