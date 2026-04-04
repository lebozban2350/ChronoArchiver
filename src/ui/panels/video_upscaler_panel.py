"""
AI Video Upscaler — Real-ESRGAN (x2plus/x4plus), industry-style target resolutions, fixed cleanup pipeline, AV1 export.

Auto (no second NN): one pre-scan pass per clip — per-frame noise, grade, WB cast, skin warmth, and
artifact maps (macroblock/combing/banding/chroma/dropout); grades smoothed ±3 frames, then median /
step-limited in time to cut flicker on sharp edges (e.g. stripes). Encode blends classical inpaint
where the map is high, then Real-ESRGAN (wider tile overlap); chroma NR is weakened on high
luma-contrast frames. Temp artifact data is removed after mux.
"""

from __future__ import annotations

import logging
import math
import numpy as np
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QImage, QPixmap, QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ui.console_style import PANEL_CONSOLE_TEXTEDIT_STYLE, message_to_html
from ui.panel_widgets import (
    COMBO_BOX_PANEL_QSS,
    eng_row_btn_qss,
    field_label,
    fmt_bytes,
    format_net_speed,
    path_browse_btn_qss,
    pytorch_installer_vram_guidance,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.app_paths import settings_dir
from core.ml_runtime import (
    check_ml_runtime,
    install_ml_runtime,
    uninstall_ml_runtime,
    estimate_ml_runtime_components,
)
from core.lama_inpaint_models import APPROX_LAMA_BYTES, LAMA_FILENAME, LamaInpaintModelManager
from core.lama_inpaint_runner import LamaInpaintRunner
from core.fs_task_lock import release_fs_heavy, try_acquire_fs_heavy
from core.realesrgan_models import (
    RealESRGANModelManager,
    expected_bytes,
    model_filename_for_net_scale,
    net_scale_for_user_scale,
)
from core.network_status import (
    NO_NETWORK_LABEL_STYLE_9,
    NO_NETWORK_MESSAGE,
    is_network_reachable,
)
from core.realesrgan_runner import RealESRGANRunner
from core.video_target_presets import (
    VideoTargetPreset,
    VIDEO_TARGET_PRESETS,
    presets_above_source,
    source_video_caption_line,
    user_scale_for_preset,
)
from core.video_artifact_detection import prepare_source_for_realesrgan
from core.video_frame_preanalysis import (
    aesthetic_tuple_from_source,
    apply_skin_tone_warmth_bgr,
    cast_strength_from_source,
    pre_scan_video_upscale,
    skin_tone_strength_from_source,
)
from core.video_subject_detect import VideoSubjectHints, analyze_subjects_bgr, subject_tracks_log_line
from core.video_upscaler_settings import VideoUpscalerPanelSettings
from core.debug_logger import (
    INSTALLER_APP_AI_VIDEO_UPSCALER,
    UTILITY_APP,
    append_multiline,
    log_exception,
    log_installer_popup,
    mirror_panel_line,
)
from core.restart import restart_application
from core.venv_manager import format_pytorch_ready_line, get_ml_torch_install_label

from ui.panels.upscaler_panel import EngineSetupDialog

_vup_log = logging.getLogger("ChronoArchiver.video_upscaler")

# --- AI Video Upscaler: Real-ESRGAN + OpenCV (hard-coded pipeline) ---
# Inference matches xinntao RealESRGANer defaults: tile overlap + pre-pad; FP16 on CUDA when available.
VUP_REALESRGAN_TILE = 400  # px tile edge (0 = full frame; 400 balances VRAM vs speed for HD/4K)
VUP_REALESRGAN_TILE_PAD = 18  # wider overlap → fewer seam-related inconsistencies on busy textures
VUP_REALESRGAN_PRE_PAD = 10  # reflect pad before RRDB (official default)
VUP_REALESRGAN_HALF = True  # FP16 on CUDA; CPU path stays FP32 inside RealESRGANRunner

# After RRDB: clamp long edge before OpenCV post (8K cap for delivery / encoder stability).
VUP_MAX_EDGE = 7680

# Post–SR OpenCV chain (order: downscale-if-needed INTER_AREA → bilateral → unsharp). RRDB already denoises.
# Mild contrast + moderate unsharp (slightly softer than before) to avoid oversharpened edges.
VUP_DENOISE_BILATERAL_D = 5
VUP_DENOISE_SIGMA_COLOR = 42
VUP_DENOISE_SIGMA_SPACE = 42
VUP_POST_BRIGHTNESS = 0.0
VUP_POST_CONTRAST = 1.03
VUP_POST_SATURATION = 1.0
VUP_UNSHARP_STRENGTH = 0.37  # softer halos → less temporal shimmer on high-contrast edges when unsharp varies
VUP_UNSHARP_GAUSSIAN_SIGMA = 2.95  # wider Gaussian pairs with lower strength

# Chroma-only denoise (low-light red/green/magenta speckle, VHS & analog color noise).
# Same principle as editors' "chroma noise reduction" / AviSynth CNR2: smooth U & V in YUV, leave Y sharp.
# Not luminance denoise — targets chrominance blotches that read as "red noise" in shadows.
VUP_CHROMA_UV_DIAMETER = 5  # bilateral aperture on each chroma plane (odd)
VUP_CHROMA_UV_SIGMA_COLOR = 58  # higher = stronger blot suppression in U/V
VUP_CHROMA_UV_SIGMA_SPACE = 4.5  # local neighborhood (px) for edge-aware chroma blend

# Auto-apply chroma NR from source-frame stats (Real-ESRGAN has no low-light flag; this is cheap YUV heuristics).
# Trigger: dark frame (mean Y) OR elevated U/V spread (analog/tape/compressed chroma noise) at non-bright luma.
VUP_AUTO_CHROMA_MEAN_Y_LOW = 98.0  # below → likely low-light chroma noise
VUP_AUTO_CHROMA_MEAN_Y_MID = 132.0  # upper bound for “noisy chroma in mid tones” rule
VUP_AUTO_CHROMA_SPREAD_MIN = 22.0  # std(U)+std(V); catches speckle without needing a second NN

# Auto full-frame (luma) bilateral: ISO grain, sensor noise, compression blocking — not chroma speckle.
# Estimator: high-frequency residual |Y − Gauss(Y)| on source luma; median/mean vs thresholds.
VUP_AUTO_LUMA_ANALYSIS_MAX_EDGE = 640  # downscale before stats (speed); order-preserving for noise level
VUP_AUTO_LUMA_GAUSS_KSIZE = 7
VUP_AUTO_LUMA_GAUSS_SIGMA = 1.5
VUP_AUTO_LUMA_HF_MEDIAN_MIN = 4.0  # uniform grain: median hf residual (0–255 scale)
VUP_AUTO_LUMA_HF_MEAN_MIN = 7.0  # stronger mixed noise / edges+grain

# Auto grade heuristics (also used in core.video_frame_preanalysis for per-frame + temporal smooth).
VUP_AESTHETIC_ANALYSIS_MAX_EDGE = 640
# Luma: lift shadows / tame highlights
VUP_AUTO_AESTH_MEAN_Y_DARK = 52.0  # below → small brightness lift
VUP_AUTO_AESTH_MEAN_Y_BRIGHT = 210.0  # above → small pull-down
VUP_AUTO_AESTH_BRIGHTNESS_MAX_DELTA = 10.0
# Contrast: flat vs punchy histogram
VUP_AUTO_AESTH_STD_Y_FLAT = 34.0  # below → gentle contrast boost
VUP_AUTO_AESTH_STD_Y_PUNCHY = 68.0  # above → slight contrast ease
# Saturation: dull vs oversaturated
VUP_AUTO_AESTH_SAT_DULL = 78.0  # mean HSV S below → nudge up
VUP_AUTO_AESTH_SAT_HOT = 232.0  # above → nudge down
# Sharpness: soft vs already crisp (Laplacian variance on Y)
VUP_AUTO_AESTH_LAP_SOFT = 140.0  # below → slightly more unsharp
VUP_AUTO_AESTH_LAP_CRISP = 2800.0  # above → slightly less (fewer halos)
# Mild green/magenta drift (tape, white balance): pull U/V toward neutral
VUP_AUTO_CAST_UV_SUM_MIN = 20.0  # |meanU−128|+|meanV−128| before correction kicks in
VUP_AUTO_CAST_STRENGTH_MAX = 0.12  # blend factor toward 128 in U/V

_av1_encoder_name: str | None = None
_av1_encoder_extra: list[str] | None = None


def _ffmpeg_av1_encoder(ff: str) -> tuple[str, list[str]]:
    """Pick libsvtav1 or libaom-av1 from ffmpeg build; cache result."""
    global _av1_encoder_name, _av1_encoder_extra
    if _av1_encoder_name is not None and _av1_encoder_extra is not None:
        return _av1_encoder_name, list(_av1_encoder_extra)
    name, extra = "libsvtav1", ["-preset", "6", "-crf", "28", "-pix_fmt", "yuv420p"]
    try:
        r = subprocess.run(
            [ff, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        blob = f"{r.stdout}\n{r.stderr}"
        if "libsvtav1" in blob:
            name, extra = "libsvtav1", ["-preset", "6", "-crf", "28", "-pix_fmt", "yuv420p"]
        elif "libaom-av1" in blob:
            name, extra = "libaom-av1", ["-cpu-used", "6", "-crf", "32", "-pix_fmt", "yuv420p"]
    except (OSError, subprocess.TimeoutExpired):
        pass
    _av1_encoder_name, _av1_encoder_extra = name, extra
    return name, list(extra)


def _auto_chroma_nr_wanted_from_source(bgr) -> bool:
    """
    Decide whether to run chroma-only denoise for this frame, from the *source* BGR (pre–Real-ESRGAN).

    The RRDB model does not expose a scene label; we use fast YUV statistics that correlate with
    low-light chroma speckle (dark mean luma) or heavy chroma noise (high U/V spread at moderate luma).
    """
    import cv2
    import numpy as np

    if bgr is None or bgr.size == 0:
        return False
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
    y, u, v = cv2.split(yuv)
    mean_y = float(np.mean(y.astype(np.float32)))
    chroma_spread = float(np.std(u.astype(np.float32))) + float(np.std(v.astype(np.float32)))
    if mean_y < VUP_AUTO_CHROMA_MEAN_Y_LOW:
        return True
    if mean_y < VUP_AUTO_CHROMA_MEAN_Y_MID and chroma_spread >= VUP_AUTO_CHROMA_SPREAD_MIN:
        return True
    return False


def _auto_luma_nr_wanted_from_source(bgr) -> bool:
    """
    Decide whether to run full-frame bilateral (luminance / “normal” noise) for this frame.

    Uses source luma Y: high-frequency energy vs a Gaussian low-pass approximates visible grain /
    sensor noise without a second neural model. Clean footage stays sharper by skipping bilateral.
    """
    import cv2
    import numpy as np

    if bgr is None or bgr.size == 0:
        return False
    bgr = _resize_bgr_for_analysis(bgr, VUP_AUTO_LUMA_ANALYSIS_MAX_EDGE)
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
    y = yuv[:, :, 0]
    k = VUP_AUTO_LUMA_GAUSS_KSIZE | 1
    if k < 3:
        k = 3
    blur = cv2.GaussianBlur(y, (k, k), VUP_AUTO_LUMA_GAUSS_SIGMA)
    diff = np.abs(y.astype(np.float32) - blur.astype(np.float32))
    med = float(np.median(diff))
    mean_hf = float(np.mean(diff))
    if med >= VUP_AUTO_LUMA_HF_MEDIAN_MIN:
        return True
    if mean_hf >= VUP_AUTO_LUMA_HF_MEAN_MIN:
        return True
    return False


def _resize_bgr_for_analysis(bgr, max_edge: int):
    """Downscale for cheap stats; preserves aspect ratio."""
    import cv2

    if bgr is None or bgr.size == 0:
        return bgr
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m <= max_edge or m <= 0:
        return bgr
    s = float(max_edge) / float(m)
    nh, nw = max(1, int(h * s)), max(1, int(w * s))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def _apply_yuv_chroma_center_bgr(bgr, strength: float):
    """Blend U/V toward 128 (reduce global green/magenta cast). strength in [0, ~0.12]."""
    import cv2
    import numpy as np

    if bgr is None or bgr.size == 0 or strength <= 1e-6:
        return bgr
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
    y, u, v = cv2.split(yuv)
    u_f = u.astype(np.float32)
    v_f = v.astype(np.float32)
    u_f = u_f + strength * (128.0 - u_f)
    v_f = v_f + strength * (128.0 - v_f)
    u = np.clip(u_f, 0, 255).astype(np.uint8)
    v = np.clip(v_f, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([y, u, v]), cv2.COLOR_YUV2BGR)


def _chroma_noise_reduce_bgr(bgr):
    """
    Reduce chrominance noise (typical "red" / magenta / green speckle in dark areas and old tape).
    Operates in YUV: bilateral filter on U and V only so luminance detail is preserved.
    See e.g. chroma NR in YUV (Kdenlive, classic capture guides), vs. full-frame denoise.
    """
    import cv2

    if bgr is None or bgr.size == 0:
        return bgr
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
    y, u, v = cv2.split(yuv)
    d = VUP_CHROMA_UV_DIAMETER | 1  # must be odd
    if d < 3:
        d = 3
    u = cv2.bilateralFilter(
        u,
        d=d,
        sigmaColor=VUP_CHROMA_UV_SIGMA_COLOR,
        sigmaSpace=VUP_CHROMA_UV_SIGMA_SPACE,
    )
    v = cv2.bilateralFilter(
        v,
        d=d,
        sigmaColor=VUP_CHROMA_UV_SIGMA_COLOR,
        sigmaSpace=VUP_CHROMA_UV_SIGMA_SPACE,
    )
    yuv = cv2.merge([y, u, v])
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


def _denoise_bgr_one_step(bgr):
    """Full BGR bilateral after upscale — only when `_auto_luma_nr_wanted_from_source` says so."""
    import cv2

    if bgr is None or bgr.size == 0:
        return bgr
    return cv2.bilateralFilter(
        bgr,
        d=VUP_DENOISE_BILATERAL_D,
        sigmaColor=VUP_DENOISE_SIGMA_COLOR,
        sigmaSpace=VUP_DENOISE_SIGMA_SPACE,
    )


def _blend_nr_strength(bgr, strength: float, denoise_fn):
    """Blend identity with full denoise; strength in [0, 1] (temporally smoothed per-frame scores)."""
    import cv2
    import numpy as np

    if bgr is None or bgr.size == 0:
        return bgr
    a = float(np.clip(strength, 0.0, 1.0))
    if a <= 1e-6:
        return bgr
    d = denoise_fn(bgr)
    if a >= 1.0 - 1e-6:
        return d
    return cv2.addWeighted(bgr, 1.0 - a, d, a, 0)


def _chroma_nr_strength_after_edge_gate(bgr_src, strength: float) -> float:
    """
    YUV chroma bilateral can smear or shift at sharp B/W boundaries when strength flickers frame to frame.
    On high Laplacian energy (stripes, text), reduce effective chroma NR.
    """
    import cv2
    import numpy as np

    if bgr_src is None or bgr_src.size == 0 or strength <= 1e-6:
        return float(strength)
    sm = _resize_bgr_for_analysis(bgr_src, 560)
    yuv = cv2.cvtColor(sm, cv2.COLOR_BGR2YUV)
    y = yuv[:, :, 0]
    lap = cv2.Laplacian(y, cv2.CV_32F)
    e = float(np.mean(np.abs(lap)))
    # e ~5–12 calm; dense stripes / print often 20–50+
    t = float(np.clip((e - 8.0) / 30.0, 0.0, 1.0))
    return float(strength * (1.0 - 0.72 * t))


def _run_video_btn_stylesheet(*, pulse: bool = False, w: int, h: int) -> str:
    """UPSCALE (#btnStart): fixed box; guide pulse swaps border."""
    bd = "#ef4444" if pulse else "#10b981"
    fs = 8 if w <= 72 else 10
    return (
        "QPushButton#btnStart {"
        "background-color:#10b981; color:#064e3b; "
        f"border:2px solid {bd}; "
        f"font-size:{fs}px; font-weight:900; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px; "
        "}"
        "QPushButton#btnStart:hover:enabled {"
        "background-color:#34d399; color:#064e3b; "
        f"border:2px solid {bd}; "
        "}"
        "QPushButton#btnStart:disabled {"
        "background-color:#1a1a1a; color:#6b7280; border:2px solid #262626; "
        f"font-size:{fs}px; font-weight:900; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px; "
        "}"
    )


def _ffmpeg_exe() -> str | None:
    """Prefer PATH (after startup add_ffmpeg_to_path); fall back to venv static-ffmpeg."""
    s = shutil.which("ffmpeg")
    if s:
        return s
    try:
        from core.venv_manager import add_ffmpeg_to_path, check_ffmpeg_in_venv

        if check_ffmpeg_in_venv():
            add_ffmpeg_to_path()
            return shutil.which("ffmpeg")
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _cap_long_edge_bgr(img, max_edge: int):
    import cv2

    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_edge:
        return img
    s = max_edge / m
    # INTER_AREA is standard for downscaling (preserves detail vs linear).
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _post_color_bgr(img, brightness: float, contrast: float, saturation: float, sharpness: float):
    import cv2
    import numpy as np

    out = img.astype(np.float32)
    if contrast != 1.0:
        out = (out - 127.5) * contrast + 127.5
    out = np.clip(out + brightness, 0, 255)
    hsv = cv2.cvtColor(out.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if sharpness > 0:
        blur = cv2.GaussianBlur(out, (0, 0), VUP_UNSHARP_GAUSSIAN_SIGMA)
        out = cv2.addWeighted(out, 1.0 + sharpness, blur, -sharpness, 0)
    return out


def _format_video_clock(ms: int) -> str:
    ms = max(0, int(ms))
    total_s = ms // 1000
    m = total_s // 60
    s = total_s % 60
    return f"{m:d}:{s:02d}"


def _stop_encode_btn_stylesheet(*, w: int, h: int, job_running: bool) -> str:
    """job_running=True: encoding (red). job_running=False: idle (grey)."""
    if job_running:
        return (
            f"QPushButton#btnStopEncode {{"
            "background-color:#dc2626; color:#fef2f2; border:2px solid #b91c1c;"
            f"font-size:10px; font-weight:900;"
            f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
            "}"
            "QPushButton#btnStopEncode:hover:enabled {"
            "background-color:#ef4444; color:#fef2f2; border:2px solid #f87171;"
            "}"
            "QPushButton#btnStopEncode:disabled {"
            "background-color:#1a1a1a; color:#6b7280; border:2px solid #262626;"
            f"font-size:10px; font-weight:900;"
            f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
            "}"
        )
    return (
        f"QPushButton#btnStopEncode {{"
        "background-color:#262626; color:#6b7280; border:2px solid #3f3f46;"
        f"font-size:10px; font-weight:900;"
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
        "}"
        "QPushButton#btnStopEncode:hover:enabled { background-color:#3f3f46; }"
        "QPushButton#btnStopEncode:disabled {"
        "background-color:#1a1a1a; color:#52525b; border:2px solid #262626;"
        f"font-size:10px; font-weight:900;"
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
        "}"
    )


_VUP_SLIDER_QSS = """
QSlider::groove:horizontal {
    border: 1px solid #262626;
    height: 5px;
    background: #141414;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #3f3f46;
    border-radius: 2px;
}
QSlider::add-page:horizontal {
    background: #141414;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #71717a;
    border: 1px solid #a1a1aa;
    width: 11px;
    height: 11px;
    margin: -5px 0;
    border-radius: 3px;
}
QSlider::handle:horizontal:hover {
    background: #d4d4d8;
}
QSlider::disabled {
    opacity: 0.45;
}
"""

_VUP_PLAY_BTN_QSS = """
QPushButton#btnVideoPlay {
    background-color: #262626;
    color: #e4e4e7;
    border: 1px solid #3f3f46;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 700;
    min-width: 30px;
    max-width: 30px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
}
QPushButton#btnVideoPlay:hover:enabled { background-color: #3f3f46; }
QPushButton#btnVideoPlay:disabled { color: #52525b; background-color: #1a1a1a; border-color: #262626; }
"""


def _pixmap_from_bgr(bgr, max_w: int = 320, max_h: int = 300) -> QPixmap:
    import cv2

    if bgr is None:
        return QPixmap()
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    pix = QPixmap.fromImage(qimg.copy())
    return pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class _Signals(QObject):
    log_msg = Signal(str)
    setup_complete = Signal(object)
    progress_frames = Signal(int, int)
    noise_scan_progress = Signal(int, int)
    full_job_done = Signal()
    resource_warning = Signal(str)


class RealESRGANDownloadDialog(QDialog):
    """Progress for Real-ESRGAN + optional LaMa weight downloads (filename, bytes done, total)."""

    progress_update = Signal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_realesrgan_log_key: str | None = None
        self._last_realesrgan_log_ts = 0.0
        self.setWindowTitle("AI Video weights")
        self.setModal(False)
        self.setFixedSize(420, 180)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl = QLabel("Preparing…")
        self._lbl.setStyleSheet("font-size: 10px; font-weight: 600; color: #10b981;")
        v.addWidget(self._lbl)
        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("font-size: 8px; color: #6b7280;")
        v.addWidget(self._lbl_detail)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(14)
        v.addWidget(self._bar)
        v.addStretch()
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self.progress_update.connect(self._on_prog)
        self._net_t: float | None = None
        self._net_b: int = 0

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        log_installer_popup(INSTALLER_APP_AI_VIDEO_UPSCALER, "RealESRGANDownloadDialog", "opened")

    def closeEvent(self, event: QCloseEvent) -> None:
        log_installer_popup(INSTALLER_APP_AI_VIDEO_UPSCALER, "RealESRGANDownloadDialog", "closed")
        super().closeEvent(event)

    def _on_prog(self, filename: str, downloaded: int, total: int):
        self._lbl.setText(f"Downloading {filename}…")
        now = time.monotonic()
        spd = ""
        if downloaded == 0 or (self._net_b and downloaded < self._net_b):
            self._net_t = None
            self._net_b = 0
        if total > 0 and downloaded > 0 and self._net_t is not None and downloaded > self._net_b:
            dt = now - self._net_t
            if dt > 1e-6:
                spd = f" · {format_net_speed((downloaded - self._net_b) / dt)}"
        if total > 0:
            pct = min(100, int(100 * downloaded / total))
            self._bar.setValue(pct)
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            self._lbl_detail.setText(f"{mb_d:.1f} / {mb_t:.1f} MB{spd}")
        else:
            self._lbl_detail.setText(f"{downloaded // (1024 * 1024)} MB{spd}")
        self._net_t = now
        self._net_b = downloaded
        pct = min(100, int(100 * downloaded / total)) if total > 0 else 0
        log_key = f"{filename}|{pct}"
        if log_key != self._last_realesrgan_log_key or (now - self._last_realesrgan_log_ts) >= 2.0:
            self._last_realesrgan_log_key = log_key
            self._last_realesrgan_log_ts = now
            log_installer_popup(
                INSTALLER_APP_AI_VIDEO_UPSCALER,
                "RealESRGANDownloadDialog",
                "progress",
                f"file={filename!r} downloaded={downloaded} total={total} pct={pct}",
            )


# progress_frames(total): total > 0 = known frame count; total == 0 = unknown count (indeterminate);
# total == -1 = rawvideo → AV1 encode; total == -2 = optional audio mux to output.
_VUP_PROG_FFMPEG_PHASE = -1
_VUP_PROG_MUX_PHASE = -2


def _format_eta_hms(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    sec = int(round(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class _Video21x9PreviewHolder(QWidget):
    """Centers the preview label and sizes it to the largest 21:9 rectangle that fits (letterbox sides)."""

    _RW, _RH = 21, 9

    def __init__(self, panel: "VideoUpscalerPanel", label: QLabel, parent: QWidget | None = None):
        super().__init__(parent)
        self._panel = panel
        self._label = label
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        row.addStretch(1)
        lay.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        aw = max(1, self.width())
        ah = max(1, self.height())
        w_if_full_h = (ah * self._RW) // self._RH
        if w_if_full_h <= aw:
            w, h = w_if_full_h, ah
        else:
            w, h = aw, (aw * self._RH) // self._RW
        # Slightly larger than tight fit while staying inside the holder (preserves 21:9).
        w2 = min(aw, (w * 106) // 100)
        h2 = (w2 * self._RH) // self._RW
        if h2 > ah:
            h2 = ah
            w2 = (ah * self._RW) // self._RH
        w, h = w2, h2
        w = max(160, w)
        h = max(68, h)
        self._label.setFixedSize(w, h)
        if self._panel._last_frame_bgr is not None:
            self._panel._display_frame_bgr(cache=False)


class VideoUpscalerPanel(QWidget):
    def __init__(self, parent=None, status_callback=None):
        super().__init__(parent)
        self._status_cb = status_callback
        self._sig = _Signals()
        # QueuedConnection: emissions from threading.Thread must run slots on the GUI thread
        # or labels/buttons may not repaint (weights/engine row stuck until restart).
        _q = Qt.ConnectionType.QueuedConnection
        self._sig.log_msg.connect(self._add_log, _q)
        self._sig.setup_complete.connect(self._on_setup_complete, _q)
        self._sig.progress_frames.connect(self._on_frame_progress, _q)
        self._sig.noise_scan_progress.connect(self._on_noise_scan_progress, _q)
        self._sig.full_job_done.connect(self._finish_job_ui, _q)
        self._sig.resource_warning.connect(self._on_resource_warning, _q)

        self._base = settings_dir() / "ai_video_upscaler"
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._model_mgr = RealESRGANModelManager(self._base / "models")
        self._lama_mgr = LamaInpaintModelManager(self._base / "models")
        self._prefs = VideoUpscalerPanelSettings(self._base)
        self._source_dims: tuple[int, int] | None = None
        self._saved_preset_key: str = "uhd_4k"
        self._runner: RealESRGANRunner | None = None
        self._runner_key: tuple[str, int] | None = None
        self._lama_runner: LamaInpaintRunner | None = None
        self._lama_runner_key: str | None = None

        self._setup_in_progress = False
        self._job_in_progress = False
        self._fs_holding_vup = False
        self._job_eta_start_mono: float | None = None
        self._noise_eta_start_mono: float | None = None
        self._vup_upscale_eta_started = False
        self._cancel_job = threading.Event()
        self._pending_engine_install = False
        self._engine_just_installed = False
        self._active_dl_dialog: QDialog | None = None
        self._engine_setup_dialog: EngineSetupDialog | None = None

        self._last_output_path: str | None = None
        self._last_subject_hints: VideoSubjectHints | None = None

        self._cap_preview = None
        self._last_frame_bgr = None
        self._video_fps = 30.0
        self._video_frame_total = 0
        self._slider_programmatic = False
        self._is_playing = False
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._preview_seek_last_mono = 0.0

        # Source path row: match AI Image Upscaler (28px bar, 60×28 Browse).
        _bar_h = 28
        _browse_w, _browse_h = 60, _bar_h
        _src_edit_ss = (
            f"color:#fff; font-size:11px; font-weight:500; background:#121212; border:1px solid #1a1a1a; "
            f"padding:2px 6px; min-height:{_bar_h}px; max-height:{_bar_h}px;"
        )
        # SOURCE + Engine Status: same fixed height as AI Image Upscaler engine strip (PyTorch + weights rows).
        _strip = 72
        _ew, _eh = 82, 22
        self._eng_btn_w, self._eng_btn_h = _ew, _eh
        self._path_bar_h = _bar_h
        self._browse_btn_w = _browse_w
        _combo_style = COMBO_BOX_PANEL_QSS

        self._guide_pulse_timer = QTimer(self)
        self._guide_pulse_timer.setInterval(550)
        self._guide_pulse_timer.timeout.connect(self._pulse_guide)
        self._guide_glow_phase = 0
        self._guide_target = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 4)
        root.setSpacing(5)

        h_strip = QHBoxLayout()
        h_strip.setSpacing(8)

        _run_w, _run_h = 80, 26

        self._combo_scale = QComboBox()
        self._combo_scale.setStyleSheet(_combo_style)
        self._combo_scale.setFixedHeight(_run_h)
        self._combo_scale.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._combo_scale.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._combo_scale.setToolTip(
            "Target output (common name, pixel size, aspect). "
            "Only tiers above the source’s long edge are listed; scaling is uniform."
        )
        self._combo_scale.currentIndexChanged.connect(
            lambda *_: (self._refresh_engine_labels(), self._update_buttons())
        )

        grp_src = QGroupBox("SOURCE")
        grp_src.setFixedHeight(_strip)
        grp_src.setToolTip(
            "Pick a video (Browse is at the end of the path field). Scale and UPSCALE sit under the preview."
        )
        vs = QVBoxLayout(grp_src)
        vs.setContentsMargins(9, 2, 9, 3)
        vs.setSpacing(0)

        h_src = QHBoxLayout()
        h_src.setSpacing(6)
        h_src.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        h_src.addWidget(field_label("Video", 40))
        self._edit_video = QLineEdit()
        self._edit_video.setPlaceholderText("Path to video…")
        self._edit_video.setStyleSheet(_src_edit_ss)
        self._edit_video.setFixedHeight(_bar_h)
        self._edit_video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit_video.textChanged.connect(self._on_video_path_changed)
        h_src.addWidget(self._edit_video, 1)
        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setObjectName("browseBtn")
        self._btn_browse.setFixedSize(_browse_w, _browse_h)
        self._btn_browse.setStyleSheet(
            path_browse_btn_qss(
                self._path_bar_h, self._browse_btn_w, "#262626", "#aaa", border_px=1
            )
        )
        self._btn_browse.clicked.connect(self._browse_video)
        h_src.addWidget(self._btn_browse, 0, Qt.AlignmentFlag.AlignVCenter)
        vs.addLayout(h_src)

        self._vup_upscale_btn_w = _run_w
        self._vup_upscale_btn_h = _run_h
        self._btn_run = QPushButton("UPSCALE")
        self._btn_run.setObjectName("btnStart")
        self._btn_run.setFixedSize(self._vup_upscale_btn_w, self._vup_upscale_btn_h)
        self._btn_run.setStyleSheet(
            _run_video_btn_stylesheet(pulse=False, w=self._vup_upscale_btn_w, h=self._vup_upscale_btn_h)
        )
        self._btn_run.setToolTip("Export AV1 video at the same frame rate as the source (optional audio mux).")
        self._btn_run.clicked.connect(self._run_full_job)

        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setObjectName("btnStopEncode")
        self._btn_stop.setFixedSize(self._vup_upscale_btn_w, self._vup_upscale_btn_h)
        self._btn_stop.setStyleSheet(
            _stop_encode_btn_stylesheet(
                w=self._vup_upscale_btn_w,
                h=self._vup_upscale_btn_h,
                job_running=False,
            )
        )
        self._btn_stop.setEnabled(False)
        self._btn_stop.setToolTip("Stop encoding (cancels after the current step when possible).")
        self._btn_stop.clicked.connect(self._on_stop_encode)

        grp_eng = QGroupBox("Engine Status")
        grp_eng.setFixedHeight(_strip)
        grp_eng.setMinimumWidth(248)
        ve = QVBoxLayout(grp_eng)
        ve.setContentsMargins(4, 2, 4, 0)
        ve.setSpacing(2)
        h_pt = QHBoxLayout()
        h_pt.setSpacing(2)
        self._lbl_torch = QLabel("CHECKING…")
        self._lbl_torch.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_torch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lbl_torch.setWordWrap(False)
        lbl_pt = QLabel("PyTorch:", styleSheet="font-size:8px; color:#888;")
        lbl_pt.setFixedWidth(44)
        h_pt.addWidget(lbl_pt)
        h_pt.addWidget(self._lbl_torch, 1)
        h_pt.addSpacing(2)
        self._btn_inst_torch = QPushButton("Install PyTorch")
        self._btn_inst_torch.setFixedSize(_ew, _eh)
        self._btn_inst_torch.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_inst_torch.clicked.connect(self._on_install_torch)
        self._btn_rm_torch = QPushButton("Uninstall PyTorch")
        self._btn_rm_torch.setFixedSize(_ew, _eh)
        self._btn_rm_torch.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_rm_torch.clicked.connect(self._on_uninstall_torch)
        h_pt.addWidget(self._btn_inst_torch)
        h_pt.addWidget(self._btn_rm_torch)

        h_md = QHBoxLayout()
        h_md.setSpacing(2)
        self._lbl_weights = QLabel("CHECKING…")
        self._lbl_weights.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_weights.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lbl_weights.setWordWrap(False)
        lbl_w = QLabel("Weights:", styleSheet="font-size:8px; color:#888;")
        lbl_w.setFixedWidth(44)
        h_md.addWidget(lbl_w)
        h_md.addWidget(self._lbl_weights, 1)
        h_md.addSpacing(2)
        self._btn_dl_weights = QPushButton("Download")
        self._btn_dl_weights.setFixedSize(_ew, _eh)
        self._btn_dl_weights.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_dl_weights.clicked.connect(self._on_download_weights)
        self._btn_rm_weights = QPushButton("Uninstall Weights")
        self._btn_rm_weights.setFixedSize(_ew, _eh)
        self._btn_rm_weights.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_rm_weights.clicked.connect(self._on_remove_weights)
        h_md.addWidget(self._btn_dl_weights)
        h_md.addWidget(self._btn_rm_weights)

        ve.addLayout(h_pt)
        ve.addLayout(h_md)

        h_strip.addWidget(grp_src, 7)
        h_strip.addWidget(grp_eng, 3)
        root.addLayout(h_strip)

        grp_prev = QGroupBox("Source video")
        hp = QHBoxLayout(grp_prev)
        hp.setContentsMargins(9, 4, 9, 7)
        fr_o = QFrame()
        fr_o.setObjectName("previewCard")
        vo = QVBoxLayout(fr_o)
        vo.setContentsMargins(2, 2, 2, 2)
        vo.setSpacing(4)
        self._lbl_video = QLabel("No video")
        self._lbl_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_video.setStyleSheet(
            "color:#a1a1aa; font-size:11px; background-color:#0a0a0a; border:1px solid #262626;"
        )
        self._lbl_video.setScaledContents(False)
        self._video_21x9_holder = _Video21x9PreviewHolder(self, self._lbl_video)
        vo.addWidget(self._video_21x9_holder, 1)
        h_ctrl = QHBoxLayout()
        h_ctrl.setSpacing(8)
        self._btn_play = QPushButton("▶")
        self._btn_play.setObjectName("btnVideoPlay")
        self._btn_play.setStyleSheet(_VUP_PLAY_BTN_QSS)
        self._btn_play.setEnabled(False)
        self._btn_play.setToolTip("Play / pause")
        self._btn_play.clicked.connect(self._on_toggle_play)
        h_ctrl.addWidget(self._btn_play, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lbl_time_cur = QLabel("--:--")
        self._lbl_time_cur.setFixedWidth(44)
        self._lbl_time_cur.setStyleSheet("font-size:9px; color:#a1a1aa;")
        h_ctrl.addWidget(self._lbl_time_cur, 0, Qt.AlignmentFlag.AlignVCenter)
        self._time_slider = QSlider(Qt.Orientation.Horizontal)
        self._time_slider.setStyleSheet(_VUP_SLIDER_QSS)
        self._time_slider.setRange(0, 0)
        self._time_slider.setEnabled(False)
        self._time_slider.setTracking(True)
        self._time_slider.valueChanged.connect(self._on_time_slider_changed)
        h_ctrl.addWidget(self._time_slider, 1)
        self._lbl_time_total = QLabel("--:--")
        self._lbl_time_total.setFixedWidth(44)
        self._lbl_time_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_time_total.setStyleSheet("font-size:9px; color:#a1a1aa;")
        h_ctrl.addWidget(self._lbl_time_total, 0, Qt.AlignmentFlag.AlignVCenter)
        vo.addLayout(h_ctrl)
        self._lbl_orig_info = QLabel("")
        self._lbl_orig_info.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._lbl_orig_info.setWordWrap(True)
        self._lbl_orig_info.setStyleSheet("color:#737373; font-size:9px; margin-top: 2px;")
        vo.addWidget(self._lbl_orig_info, 0)
        hp.addWidget(fr_o, 1)
        # Preview vs console: tall 21:9 preview; console keeps a minimum line count (see below).
        root.addWidget(grp_prev, 20)

        h_bar = QHBoxLayout()
        h_bar.setSpacing(10)
        left_bar_col = QVBoxLayout()
        left_bar_col.setSpacing(0)
        left_bar_col.setContentsMargins(0, 0, 0, 0)
        self._bar = QProgressBar()
        self._bar.setFixedHeight(18)
        self._bar.setMinimumWidth(160)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("Ready")
        self._bar.setTextVisible(True)
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setVisible(True)
        left_bar_col.addWidget(self._bar)
        eta_row = QHBoxLayout()
        eta_row.setContentsMargins(0, 0, 0, 0)
        eta_row.addStretch(1)
        self._lbl_eta_prefix = QLabel("ESTIMATED TIME REMAINING:")
        self._lbl_eta_prefix.setStyleSheet(
            "color: #22c55e; font-size: 8px; font-weight: 600; letter-spacing: 0.02em; "
            "padding: 0px; margin: 0px;"
        )
        self._lbl_eta_time = QLabel("--:--:--")
        self._lbl_eta_time.setStyleSheet("color: #fafafa; font-size: 8px; padding: 0px; margin: 0px;")
        eta_row.addWidget(self._lbl_eta_prefix, 0, Qt.AlignmentFlag.AlignVCenter)
        eta_row.addSpacing(6)
        eta_row.addWidget(self._lbl_eta_time, 0, Qt.AlignmentFlag.AlignVCenter)
        eta_row.addStretch(1)
        left_bar_col.addLayout(eta_row)
        h_bar.addLayout(left_bar_col, 1)
        h_bar.addSpacing(8)
        _lbl_scale_bar = field_label("Target", 44)
        h_bar.addWidget(_lbl_scale_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        h_bar.addWidget(self._combo_scale, 0, Qt.AlignmentFlag.AlignVCenter)
        h_bar.addWidget(self._btn_run, 0, Qt.AlignmentFlag.AlignVCenter)
        h_bar.addWidget(self._btn_stop, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(h_bar)

        grp_log = QGroupBox("Console")
        grp_log.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        vl = QVBoxLayout(grp_log)
        v_log = QTextEdit()
        v_log.setObjectName("panelConsole")
        v_log.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        v_log.setReadOnly(True)
        v_log.setAcceptRichText(True)
        _fm = v_log.fontMetrics()
        _ls = int(_fm.lineSpacing())
        _cons_min = max(88, int(_fm.lineSpacing() * 4 + 28)) - _ls * 4
        v_log.setMinimumHeight(max(_ls * 4 + 20, _cons_min))
        v_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vl.setContentsMargins(8, 4, 8, 6)
        vl.addWidget(v_log, 1)
        root.addWidget(grp_log, 3)
        self._log_edit = v_log

        self._load_prefs()
        self._rebuild_resolution_combo()
        self._combo_scale.currentIndexChanged.connect(lambda *_: self._persist())

        QTimer.singleShot(0, self._refresh_engine_labels)
        QTimer.singleShot(0, self._update_buttons)
        if self._edit_video.text().strip():
            QTimer.singleShot(50, self._load_video_preview_thumb)

    def _load_prefs(self):
        p = self._prefs.load()
        # Video path is session-only: survives switching internal panels, not app restart.
        self._edit_video.setText("")
        self._saved_preset_key = str(p.get("preset_key") or "uhd_4k")

    def _persist(self):
        pr = self._active_preset()
        pk = pr.key if pr else self._saved_preset_key
        self._prefs.save(
            {
                "source_video": "",
                "preset_key": pk,
            }
        )

    def _active_preset(self) -> VideoTargetPreset | None:
        d = self._combo_scale.currentData()
        return d if isinstance(d, VideoTargetPreset) else None

    def _ui_user_scale(self) -> float:
        pr = self._active_preset()
        if pr is None:
            return 2.0
        if self._source_dims is None:
            return user_scale_for_preset(1920, 1080, pr)
        return user_scale_for_preset(self._source_dims[0], self._source_dims[1], pr)

    def _rebuild_resolution_combo(self) -> None:
        self._combo_scale.blockSignals(True)
        self._combo_scale.clear()
        w, h = self._source_dims if self._source_dims else (0, 0)
        if w > 0 and h > 0:
            presets = presets_above_source(w, h)
        else:
            presets = list(VIDEO_TARGET_PRESETS)
        for p in presets:
            self._combo_scale.addItem(p.combo_label(), p)
        want = self._saved_preset_key
        idx = -1
        for i in range(self._combo_scale.count()):
            d = self._combo_scale.itemData(i)
            if isinstance(d, VideoTargetPreset) and d.key == want:
                idx = i
                break
        if idx < 0 and self._combo_scale.count() > 0:
            idx = self._combo_scale.count() - 1
        if idx >= 0:
            self._combo_scale.setCurrentIndex(idx)
        self._combo_scale.blockSignals(False)
        self._combo_scale.updateGeometry()
        pr = self._active_preset()
        if pr:
            self._saved_preset_key = pr.key
        self._refresh_engine_labels()
        self._update_buttons()

    def _on_video_path_changed(self, *_):
        self._update_buttons()
        self._persist()
        QTimer.singleShot(0, self._load_video_preview_thumb)

    def get_activity(self) -> str:
        return "upscaling" if self._job_in_progress else "idle"

    def _notify_activity(self, activity: str) -> None:
        if self._status_cb:
            self._status_cb(activity)

    def _add_log(self, msg: str):
        s = str(msg).strip()
        mirror_panel_line("AI Video Upscaler", s)
        u = s.upper()
        if u.startswith("ERROR"):
            _vup_log.error(s)
        elif u.startswith("WARNING"):
            _vup_log.warning(s)
        self._log_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._log_edit.insertHtml(message_to_html(str(msg)))
        self._log_edit.insertPlainText("\n")

    def _on_resource_warning(self, msg: str):
        QMessageBox.warning(self, "GPU memory", msg)

    def _refresh_engine_labels(self):
        try:
            net_ok = is_network_reachable()
        except Exception:
            net_ok = True
        ok, reason = check_ml_runtime()
        if self._engine_just_installed:
            self._lbl_torch.setText("RESTART REQUIRED")
            self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#eab308;")
            self._btn_inst_torch.setText("Restart app")
            self._btn_inst_torch.show()
            self._btn_rm_torch.hide()
        elif ok:
            text, tip = format_pytorch_ready_line()
            self._lbl_torch.setText(text)
            self._lbl_torch.setToolTip(tip)
            self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#10b981;")
            self._btn_inst_torch.hide()
            self._btn_rm_torch.show()
        else:
            if not net_ok:
                self._lbl_torch.setText(NO_NETWORK_MESSAGE)
                self._lbl_torch.setStyleSheet(NO_NETWORK_LABEL_STYLE_9)
                self._btn_inst_torch.setToolTip("Internet required to install PyTorch.")
            else:
                self._lbl_torch.setText(reason.replace("_", " ").upper()[:18])
                self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#ef4444;")
                self._btn_inst_torch.setToolTip("")
            self._btn_inst_torch.show()
            self._btn_rm_torch.hide()

        ns = net_scale_for_user_scale(self._ui_user_scale())
        wr = self._model_mgr.is_ready(ns)
        lr = self._lama_mgr.is_ready()
        if wr:
            self._lbl_weights.setStyleSheet("font-size:9px;font-weight:700;color:#10b981;")
            if lr:
                self._lbl_weights.setText("READY")
                self._lbl_weights.setToolTip("Real-ESRGAN + LaMa (neural inpaint).")
                self._btn_dl_weights.hide()
            else:
                self._lbl_weights.setText("READY")
                self._lbl_weights.setToolTip(
                    "Real-ESRGAN ready. LaMa optional — Download adds neural inpainting "
                    "(else Telea for artifact repair)."
                )
                self._btn_dl_weights.show()
            self._btn_rm_weights.show()
        else:
            if not net_ok:
                self._lbl_weights.setText(NO_NETWORK_MESSAGE)
                self._lbl_weights.setStyleSheet(NO_NETWORK_LABEL_STYLE_9)
                self._btn_dl_weights.setToolTip(
                    "Internet required to download Real-ESRGAN / LaMa weights."
                )
            else:
                self._lbl_weights.setText("MISSING")
                self._lbl_weights.setStyleSheet("font-size:9px;font-weight:700;color:#ef4444;")
                self._btn_dl_weights.setToolTip("")
            self._btn_dl_weights.show()
            self._btn_rm_weights.hide()

    def _get_runner(self, net_scale: int) -> RealESRGANRunner:
        if not self._model_mgr.is_ready(net_scale):
            self._runner = None
            self._runner_key = None
            raise ValueError(
                "Real-ESRGAN weights are missing or invalid. Use Download Weights in this panel "
                "(invalid checkpoints are moved aside as *.pth.bad)."
            )
        mp = self._model_mgr.path_for_net_scale(net_scale)
        key = (str(Path(mp).resolve()), VUP_REALESRGAN_TILE)
        if self._runner is not None and self._runner_key == key:
            return self._runner
        self._runner = RealESRGANRunner(
            mp,
            net_scale=net_scale,
            tile=VUP_REALESRGAN_TILE,
            tile_pad=VUP_REALESRGAN_TILE_PAD,
            pre_pad=VUP_REALESRGAN_PRE_PAD,
            half=VUP_REALESRGAN_HALF,
        )
        self._runner_key = key
        return self._runner

    def _get_lama_runner(self) -> LamaInpaintRunner | None:
        """Neural inpainting for artifact repair; None if torch missing or LaMa weights absent."""
        ok, _ = check_ml_runtime()
        if not ok or not self._lama_mgr.is_ready():
            return None
        p = str(self._lama_mgr.path().resolve())
        if self._lama_runner is not None and self._lama_runner_key == p:
            return self._lama_runner
        try:
            self._lama_runner = LamaInpaintRunner(self._lama_mgr.path())
        except Exception:
            self._lama_runner = None
            self._lama_runner_key = None
            return None
        self._lama_runner_key = p
        return self._lama_runner

    def _process_frame(
        self,
        bgr,
        runner: RealESRGANRunner,
        user_scale: float,
        *,
        aesthetic: tuple[float, float, float, float] | None = None,
        cast_strength: float | None = None,
        skin_tone_strength: float | None = None,
        luma_nr_strength: float | None = None,
        chroma_nr_strength: float | None = None,
        artifact_mask: np.ndarray | None = None,
    ):
        if luma_nr_strength is None:
            luma_nr_strength = 1.0 if _auto_luma_nr_wanted_from_source(bgr) else 0.0
        if chroma_nr_strength is None:
            chroma_nr_strength = 1.0 if _auto_chroma_nr_wanted_from_source(bgr) else 0.0
        chroma_nr_strength = _chroma_nr_strength_after_edge_gate(bgr, float(chroma_nr_strength))
        lama = self._get_lama_runner() if artifact_mask is not None else None
        bgr_for_sr = (
            prepare_source_for_realesrgan(bgr, artifact_mask, lama=lama)
            if artifact_mask is not None
            else bgr
        )
        up = runner.enhance(bgr_for_sr, user_scale=float(user_scale))
        up = _cap_long_edge_bgr(up, VUP_MAX_EDGE)
        up = _blend_nr_strength(up, chroma_nr_strength, _chroma_noise_reduce_bgr)
        up = _blend_nr_strength(up, luma_nr_strength, _denoise_bgr_one_step)
        if aesthetic is None:
            aesthetic = aesthetic_tuple_from_source(bgr)
        pb, pc, ps, psh = aesthetic
        up = _post_color_bgr(up, pb, pc, ps, psh)
        if cast_strength is None:
            cast_strength = cast_strength_from_source(bgr)
        if cast_strength > 1e-6:
            up = _apply_yuv_chroma_center_bgr(up, cast_strength)
        if skin_tone_strength is None:
            skin_tone_strength = skin_tone_strength_from_source(bgr)
        if skin_tone_strength > 1e-6:
            up = apply_skin_tone_warmth_bgr(up, skin_tone_strength)
        return up

    def _update_buttons(self):
        path = self._edit_video.text().strip()
        path_ok = bool(path and os.path.isfile(path))
        preset_ok = self._active_preset() is not None and self._combo_scale.count() > 0
        dims_ok = self._source_dims is not None
        ns = net_scale_for_user_scale(self._ui_user_scale())
        w_ok = self._model_mgr.is_ready(ns)
        t_ok, _ = check_ml_runtime()
        busy = self._setup_in_progress or self._job_in_progress
        try:
            net_ok = is_network_reachable()
        except Exception:
            net_ok = True
        need_torch_net = not t_ok and not self._engine_just_installed
        need_weights_net = (not w_ok) or (not self._lama_mgr.is_ready())
        self._btn_run.setEnabled(
            path_ok and preset_ok and dims_ok and w_ok and t_ok and not busy and bool(_ffmpeg_exe())
        )
        self._btn_browse.setEnabled(not busy)
        self._btn_dl_weights.setEnabled(not busy and (not need_weights_net or net_ok))
        has_any_weights = (
            self._model_mgr.is_ready(2) or self._model_mgr.is_ready(4) or self._lama_mgr.is_ready()
        )
        self._btn_rm_weights.setEnabled(not busy and has_any_weights)
        self._btn_inst_torch.setEnabled(
            (not busy or self._engine_just_installed) and (not need_torch_net or net_ok)
        )
        self._btn_rm_torch.setEnabled(not busy and t_ok and not self._engine_just_installed)
        self._btn_stop.setEnabled(self._job_in_progress)
        self._btn_stop.setStyleSheet(
            _stop_encode_btn_stylesheet(
                w=self._vup_upscale_btn_w,
                h=self._vup_upscale_btn_h,
                job_running=self._job_in_progress,
            )
        )
        # Lock preview play/seek during engine setup or while encoding (defense: also guard in handlers).
        preview_locked = self._setup_in_progress or self._job_in_progress
        can_play = (
            path_ok
            and dims_ok
            and self._cap_preview is not None
            and not preview_locked
        )
        self._btn_play.setEnabled(can_play)
        self._time_slider.setEnabled(can_play and self._video_frame_total > 0)
        if self._job_in_progress:
            self._btn_play.setToolTip(
                "Manual playback is disabled while encoding; the preview follows encode progress."
            )
            self._time_slider.setToolTip(
                "Seek is disabled while encoding; the playhead moves with encode progress."
            )
        elif self._setup_in_progress:
            self._btn_play.setToolTip("Playback is disabled while the engine is being set up.")
            self._time_slider.setToolTip("Seek is disabled while the engine is being set up.")
        else:
            self._btn_play.setToolTip("Play / pause")
            self._time_slider.setToolTip("")
        self._sync_guide_pulse()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._display_frame_bgr(cache=False)

    def _release_preview_cap(self) -> None:
        self._stop_playback()
        self._last_frame_bgr = None
        if self._cap_preview is not None:
            try:
                self._cap_preview.release()
            except Exception:
                pass
            self._cap_preview = None
        self._video_frame_total = 0
        self._video_fps = 30.0
        self._slider_programmatic = True
        self._time_slider.setRange(0, 0)
        self._time_slider.setValue(0)
        self._slider_programmatic = False
        self._lbl_time_cur.setText("--:--")
        self._lbl_time_total.setText("--:--")

    def _stop_playback(self) -> None:
        self._play_timer.stop()
        self._is_playing = False
        self._btn_play.setText("▶")

    def _display_frame_bgr(self, bgr=None, *, cache: bool = True):
        import numpy as np

        if cache:
            if bgr is None or (hasattr(bgr, "size") and bgr.size == 0):
                self._lbl_video.clear()
                self._last_frame_bgr = None
                return
            self._last_frame_bgr = np.asarray(bgr, dtype=np.uint8).copy()
        arr = self._last_frame_bgr
        if arr is None:
            return
        ww = max(1, self._lbl_video.width() - 4)
        hh = max(1, self._lbl_video.height() - 4)
        pix = _pixmap_from_bgr(arr, ww, hh)
        self._lbl_video.setPixmap(pix)
        self._lbl_video.setText("")

    def _update_time_labels(self) -> None:
        if self._video_frame_total <= 0:
            self._lbl_time_cur.setText("--:--")
            self._lbl_time_total.setText("--:--")
            return
        fps = max(self._video_fps, 1e-6)
        idx = self._time_slider.value()
        cur_ms = int(1000 * idx / fps)
        total_ms = int(1000 * max(0, self._video_frame_total - 1) / fps)
        self._lbl_time_cur.setText(_format_video_clock(cur_ms))
        self._lbl_time_total.setText(_format_video_clock(total_ms))

    def _seek_to_frame(self, idx: int) -> None:
        import cv2

        if self._cap_preview is None or not self._cap_preview.isOpened():
            return
        if self._video_frame_total <= 0:
            return
        idx = max(0, min(int(idx), self._video_frame_total - 1))
        self._cap_preview.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = self._cap_preview.read()
        if ok and fr is not None:
            self._display_frame_bgr(fr)
            self._slider_programmatic = True
            self._time_slider.setValue(idx)
            self._slider_programmatic = False
        self._update_time_labels()

    def _on_time_slider_changed(self, value: int) -> None:
        if self._slider_programmatic:
            return
        if self._job_in_progress or self._setup_in_progress:
            return
        self._seek_to_frame(value)

    def _on_toggle_play(self) -> None:
        if self._job_in_progress or self._setup_in_progress:
            return
        if self._cap_preview is None or not self._cap_preview.isOpened():
            return
        if self._video_frame_total <= 0:
            return
        if self._is_playing:
            self._stop_playback()
            return
        fps = max(self._video_fps, 1e-6)
        self._play_timer.setInterval(int(max(33, min(100, 1000 / fps))))
        self._is_playing = True
        self._btn_play.setText("⏸")
        self._play_timer.start()

    def _on_play_tick(self) -> None:
        import cv2

        if self._job_in_progress or self._cap_preview is None or not self._cap_preview.isOpened():
            self._stop_playback()
            return
        ok, fr = self._cap_preview.read()
        if not ok or fr is None:
            self._stop_playback()
            return
        pos = int(self._cap_preview.get(cv2.CAP_PROP_POS_FRAMES))
        idx = max(0, min(pos - 1, self._video_frame_total - 1))
        self._slider_programmatic = True
        self._time_slider.setValue(idx)
        self._slider_programmatic = False
        self._update_time_labels()
        self._display_frame_bgr(fr)
        if idx >= self._video_frame_total - 1:
            self._stop_playback()

    def _on_stop_encode(self) -> None:
        if not self._job_in_progress:
            return
        self._cancel_job.set()
        self._add_log("Stop requested — cancelling after the current step.")

    def _pause_preview_player_for_job(self) -> None:
        """Stop playback but keep the preview capture so we can seek frames during encode."""
        self._stop_playback()
        self._preview_seek_last_mono = 0.0

    def _reload_preview_after_job(self) -> None:
        path = self._edit_video.text().strip()
        if path and os.path.isfile(path):
            self._load_video_preview_thumb()

    def _sync_guide_pulse(self) -> None:
        busy = self._setup_in_progress or self._job_in_progress
        if busy:
            self._guide_pulse_timer.stop()
            self._clear_guide_glow(self._guide_target)
            self._guide_target = None
            return
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _get_guide_target(self):
        if self._setup_in_progress or self._job_in_progress:
            return None
        if self._engine_just_installed:
            return self._btn_inst_torch
        t_ok, _ = check_ml_runtime()
        if not t_ok:
            return self._btn_inst_torch
        ns = net_scale_for_user_scale(self._ui_user_scale())
        if not self._model_mgr.is_ready(ns):
            return self._btn_dl_weights
        path = self._edit_video.text().strip()
        if not path or not os.path.isfile(path):
            return self._btn_browse
        if self._combo_scale.count() <= 0 or self._active_preset() is None:
            return None
        if self._source_dims is None:
            return None
        return self._btn_run

    def _clear_guide_glow(self, w):
        if not w:
            return
        ew, eh = self._eng_btn_w, self._eng_btn_h
        if w == self._btn_run:
            w.setStyleSheet(
                _run_video_btn_stylesheet(
                    pulse=False, w=self._vup_upscale_btn_w, h=self._vup_upscale_btn_h
                )
            )
        elif w == self._btn_browse:
            w.setStyleSheet(
                path_browse_btn_qss(
                    self._path_bar_h, self._browse_btn_w, "#262626", "#aaa", border_px=1
                )
            )
        elif w == self._btn_inst_torch:
            if self._engine_just_installed:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#064e3b", "#064e3b", "#10b981"))
            elif not check_ml_runtime()[0]:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#aaa", "#262626"))
            else:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#aaa", "#262626"))
        elif w == self._btn_dl_weights:
            w.setStyleSheet(eng_row_btn_qss(ew, eh, "#aaa", "#262626"))

    def _pulse_guide(self):
        target = self._get_guide_target()
        # Do not pulse disabled controls (e.g. UPSCALE without FFmpeg). Skip isVisible() so the
        # guide still runs when this panel is on a stacked page that is not the current tab.
        if target is not None and not target.isEnabled():
            target = None
        if target != self._guide_target:
            self._clear_guide_glow(self._guide_target)
            self._guide_target = target
        if not target:
            self._guide_pulse_timer.stop()
            self._clear_guide_glow(self._guide_target)
            self._guide_target = None
            return
        self._guide_glow_phase = 1 - self._guide_glow_phase
        ew, eh = self._eng_btn_w, self._eng_btn_h
        if self._guide_glow_phase:
            if target == self._btn_run and target.isEnabled():
                target.setStyleSheet(
                    _run_video_btn_stylesheet(
                        pulse=True, w=self._vup_upscale_btn_w, h=self._vup_upscale_btn_h
                    )
                )
            elif target == self._btn_browse:
                target.setStyleSheet(
                    path_browse_btn_qss(
                        self._path_bar_h, self._browse_btn_w, "#ef4444", "#ef4444", border_px=1
                    )
                )
            elif target == self._btn_inst_torch and self._engine_just_installed:
                target.setStyleSheet(eng_row_btn_qss(ew, eh, "#064e3b", "#34d399", "#10b981"))
            elif target in (self._btn_inst_torch, self._btn_dl_weights):
                target.setStyleSheet(eng_row_btn_qss(ew, eh, "#ef4444", "#ef4444", "transparent"))
        else:
            self._clear_guide_glow(target)

    def _browse_video(self):
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Open video",
            "",
            "Video (*.mp4 *.mkv *.mov *.avi *.webm *.3gp);;All files (*)",
        )
        if p:
            self._edit_video.setText(p)
            self._load_video_preview_thumb()

    def _update_orig_source_info(self) -> None:
        if self._source_dims is None:
            self._lbl_orig_info.setText("")
            return
        w, h = self._source_dims
        line = source_video_caption_line(w, h)
        if self._last_subject_hints is not None:
            line = f"{line}\n{self._last_subject_hints.summary_line()}"
        self._lbl_orig_info.setText(line)

    def _load_video_preview_thumb(self):
        path = self._edit_video.text().strip()
        try:
            if not path or not os.path.isfile(path):
                self._source_dims = None
                self._last_subject_hints = None
                self._release_preview_cap()
                self._lbl_video.setText("No video")
                self._lbl_video.setPixmap(QPixmap())
                self._rebuild_resolution_combo()
                return
            import cv2

            self._release_preview_cap()
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self._source_dims = None
                self._last_subject_hints = None
                self._lbl_video.setText("Unreadable")
                self._lbl_video.setPixmap(QPixmap())
                self._rebuild_resolution_combo()
                return
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self._source_dims = (w, h) if w > 0 and h > 0 else None
            self._video_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            self._video_frame_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._cap_preview = cap
            fps = max(self._video_fps, 1e-6)
            self._play_timer.setInterval(int(max(33, min(100, 1000 / fps))))
            if self._video_frame_total > 0:
                self._slider_programmatic = True
                self._time_slider.setRange(0, self._video_frame_total - 1)
                self._slider_programmatic = False
            else:
                self._slider_programmatic = True
                self._time_slider.setRange(0, 0)
                self._slider_programmatic = False
            self._cap_preview.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, fr = self._cap_preview.read()
            if not ok or fr is None:
                self._release_preview_cap()
                self._last_subject_hints = None
                self._lbl_video.setText("Unreadable")
                self._lbl_video.setPixmap(QPixmap())
                self._rebuild_resolution_combo()
                return
            self._slider_programmatic = True
            self._time_slider.setValue(0)
            self._slider_programmatic = False
            self._update_time_labels()
            self._display_frame_bgr(fr)
            try:
                self._last_subject_hints = analyze_subjects_bgr(fr)
            except Exception:
                self._last_subject_hints = None
            self._rebuild_resolution_combo()
        finally:
            self._update_orig_source_info()

    def _sync_preview_to_encode_progress(self, cur: int, total: int) -> None:
        """Seek source preview to the last encoded frame (cur = frames done, 1-based). GUI thread only."""
        import cv2

        if not self._job_in_progress or self._cap_preview is None or not self._cap_preview.isOpened():
            return
        if cur <= 0:
            return
        idx = cur - 1
        if self._video_frame_total > 0:
            idx = min(idx, self._video_frame_total - 1)
        if total > 0:
            idx = min(idx, total - 1)
        idx = max(0, idx)

        now = time.monotonic()
        at_end = (total > 0 and cur >= total) or (
            self._video_frame_total > 0 and idx >= self._video_frame_total - 1
        )
        if not at_end and (now - self._preview_seek_last_mono) < (1.0 / 12.0):
            return
        self._preview_seek_last_mono = now

        self._cap_preview.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = self._cap_preview.read()
        if not ok or fr is None:
            return
        self._slider_programmatic = True
        self._time_slider.setValue(idx)
        self._slider_programmatic = False
        self._update_time_labels()
        self._display_frame_bgr(fr)

    def _set_eta_idle(self) -> None:
        self._lbl_eta_time.setText("--:--:--")

    def _update_eta_remaining(
        self, cur: int, total: int, *, start_mono: float | None = None
    ) -> None:
        if total <= 0 or cur <= 0:
            self._set_eta_idle()
            return
        t0 = start_mono if start_mono is not None else self._job_eta_start_mono
        if t0 is None:
            self._set_eta_idle()
            return
        elapsed = time.monotonic() - t0
        if elapsed < 1e-3:
            self._set_eta_idle()
            return
        rate = cur / elapsed
        if rate < 1e-12:
            self._set_eta_idle()
            return
        rem = (total - cur) / rate
        self._lbl_eta_time.setText(_format_eta_hms(rem))

    def _on_noise_scan_progress(self, cur: int, total: int):
        if self._noise_eta_start_mono is None:
            self._noise_eta_start_mono = time.monotonic()
        if total <= 0:
            self._bar.setRange(0, 0)
            self._bar.setFormat(f"Analyzing frames (noise, grade, skin)… {cur} frame(s)")
            self._set_eta_idle()
            return
        self._bar.setRange(0, 100)
        self._bar.setValue(int(100 * min(1.0, cur / total)))
        self._bar.setFormat(f"Analyzing frames: {cur} / {total}")
        self._update_eta_remaining(cur, total, start_mono=self._noise_eta_start_mono)

    def _on_frame_progress(self, cur: int, total: int):
        if total == _VUP_PROG_FFMPEG_PHASE:
            self._bar.setRange(0, 0)
            self._bar.setFormat("Encoding AV1…")
            self._set_eta_idle()
            return
        if total == _VUP_PROG_MUX_PHASE:
            self._bar.setRange(0, 0)
            self._bar.setFormat("Muxing output…")
            self._set_eta_idle()
            return
        if total <= 0:
            self._bar.setRange(0, 0)
            self._bar.setFormat(f"{cur} frames · AI upscale…")
            self._set_eta_idle()
            if self._job_in_progress and cur > 0:
                self._sync_preview_to_encode_progress(cur, self._video_frame_total or 0)
            return
        if not self._vup_upscale_eta_started:
            self._vup_upscale_eta_started = True
            self._job_eta_start_mono = time.monotonic()
        self._bar.setRange(0, 100)
        self._bar.setValue(int(100 * min(1.0, cur / total)))
        self._bar.setFormat(f"{cur} / {total} frames")
        self._update_eta_remaining(cur, total)
        if self._job_in_progress and cur > 0:
            self._sync_preview_to_encode_progress(cur, total)

    def _run_full_job(self):
        path = self._edit_video.text().strip()
        ff = _ffmpeg_exe()
        if not ff:
            QMessageBox.warning(self, "FFmpeg", "FFmpeg not found in PATH.")
            return
        pr = self._active_preset()
        if pr is None or self._combo_scale.count() <= 0:
            QMessageBox.warning(
                self,
                "Target resolution",
                "Choose a target output resolution (tiers above the source long edge).",
            )
            return
        if self._source_dims is None:
            QMessageBox.warning(self, "Video", "Could not read source video dimensions.")
            return
        sw, sh = self._source_dims
        user_sc = user_scale_for_preset(sw, sh, pr)
        ns = net_scale_for_user_scale(user_sc)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Save upscaled video (AV1)",
            "",
            "MP4 / AV1 (*.mp4);;Matroska / AV1 (*.mkv);;All files (*)",
        )
        if not dest:
            return
        low = dest.lower()
        if not (low.endswith(".mp4") or low.endswith(".mkv")):
            dest += ".mp4"
        if os.path.abspath(os.path.normpath(dest)) == os.path.abspath(os.path.normpath(path)):
            QMessageBox.warning(
                self,
                "Output file",
                "Output path must differ from the source video (same file would corrupt the input).",
            )
            return

        try:
            runner = self._get_runner(ns)
        except Exception as e:
            self._add_log(f"ERROR: {e}")
            QMessageBox.warning(self, "Engine", str(e))
            QTimer.singleShot(0, self._reload_preview_after_job)
            return

        out_dir = os.path.dirname(os.path.abspath(dest)) or "."
        try:
            import cv2

            n = int(self._video_frame_total or 0)
            if n <= 0:
                cap = cv2.VideoCapture(path)
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
            raw = max(1, sw) * max(1, sh) * 3
            est = max(n * raw * 2, os.path.getsize(path) * 6)
            du = shutil.disk_usage(out_dir)
            if du.free < est * 1.20:
                r = QMessageBox.question(
                    self,
                    "Low disk space",
                    f"Rough working-space estimate: ~{est / (1024**3):.1f} GB.\n"
                    f"Free on output drive: ~{du.free / (1024**3):.1f} GB (aim for ~20% headroom).\n"
                    f"Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r != QMessageBox.StandardButton.Yes:
                    return
        except OSError:
            pass

        if not try_acquire_fs_heavy():
            QMessageBox.warning(
                self,
                "Busy",
                "Another file-heavy operation is in progress (Mass AV1 Encoder or Media Organizer).",
            )
            return
        self._fs_holding_vup = True

        self._cancel_job.clear()
        self._pause_preview_player_for_job()
        self._job_in_progress = True
        self._job_eta_start_mono = time.monotonic()
        self._noise_eta_start_mono = None
        self._vup_upscale_eta_started = False
        self._set_eta_idle()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("Starting…")
        self._update_buttons()
        self._notify_activity("upscaling")
        self._add_log(f"Starting upscale → {dest} ({pr.combo_label()}, {user_sc:.3f}×)")

        def work():
            import cv2

            tmp_vid = None
            artifact_dir: str | None = None
            try:
                _noise_prog_last = [0.0]

                def _noise_progress(done: int, tot: int) -> None:
                    now = time.monotonic()
                    # First frame, last frame, and ~10 Hz so long clips do not flood the GUI thread.
                    is_final = tot > 0 and done >= tot
                    if done != 1 and not is_final and (now - _noise_prog_last[0]) < 0.1:
                        return
                    _noise_prog_last[0] = now
                    self._sig.noise_scan_progress.emit(done, tot)

                try:
                    artifact_dir = tempfile.mkdtemp(prefix="ca_vup_art_")
                except OSError:
                    artifact_dir = None
                pre = pre_scan_video_upscale(
                    path,
                    on_progress=_noise_progress,
                    artifact_dir=artifact_dir,
                )
                if pre is None:
                    aest_pack = None
                    if artifact_dir and os.path.isdir(artifact_dir):
                        shutil.rmtree(artifact_dir, ignore_errors=True)
                    artifact_dir = None
                    self._sig.log_msg.emit(
                        "WARN: could not pre-scan; using per-source-frame noise and grade heuristics."
                    )
                else:
                    aest_pack = pre
                    self._sig.log_msg.emit(
                        "Per-frame analysis: noise, grade (b/c/sat/unsharp), WB cast, skin warmth — "
                        f"temporally smoothed ±3 frames + edge-flicker stabilization, {len(pre['luma_nr'])} source frame(s)."
                    )
                    try:
                        self._sig.log_msg.emit(
                            subject_tracks_log_line(
                                pre["subject_face"],
                                pre["subject_full_body"],
                                pre["subject_hair"],
                            )
                        )
                    except Exception:
                        pass
                    if artifact_dir:
                        self._sig.log_msg.emit(
                            "Artifact maps (macroblock, combing, banding, chroma, dropout) saved for "
                            f"inpaint+AI pass; temp dir removed after encode."
                        )

                cap = cv2.VideoCapture(path)
                if not cap.isOpened():
                    self._sig.log_msg.emit("ERROR: could not open video")
                    return
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                if n <= 0:
                    n = -1
                ok, fr0 = cap.read()
                if not ok or fr0 is None:
                    self._sig.log_msg.emit("ERROR: empty video")
                    cap.release()
                    return

                def _frame_params(idx: int):
                    """Returns (aesthetic, cast, skin, luma_nr, chroma_nr); all None if no pre-scan."""
                    if aest_pack is None:
                        return None, None, None, None, None
                    ni = int(np.clip(idx, 0, len(aest_pack["luma_nr"]) - 1))
                    aesthetic = (
                        float(aest_pack["brightness"][ni]),
                        float(aest_pack["contrast"][ni]),
                        float(aest_pack["saturation"][ni]),
                        float(aest_pack["sharpness"][ni]),
                    )
                    return (
                        aesthetic,
                        float(aest_pack["cast"][ni]),
                        float(aest_pack["skin_tone"][ni]),
                        float(aest_pack["luma_nr"][ni]),
                        float(aest_pack["chroma_nr"][ni]),
                    )

                def _artifact_mask_at(idx: int) -> np.ndarray | None:
                    if not artifact_dir:
                        return None
                    p = os.path.join(artifact_dir, f"{idx:06d}.npz")
                    if not os.path.isfile(p):
                        return None
                    with np.load(p) as z:
                        return np.asarray(z["mask"], dtype=np.uint8).copy()

                ae0, c0, sk0, lu0, ch0 = _frame_params(0)
                am0 = _artifact_mask_at(0)
                if ae0 is not None:
                    self._sig.log_msg.emit(
                        "Example (frame 0, smoothed): "
                        f"bΔ={ae0[0]:+.1f}, c={ae0[1]:.2f}, sat={ae0[2]:.2f}, "
                        f"unsharp={ae0[3]:.2f} (soft↔sharp), cast={c0:.3f}, skin={sk0:.2f}"
                    )
                if aest_pack is None:
                    try:
                        sub = analyze_subjects_bgr(fr0)
                        self._sig.log_msg.emit(
                            "Pre-scan unavailable — subject hint from opening frame only. " + sub.log_line()
                        )
                    except Exception:
                        pass
                out0 = self._process_frame(
                    fr0,
                    runner,
                    user_sc,
                    aesthetic=ae0,
                    cast_strength=c0,
                    skin_tone_strength=sk0,
                    luma_nr_strength=lu0,
                    chroma_nr_strength=ch0,
                    artifact_mask=am0,
                )
                oh, ow = out0.shape[:2]
                vcodec, vargs = _ffmpeg_av1_encoder(ff)
                # Matroska intermediate avoids fragile MP4-in-progress muxing; final mux targets user extension.
                fd, tmp_vid = tempfile.mkstemp(suffix="_ca_vup_av1_noaudio.mkv")
                os.close(fd)
                fd_err, fferr_path = tempfile.mkstemp(suffix="_ffmpeg.log")
                os.close(fd_err)
                cmd = [
                    ff,
                    "-y",
                    "-f",
                    "rawvideo",
                    "-vcodec",
                    "rawvideo",
                    "-s",
                    f"{ow}x{oh}",
                    "-pix_fmt",
                    "bgr24",
                    "-r",
                    str(fps),
                    "-i",
                    "-",
                    "-an",
                    "-c:v",
                    vcodec,
                    *vargs,
                    tmp_vid,
                ]
                err_f = None
                try:
                    err_f = open(fferr_path, "w", encoding="utf-8", errors="replace")
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=err_f,
                        bufsize=10**7,
                    )
                except Exception:
                    if err_f is not None:
                        try:
                            err_f.close()
                        except Exception:
                            pass
                    try:
                        os.unlink(fferr_path)
                    except OSError:
                        pass
                    raise
                assert proc.stdin is not None

                def write_frame(bgr):
                    if bgr.shape[1] != ow or bgr.shape[0] != oh:
                        bgr = cv2.resize(bgr, (ow, oh), interpolation=cv2.INTER_AREA)
                    # OpenCV frames may be stride-padded; rawvideo must be exactly w*h*3 bytes per frame.
                    tight = np.ascontiguousarray(np.asarray(bgr, dtype=np.uint8))
                    proc.stdin.write(tight.tobytes())

                write_frame(out0)
                done = 1
                if n > 0:
                    self._sig.progress_frames.emit(done, n)
                else:
                    self._sig.progress_frames.emit(done, 0)
                frame_i = 1
                while not self._cancel_job.is_set():
                    ok, fr = cap.read()
                    if not ok:
                        break
                    ae_i, c_i, sk_i, lu_i, ch_i = _frame_params(frame_i)
                    am_i = _artifact_mask_at(frame_i)
                    out = self._process_frame(
                        fr,
                        runner,
                        user_sc,
                        aesthetic=ae_i,
                        cast_strength=c_i,
                        skin_tone_strength=sk_i,
                        luma_nr_strength=lu_i,
                        chroma_nr_strength=ch_i,
                        artifact_mask=am_i,
                    )
                    frame_i += 1
                    write_frame(out)
                    done += 1
                    if n > 0:
                        self._sig.progress_frames.emit(done, n)
                    else:
                        self._sig.progress_frames.emit(done, 0)
                cap.release()
                proc.stdin.close()
                if err_f is not None:
                    try:
                        err_f.flush()
                        err_f.close()
                    except Exception:
                        pass
                    err_f = None
                self._sig.progress_frames.emit(0, _VUP_PROG_FFMPEG_PHASE)
                proc.wait(timeout=3600)
                ff_full = ""
                try:
                    with open(fferr_path, "r", errors="replace") as ef:
                        ff_full = ef.read()
                except OSError:
                    pass
                ff_tail = ff_full.strip()[-2500:].strip() if ff_full else ""
                try:
                    os.unlink(fferr_path)
                except OSError:
                    pass
                if proc.returncode != 0:
                    if ff_full.strip():
                        append_multiline(
                            UTILITY_APP,
                            "AI Video Upscaler · ffmpeg stderr (AV1 encode)",
                            ff_full,
                        )
                    detail = ff_tail.replace("\n", " ")[:1800] if ff_tail else ""
                    msg = (
                        "ERROR: ffmpeg AV1 encode failed "
                        f"(encoder={vcodec}; need a build with libsvtav1 or libaom-av1)."
                    )
                    if detail:
                        msg += f" ffmpeg: {detail}"
                    self._sig.log_msg.emit(msg)
                    return

                # Optional audio copy
                self._sig.progress_frames.emit(0, _VUP_PROG_MUX_PHASE)
                mux_cmd = [
                    ff,
                    "-y",
                    "-i",
                    tmp_vid,
                    "-i",
                    path,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0?",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    dest,
                ]
                try:
                    mx = subprocess.run(
                        mux_cmd,
                        capture_output=True,
                        timeout=3600,
                    )
                    if mx.returncode != 0:
                        mx_err = (mx.stderr or b"").decode("utf-8", errors="replace")
                        if mx_err.strip():
                            append_multiline(
                                UTILITY_APP,
                                "AI Video Upscaler · ffmpeg stderr (final mux)",
                                mx_err,
                            )
                        mxe = mx_err[-1500:].replace("\n", " ")
                        self._sig.log_msg.emit(
                            "ERROR: final mux failed; saving video-only. "
                            + (f"ffmpeg: {mxe}" if mxe.strip() else f"exit {mx.returncode}")
                        )
                        rv = subprocess.run(
                            [
                                ff,
                                "-y",
                                "-i",
                                tmp_vid,
                                "-map",
                                "0:v:0",
                                "-c:v",
                                "copy",
                                dest,
                            ],
                            capture_output=True,
                            timeout=3600,
                        )
                        if rv.returncode != 0:
                            rv_err = (rv.stderr or b"").decode("utf-8", errors="replace")
                            if rv_err.strip():
                                append_multiline(
                                    UTILITY_APP,
                                    "AI Video Upscaler · ffmpeg stderr (remux video-only)",
                                    rv_err,
                                )
                            rve = rv_err[-800:].replace("\n", " ")
                            self._sig.log_msg.emit(
                                "ERROR: could not remux AV1 to output file. "
                                + (rve if rve.strip() else f"exit {rv.returncode}")
                            )
                            return
                        self._sig.log_msg.emit("Saved video-only (mux failed; AV1 remuxed to output).")
                    else:
                        pass
                except (subprocess.CalledProcessError, OSError) as mux_e:
                    rv = subprocess.run(
                        [
                            ff,
                            "-y",
                            "-i",
                            tmp_vid,
                            "-map",
                            "0:v:0",
                            "-c:v",
                            "copy",
                            dest,
                        ],
                        capture_output=True,
                        timeout=3600,
                    )
                    if rv.returncode != 0:
                        self._sig.log_msg.emit(f"ERROR: could not write output: {mux_e}")
                        return
                    self._sig.log_msg.emit(
                        f"Saved video-only (audio mux skipped or unavailable): {mux_e}"
                    )
                self._last_output_path = dest
                self._sig.log_msg.emit(f"Done: {dest}")
            except Exception as e:
                from core.ai_inference_resources import (
                    REALESRGAN_VRAM_BASELINE_LOG,
                    USER_MSG_CUDA_OOM,
                )
                from core.gpu_errors import is_torch_cuda_oom

                if is_torch_cuda_oom(e):
                    log_exception(
                        e,
                        context="AI Video Upscaler · Real-ESRGAN CUDA OOM",
                        utility=UTILITY_APP,
                        extra=REALESRGAN_VRAM_BASELINE_LOG,
                    )
                    _vup_log.error("Real-ESRGAN OOM: %s | %s", e, REALESRGAN_VRAM_BASELINE_LOG)
                    self._sig.resource_warning.emit(USER_MSG_CUDA_OOM)
                    self._sig.log_msg.emit(
                        f"ERROR: {USER_MSG_CUDA_OOM} ({REALESRGAN_VRAM_BASELINE_LOG})"
                    )
                else:
                    self._sig.log_msg.emit(f"ERROR: {e}")
            finally:
                if tmp_vid and os.path.isfile(tmp_vid):
                    try:
                        os.unlink(tmp_vid)
                    except OSError:
                        pass
                if artifact_dir and os.path.isdir(artifact_dir):
                    shutil.rmtree(artifact_dir, ignore_errors=True)
                self._sig.full_job_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _finish_job_ui(self):
        self._job_in_progress = False
        if self._fs_holding_vup:
            release_fs_heavy()
            self._fs_holding_vup = False
        self._job_eta_start_mono = None
        self._noise_eta_start_mono = None
        self._vup_upscale_eta_started = False
        self._set_eta_idle()
        self._bar.setRange(0, 100)
        self._bar.setFormat("Ready")
        self._bar.setValue(0)
        self._update_buttons()
        self._notify_activity("idle")
        QTimer.singleShot(0, self._reload_preview_after_job)

    def _on_install_torch(self):
        if self._engine_just_installed:
            if restart_application():
                QApplication.instance().quit()
            return
        components, total_bytes = estimate_ml_runtime_components()
        lines = [
            "Install PyTorch + diffusers (same stack as AI Image Upscaler)?",
            "",
            f"Selected: {get_ml_torch_install_label()}",
            "",
            "Components:",
        ]
        for label, sz in components:
            lines.append(
                f"  • {label}: {fmt_bytes(sz)}" if sz > 0 else f"  • {label}"
            )
        lines.extend(["", f"Estimated total: {fmt_bytes(total_bytes)}", "", pytorch_installer_vram_guidance(), "", "Restart may be required."])
        if (
            QMessageBox.question(
                self,
                "Install PyTorch",
                "\n".join(lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._setup_in_progress = True
        self._pending_engine_install = True
        self._update_buttons()
        dlg = EngineSetupDialog(self, app_label=INSTALLER_APP_AI_VIDEO_UPSCALER)
        self._engine_setup_dialog = dlg
        dlg._lbl_components.setText(
            f"{get_ml_torch_install_label()}\n\n{pytorch_installer_vram_guidance()}\n\n"
            + "\n".join(
                [
                    f"  • {lbl}: {fmt_bytes(sz)}" if sz > 0 else f"  • {lbl}"
                    for lbl, sz in components
                ]
            )
            + f"\n\nEstimated total: {fmt_bytes(total_bytes)}"
        )

        def task():
            def prog(phase, detail, downloaded, total):
                dlg.phase_update.emit(phase, detail, downloaded, total)

            ok, err = install_ml_runtime(prog)
            self._sig.setup_complete.emit(("engine", ok, err))

        dlg.show()
        threading.Thread(target=task, daemon=True).start()

    def _on_uninstall_torch(self):
        if (
            QMessageBox.question(
                self,
                "Uninstall PyTorch",
                "Remove torch stack from this environment?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._setup_in_progress = True

        def task():
            uninstall_ml_runtime(None)
            self._sig.setup_complete.emit(("engine_uninstall", True, None))

        threading.Thread(target=task, daemon=True).start()

    def _on_download_weights(self):
        missing: list[tuple[str, int]] = []
        t_dl = 0
        for ns in (2, 4):
            if self._model_mgr.is_ready(ns):
                continue
            fn = model_filename_for_net_scale(ns)
            sz = expected_bytes(ns)
            missing.append((fn, sz))
            t_dl += sz
        if not self._lama_mgr.is_ready():
            missing.append((LAMA_FILENAME, APPROX_LAMA_BYTES))
            t_dl += APPROX_LAMA_BYTES
        if not missing:
            self._refresh_engine_labels()
            self._update_buttons()
            return

        lines = [
            "Download AI Video Upscaler weights to:",
            str(self._model_mgr._root),
            "",
            "Files to fetch:",
        ]
        for fn, sz in missing:
            lines.append(f"  • {fn} (~{fmt_bytes(sz)})")
        lines.extend(
            [
                "",
                f"Estimated data: ~{fmt_bytes(t_dl)}",
                "",
                "Real-ESRGAN: x2plus covers targets needing ≤2× on the long edge; larger targets use x4plus "
                "(with resize after the net). Both are required for full coverage.",
                "",
                f"{LAMA_FILENAME}: LaMa neural inpainting for artifact repair (optional Telea fallback if skipped).",
                "",
                "Proceed with download?",
            ]
        )
        if (
            QMessageBox.question(
                self,
                "Download AI Video weights",
                "\n".join(lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        self._setup_in_progress = True
        self._update_buttons()
        dlg = RealESRGANDownloadDialog(self)
        self._active_dl_dialog = dlg

        def prog(filename: str, downloaded: int, total: int):
            dlg.progress_update.emit(filename, downloaded, total)

        def task():
            ok, err = self._model_mgr.ensure_weights((2, 4), prog)
            if ok and not self._lama_mgr.is_ready():
                ok, err = self._lama_mgr.download(prog)
            self._sig.setup_complete.emit(("weights", ok, err))

        dlg.show()
        threading.Thread(target=task, daemon=True).start()

    def _on_remove_weights(self):
        if (
            QMessageBox.question(
                self,
                "Remove weights",
                "Delete downloaded Real-ESRGAN checkpoints and LaMa inpainting (big-lama.pt)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        for name in ("RealESRGAN_x2plus.pth", "RealESRGAN_x4plus.pth", LAMA_FILENAME):
            p = self._model_mgr._root / name
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
        self._runner = None
        self._runner_key = None
        self._lama_runner = None
        self._lama_runner_key = None
        self._refresh_engine_labels()
        self._update_buttons()

    def _on_setup_complete(self, payload: object):
        self._setup_in_progress = False
        if self._engine_setup_dialog:
            self._engine_setup_dialog.close()
            self._engine_setup_dialog = None
        if self._active_dl_dialog:
            self._active_dl_dialog.close()
            self._active_dl_dialog = None
        if isinstance(payload, tuple) and payload and payload[0] == "engine":
            ok = bool(payload[1])
            if ok:
                self._engine_just_installed = True
                self._add_log("PyTorch install finished — restart ChronoArchiver.")
            else:
                self._add_log(f"Install failed: {payload[2]}")
        elif isinstance(payload, tuple) and payload and payload[0] == "engine_uninstall":
            self._engine_just_installed = False
            self._runner = None
            self._runner_key = None
            self._lama_runner = None
            self._lama_runner_key = None
            self._add_log("PyTorch stack removed.")
        elif isinstance(payload, tuple) and payload and payload[0] == "weights":
            ok = bool(payload[1])
            err = str(payload[2]).strip() if len(payload) > 2 and payload[2] else ""
            if ok:
                self._add_log("AI Video weights ready (Real-ESRGAN x2/x4; LaMa optional).")
            else:
                self._add_log(f"Weight download failed: {err or 'unknown error'}")
                QMessageBox.warning(
                    self,
                    "AI Video weights",
                    f"Download did not finish successfully.\n\n{err or 'Unknown error.'}\n\n"
                    "Check your network, firewall, and that GitHub is reachable.",
                )
        # Defer FS-dependent row refresh to next event-loop tick so dialog teardown and
        # disk state match what the footer sees (singleShot(0, _refresh_footer) in app).
        QTimer.singleShot(0, self._apply_engine_row_after_setup)

    def _apply_engine_row_after_setup(self) -> None:
        self._refresh_engine_labels()
        self._update_buttons()
