"""
First-frame subject hints for AI Video Upscaler (OpenCV only — no extra model downloads).

- **Face**: Haar frontal cascade (shared with image upscaler).
- **Human / person**: HOG pedestrian detector (full-body; complements face for distant figures).
- **Hair (heuristic)**: if a face is found, compares edge energy in the band above the face vs
  skin patch in the lower face — higher texture above often indicates hair vs smooth skin/forehead.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.zimage_portrait import detect_faces_bgr


def _yn(b: bool) -> str:
    return "yes" if b else "no"


@dataclass(frozen=True)
class VideoSubjectHints:
    """Cheap scene hints from one BGR frame (typically first frame)."""

    face: bool
    person_full_body: bool
    hair_likely: bool

    @property
    def human(self) -> bool:
        return self.face or self.person_full_body

    def summary_line(self) -> str:
        """Second line under source caption (compact)."""
        return (
            f"Subjects: human {_yn(self.human)} · face {_yn(self.face)} · "
            f"full-body {_yn(self.person_full_body)} · hair (est.) {_yn(self.hair_likely)}"
        )

    def log_line(self) -> str:
        """Console line for encode start (matches UI facts)."""
        return (
            f"Scene detection (first frame): human={_yn(self.human)}, face={_yn(self.face)}, "
            f"full-body person={_yn(self.person_full_body)}, hair (heuristic)={_yn(self.hair_likely)}"
        )


def _hog_person_present(gray_small, *, max_side: int = 800) -> bool:
    import cv2  # type: ignore

    h, w = gray_small.shape[:2]
    if h < 2 or w < 2:
        return False
    m = max(w, h)
    if m > max_side:
        s = max_side / float(m)
        nw = max(1, int(w * s))
        nh = max(1, int(h * s))
        g = cv2.resize(gray_small, (nw, nh), interpolation=cv2.INTER_AREA)
    else:
        g = gray_small

    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    rects, _ = hog.detectMultiScale(
        g,
        winStride=(8, 8),
        padding=(16, 16),
        scale=1.05,
        hitThreshold=0.0,
    )
    return len(rects) > 0


def _hair_likely_above_face(bgr, x: int, y: int, w: int, h: int) -> bool:
    """
    Heuristic: band above the face often contains hair (higher Laplacian variance than cheek skin).
    """
    import cv2  # type: ignore

    H, W = bgr.shape[:2]
    fh, fw = h, w
    if fh < 16 or fw < 16:
        return False

    y_top = max(0, y - int(0.85 * fh))
    y_face_top = y
    if y_face_top - y_top < 8:
        return False

    roi_hair = bgr[y_top:y_face_top, x : x + fw]
    if roi_hair.size < 400:
        return False

    y_skin0 = min(H - 2, y + int(0.55 * fh))
    y_skin1 = min(H, y + int(0.88 * fh))
    roi_skin = bgr[y_skin0:y_skin1, x : x + fw]
    if roi_skin.size < 200:
        return False

    g_h = cv2.cvtColor(roi_hair, cv2.COLOR_BGR2GRAY)
    g_s = cv2.cvtColor(roi_skin, cv2.COLOR_BGR2GRAY)
    lap_h = cv2.Laplacian(g_h, cv2.CV_64F)
    lap_s = cv2.Laplacian(g_s, cv2.CV_64F)
    var_h = float(lap_h.var())
    var_s = float(lap_s.var())
    if var_s < 1e-6:
        return var_h > 40.0
    return var_h > var_s * 1.32 and var_h > 35.0


def analyze_subjects_bgr(bgr, *, face_max_side: int = 960, hog_max_side: int = 800) -> VideoSubjectHints:
    """
    Analyze one BGR frame for human / face / hair hints.

    Best-effort; safe to call on any resolution.
    """
    import cv2  # type: ignore

    if bgr is None or bgr.size == 0:
        return VideoSubjectHints(face=False, person_full_body=False, hair_likely=False)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = detect_faces_bgr(bgr, max_scan_side=face_max_side)
    face = len(faces) > 0

    hair_likely = False
    if face:
        fx, fy, fw, fh = faces[0]
        hair_likely = _hair_likely_above_face(bgr, fx, fy, fw, fh)

    person_full_body = _hog_person_present(gray, max_side=hog_max_side)

    return VideoSubjectHints(
        face=face,
        person_full_body=person_full_body,
        hair_likely=hair_likely,
    )
