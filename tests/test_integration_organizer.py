"""Organizer engine against ``Test_Files`` (piexif + ffprobe when applicable)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.organizer import OrganizerEngine

pytestmark = pytest.mark.integration


def test_get_date_taken_jpg_does_not_raise(sample_photo_jpg: Path):
    eng = OrganizerEngine(logger_callback=lambda _m: None)
    dt = eng.get_date_taken(str(sample_photo_jpg))
    # May be None if EXIF missing; must not throw
    assert dt is None or (dt.year >= 1957)


def test_get_date_taken_video_does_not_raise(sample_video_path: Path):
    eng = OrganizerEngine(logger_callback=lambda _m: None)
    dt = eng.get_date_taken(str(sample_video_path))
    assert dt is None or (dt.year >= 1957)
