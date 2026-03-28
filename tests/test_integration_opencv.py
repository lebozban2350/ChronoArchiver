"""OpenCV read paths under ``Test_Files`` (skip if cv2 cannot load)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _cv2():
    # Some OpenCV wheels link cuDNN; importing torch first loads libcudnn so cv2 can load
    # (order-independent vs other tests that import torch earlier).
    try:
        import torch  # noqa: F401
    except Exception:
        pass
    try:
        import cv2

        return cv2
    except Exception as e:
        pytest.skip(f"opencv unavailable: {e}")


def test_imread_image(sample_photo_jpg: Path):
    cv2 = _cv2()
    img = cv2.imread(str(sample_photo_jpg), cv2.IMREAD_COLOR)
    assert img is not None
    assert len(img.shape) == 3
    assert img.shape[2] == 3


def test_video_capture_open_and_read_one_frame(sample_video_path: Path):
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(sample_video_path))
    assert cap.isOpened()
    ok, frame = cap.read()
    cap.release()
    assert ok
    assert frame is not None
    assert len(frame.shape) == 3
