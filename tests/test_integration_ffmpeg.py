"""FFmpeg / ffprobe on ``Test_Files`` (skip if binaries missing)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _ffmpeg_exe() -> str | None:
    return shutil.which("ffmpeg")


def _ffprobe_exe() -> str | None:
    return shutil.which("ffprobe")


def test_ffmpeg_version():
    assert _ffmpeg_exe() is not None, "ffmpeg not on PATH (install ffmpeg or use app venv with static-ffmpeg)"
    r = subprocess.run(
        [_ffmpeg_exe(), "-version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert r.returncode == 0
    assert "ffmpeg version" in (r.stdout or "").lower()


def test_ffprobe_video_duration(sample_video_path: Path):
    """Read duration from a workspace test video."""
    ff = _ffprobe_exe()
    assert ff is not None, "ffprobe not on PATH"
    r = subprocess.run(
        [
            ff,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(sample_video_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    line = (r.stdout or "").strip().splitlines()
    assert line, "no duration output"
    dur = float(line[0])
    assert dur > 0.01, f"unexpected duration: {dur}"
