"""Face detection for AI upscaler portrait mode (OpenCV Haar cascade, no extra models)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def _haar_frontalface_xml() -> str:
    import os

    import cv2  # type: ignore

    if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
        return cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    # Some builds expose cv2 as a .so under site-packages; data lives in site-packages/cv2/data/.
    base = os.path.dirname(cv2.__file__)
    if os.path.basename(base) != "cv2":
        base = os.path.join(base, "cv2")
    return os.path.join(base, "data", "haarcascade_frontalface_default.xml")


def detect_faces_bgr(
    bgr: "np.ndarray",
    *,
    max_scan_side: int = 960,
) -> list[tuple[int, int, int, int]]:
    """
    Return frontal face bounding boxes (x, y, w, h) in **source** pixel coordinates.

    Downscales internally for speed; boxes are mapped back to full resolution.
    """
    import cv2  # type: ignore

    if bgr is None or bgr.size == 0:
        return []
    h, w = bgr.shape[:2]
    if h < 2 or w < 2:
        return []

    if max(w, h) > max_scan_side:
        scale = max_scan_side / float(max(w, h))
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        inv = 1.0 / scale
    else:
        small = bgr
        inv = 1.0

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(_haar_frontalface_xml())
    if cascade.empty():
        return []

    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(40, 40),
    )
    out: list[tuple[int, int, int, int]] = []
    for (x, y, fw, fh) in faces:
        ox = int(round(x * inv))
        oy = int(round(y * inv))
        ow = int(round(fw * inv))
        oh = int(round(fh * inv))
        out.append((ox, oy, ow, oh))
    return out


def estimate_freckle_heavy_face(bgr: "np.ndarray", face: tuple[int, int, int, int]) -> bool:
    """
    Heuristic: cheek/nose band shows dense small darker speckles (typical freckle patterns).

    Used to strengthen "reduce freckles" prompts — best-effort, may false-positive on grainy skin.
    """
    import cv2  # type: ignore
    import numpy as np

    x, y, w, h = face
    H, W = bgr.shape[:2]
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    if w < 48 or h < 48:
        return False

    # Cheeks + upper nose (avoid hair strip and mouth).
    y0 = y + int(0.28 * h)
    y1 = y + int(0.68 * h)
    x0 = x + int(0.12 * w)
    x1 = x + int(0.88 * w)
    patch = bgr[y0:y1, x0:x1]
    if patch.size < 800:
        return False

    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(gray, (120, 80), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(g, (7, 7), 0)
    # Positive where pixel is darker than local average (speckles).
    speck = cv2.subtract(blur, g)
    _, m = cv2.threshold(speck, 10, 255, cv2.THRESH_BINARY)
    frac = float(np.mean(m > 0))
    var_s = float(speck.var())
    # Dense small dark deltas + variance → freckle-like texture.
    return (frac >= 0.085 and var_s >= 95.0) or (frac >= 0.12 and var_s >= 70.0)


def portrait_signals_from_path(
    image_path: str | Path,
    *,
    max_scan_side: int = 960,
) -> tuple[bool, bool]:
    """
    Return (face_detected, freckle_heavy_heuristic) in one read.

    ``freckle_heavy_heuristic`` is False when no face is found.
    """
    portrait, heavy, _ = portrait_signals_from_path_detailed(image_path, max_scan_side=max_scan_side)
    return portrait, heavy


def portrait_signals_from_path_detailed(
    image_path: str | Path,
    *,
    max_scan_side: int = 960,
) -> tuple[bool, bool, tuple[int, int, int, int] | None]:
    """
    Return (face_detected, freckle_heavy_heuristic, first_face_bbox_or_none).

    Bounding box is ``(x, y, w, h)`` in full-resolution pixel coordinates (first detected face).
    """
    import cv2  # type: ignore

    path = Path(image_path)
    if not path.is_file():
        return False, False, None

    bgr = cv2.imread(str(path))
    if bgr is None or bgr.size == 0:
        return False, False, None

    faces = detect_faces_bgr(bgr, max_scan_side=max_scan_side)
    if not faces:
        return False, False, None
    face = faces[0]
    heavy = estimate_freckle_heavy_face(bgr, face)
    return True, heavy, face


def detect_face_in_image(image_path: str | Path, *, max_scan_side: int = 960) -> bool:
    """
    Return True if at least one frontal face is detected (suitable for portrait/beautify heuristics).

    Large images are downscaled for speed; detection is best-effort.
    """
    portrait, _ = portrait_signals_from_path(image_path, max_scan_side=max_scan_side)
    return portrait
