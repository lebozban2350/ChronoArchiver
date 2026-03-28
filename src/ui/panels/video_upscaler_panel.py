"""
AI Video Upscaler — Real-ESRGAN (x2plus/x4plus), simple 2×/3×/4× choice, fixed cleanup pipeline, AV1 export.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
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
    upscaler_browse_btn_idle_qss,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.app_paths import settings_dir
from core.ml_runtime import (
    check_ml_runtime,
    install_ml_runtime,
    uninstall_ml_runtime,
    estimate_ml_runtime_components,
)
from core.realesrgan_models import (
    RealESRGANModelManager,
    expected_bytes,
    model_filename_for_net_scale,
    net_scale_for_user_scale,
)
from core.realesrgan_runner import RealESRGANRunner
from core.video_upscaler_settings import VideoUpscalerPanelSettings
from core.restart import restart_application
from core.venv_manager import get_ml_torch_install_label

from ui.panels.upscaler_panel import EngineSetupDialog

_VUP_RUN_W = 108
_VUP_RUN_H = 28

# User only selects scale (2×/3×/4×); rest is fixed “best effort” defaults.
VUP_MAX_EDGE = 3840
VUP_TILE = 400
VUP_UNSHARP_STRENGTH = 0.38  # one mild sharpen pass after upscale + denoise

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


def _denoise_bgr_one_step(bgr):
    """Single light noise-reduction pass (bilateral — fast enough per frame for HD/4K)."""
    import cv2

    if bgr is None or bgr.size == 0:
        return bgr
    return cv2.bilateralFilter(bgr, d=7, sigmaColor=72, sigmaSpace=72)


def _run_video_btn_stylesheet(*, pulse: bool = False) -> str:
    """Video UPSCALE (#btnStart): same geometry as image upscaler; guide pulse swaps border."""
    bd = "#ef4444" if pulse else "#10b981"
    w, h = _VUP_RUN_W, _VUP_RUN_H
    return (
        "QPushButton#btnStart {"
        "background-color:#10b981; color:#064e3b; "
        f"border:2px solid {bd}; "
        "font-size:10px; font-weight:900; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px; "
        "}"
        "QPushButton#btnStart:hover:enabled {"
        "background-color:#34d399; color:#064e3b; "
        f"border:2px solid {bd}; "
        "}"
        "QPushButton#btnStart:disabled {"
        "background-color:#1a1a1a; color:#6b7280; border:2px solid #262626; "
        "font-size:10px; font-weight:900; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px; "
        "}"
    )


def _ffmpeg_exe() -> str | None:
    return shutil.which("ffmpeg")


def _cap_long_edge_bgr(img, max_edge: int):
    import cv2

    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_edge:
        return img
    s = max_edge / m
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
        blur = cv2.GaussianBlur(out, (0, 0), 3)
        out = cv2.addWeighted(out, 1.0 + sharpness, blur, -sharpness, 0)
    return out


def _read_video_frame(path: str, frame_index: int):
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    idx = 0 if n <= 0 else max(0, min(n - 1, frame_index))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None


def _user_scale_from_index(i: int) -> float:
    return (2.0, 3.0, 4.0)[max(0, min(2, i))]


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
    full_job_done = Signal()


class RealESRGANDownloadDialog(QDialog):
    """Progress for one or sequential Real-ESRGAN .pth downloads (filename, bytes done, total)."""

    progress_update = Signal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Real-ESRGAN weights")
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


class VideoUpscalerPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sig = _Signals()
        # QueuedConnection: emissions from threading.Thread must run slots on the GUI thread
        # or labels/buttons may not repaint (weights/engine row stuck until restart).
        _q = Qt.ConnectionType.QueuedConnection
        self._sig.log_msg.connect(self._add_log, _q)
        self._sig.setup_complete.connect(self._on_setup_complete, _q)
        self._sig.progress_frames.connect(self._on_frame_progress, _q)
        self._sig.full_job_done.connect(self._finish_job_ui, _q)

        self._base = settings_dir() / "ai_video_upscaler"
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._model_mgr = RealESRGANModelManager(self._base / "models")
        self._prefs = VideoUpscalerPanelSettings(self._base)
        self._runner: RealESRGANRunner | None = None
        self._runner_key: tuple[int, int] | None = None

        self._setup_in_progress = False
        self._job_in_progress = False
        self._cancel_job = threading.Event()
        self._pending_engine_install = False
        self._engine_just_installed = False
        self._active_dl_dialog: QDialog | None = None
        self._engine_setup_dialog: EngineSetupDialog | None = None

        self._last_output_path: str | None = None

        _ctrl_h = 24
        _strip_eng = 84
        _ew, _eh = 82, 22
        self._eng_btn_w, self._eng_btn_h = _ew, _eh
        self._path_bar_h = _ctrl_h
        self._browse_btn_w = 64
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

        grp_src = QGroupBox("SOURCE")
        grp_src.setFixedHeight(_strip_eng)
        grp_src.setToolTip(
            "Pick a video; scale and UPSCALE live under Browse. Export uses fixed Real-ESRGAN + AV1 pipeline."
        )
        vs = QVBoxLayout(grp_src)
        vs.setContentsMargins(9, 2, 9, 2)
        vs.setSpacing(4)
        h_vid = QHBoxLayout()
        h_vid.setSpacing(8)
        h_vid.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        h_vid.addWidget(field_label("Video", 40))
        self._edit_video = QLineEdit()
        self._edit_video.setPlaceholderText("Path to video…")
        self._edit_video.setFixedHeight(_ctrl_h)
        self._edit_video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit_video.textChanged.connect(self._update_buttons)
        h_vid.addWidget(self._edit_video, 1)
        self._btn_browse = QPushButton("Browse…")
        self._btn_browse.setObjectName("browseBtn")
        self._btn_browse.setFixedSize(self._browse_btn_w, _ctrl_h)
        self._btn_browse.setStyleSheet(
            upscaler_browse_btn_idle_qss(self._path_bar_h, self._browse_btn_w)
        )
        self._btn_browse.clicked.connect(self._browse_video)
        h_vid.addWidget(self._btn_browse, 0, Qt.AlignmentFlag.AlignVCenter)
        vs.addLayout(h_vid)

        self._combo_scale = QComboBox()
        self._combo_scale.addItem("2×", 0)
        self._combo_scale.addItem("3×", 1)
        self._combo_scale.addItem("4×", 2)
        self._combo_scale.setCurrentIndex(2)
        self._combo_scale.setStyleSheet(_combo_style)
        self._combo_scale.setFixedSize(52, 22)
        self._combo_scale.setToolTip("Output size vs source (2×, 3×, or 4× on the long edge).")
        self._combo_scale.currentIndexChanged.connect(lambda *_: (self._refresh_engine_labels(), self._update_buttons()))

        self._btn_run = QPushButton("UPSCALE")
        self._btn_run.setObjectName("btnStart")
        self._btn_run.setFixedSize(_VUP_RUN_W, _VUP_RUN_H)
        self._btn_run.setStyleSheet(_run_video_btn_stylesheet(pulse=False))
        self._btn_run.setToolTip("Export AV1 video at the same frame rate as the source (optional audio mux).")
        self._btn_run.clicked.connect(self._run_full_job)

        h_scale_row = QHBoxLayout()
        h_scale_row.setSpacing(6)
        h_scale_row.addStretch(1)
        h_scale_row.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h_scale_row.addWidget(field_label("Scale", 40), 0, Qt.AlignmentFlag.AlignVCenter)
        h_scale_row.addWidget(self._combo_scale, 0, Qt.AlignmentFlag.AlignVCenter)
        h_scale_row.addWidget(self._btn_run, 0, Qt.AlignmentFlag.AlignVCenter)
        vs.addLayout(h_scale_row)
        vs.addStretch(1)

        grp_eng = QGroupBox("Engine Status")
        grp_eng.setFixedHeight(_strip_eng)
        grp_eng.setMinimumWidth(248)
        ve = QVBoxLayout(grp_eng)
        ve.setContentsMargins(4, 2, 4, 0)
        ve.setSpacing(2)
        h_pt = QHBoxLayout()
        h_pt.setSpacing(6)
        self._lbl_torch = QLabel("CHECKING…")
        self._lbl_torch.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_torch.setFixedWidth(106)
        lbl_pt = QLabel("PyTorch:", styleSheet="font-size:8px; color:#888;")
        lbl_pt.setFixedWidth(44)
        h_pt.addWidget(lbl_pt)
        h_pt.addWidget(self._lbl_torch)
        h_pt.addSpacing(4)
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
        h_md.setSpacing(6)
        self._lbl_weights = QLabel("CHECKING…")
        self._lbl_weights.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_weights.setFixedWidth(106)
        lbl_w = QLabel("Weights:", styleSheet="font-size:8px; color:#888;")
        lbl_w.setFixedWidth(44)
        h_md.addWidget(lbl_w)
        h_md.addWidget(self._lbl_weights)
        h_md.addSpacing(4)
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

        grp_prev = QGroupBox("Preview (sample frame from source)")
        hp = QHBoxLayout(grp_prev)
        hp.setContentsMargins(9, 4, 9, 7)
        fr_o = QFrame()
        fr_o.setObjectName("previewCard")
        vo = QVBoxLayout(fr_o)
        vo.setContentsMargins(2, 2, 2, 2)
        vo.addWidget(QLabel("Original", objectName="previewTitle"))
        self._lbl_orig = QLabel("No video")
        self._lbl_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Shorter preview column frees ~25% vertical min vs 320px; stretch favors console below.
        _prev_min_h = 240
        self._lbl_orig.setMinimumSize(280, _prev_min_h)
        self._lbl_orig.setStyleSheet("color:#3f3f46; font-size:10px;")
        vo.addWidget(self._lbl_orig, 1)
        hp.addWidget(fr_o, 1)
        sep = QFrame()
        sep.setFixedWidth(3)
        sep.setStyleSheet("background:#141414; border:none;")
        hp.addWidget(sep)
        fr_p = QFrame()
        fr_p.setObjectName("previewCard")
        vp = QVBoxLayout(fr_p)
        vp.setContentsMargins(2, 2, 2, 2)
        vp.addWidget(QLabel("AI preview", objectName="previewTitle"))
        self._lbl_prev = QLabel("—")
        self._lbl_prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_prev.setMinimumSize(280, _prev_min_h)
        self._lbl_prev.setStyleSheet("color:#3f3f46; font-size:10px;")
        vp.addWidget(self._lbl_prev, 1)
        hp.addWidget(fr_p, 1)
        # Preview vs console: bias slack to console (removed separate Upscale row).
        root.addWidget(grp_prev, 2)

        h_bar = QHBoxLayout()
        self._bar = QProgressBar()
        self._bar.setFixedHeight(14)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("Ready")
        self._bar.setVisible(False)
        h_bar.addWidget(self._bar, 1)
        root.addLayout(h_bar)

        grp_log = QGroupBox("Console")
        vl = QVBoxLayout(grp_log)
        v_log = QTextEdit()
        v_log.setObjectName("panelConsole")
        v_log.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        v_log.setReadOnly(True)
        v_log.setAcceptRichText(True)
        v_log.setMinimumHeight(120)
        vl.addWidget(v_log, 1)
        root.addWidget(grp_log, 3)
        self._log_edit = v_log

        self._load_prefs()
        self._edit_video.textChanged.connect(lambda *_: self._persist())
        self._combo_scale.currentIndexChanged.connect(lambda *_: self._persist())

        QTimer.singleShot(0, self._refresh_engine_labels)
        QTimer.singleShot(0, self._update_buttons)
        if self._edit_video.text().strip():
            QTimer.singleShot(50, self._load_video_preview_thumb)

    def _load_prefs(self):
        p = self._prefs.load()
        # Video path is session-only: survives switching internal panels, not app restart.
        self._edit_video.setText("")
        self._combo_scale.setCurrentIndex(int(p.get("scale_index", 2)))

    def _persist(self):
        self._prefs.save(
            {
                "source_video": "",
                "scale_index": self._combo_scale.currentIndex(),
            }
        )

    def get_activity(self) -> str:
        return "upscaling" if self._job_in_progress else "idle"

    def _add_log(self, msg: str):
        self._log_edit.moveCursor(self._log_edit.textCursor().End)
        self._log_edit.insertHtml(message_to_html(str(msg)))
        self._log_edit.insertPlainText("\n")

    def _refresh_engine_labels(self):
        ok, reason = check_ml_runtime()
        if self._engine_just_installed:
            self._lbl_torch.setText("RESTART REQUIRED")
            self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#eab308;")
            self._btn_inst_torch.setText("Restart app")
            self._btn_inst_torch.show()
            self._btn_rm_torch.hide()
        elif ok:
            try:
                import torch

                cuda = torch.cuda.is_available()
            except Exception:
                cuda = False
            self._lbl_torch.setText(f"READY · {'CUDA' if cuda else 'CPU'}")
            self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#10b981;")
            self._btn_inst_torch.hide()
            self._btn_rm_torch.show()
        else:
            self._lbl_torch.setText(reason.replace("_", " ").upper()[:18])
            self._lbl_torch.setStyleSheet("font-size:9px;font-weight:700;color:#ef4444;")
            self._btn_inst_torch.show()
            self._btn_rm_torch.hide()

        ns = net_scale_for_user_scale(_user_scale_from_index(self._combo_scale.currentIndex()))
        wr = self._model_mgr.is_ready(ns)
        if wr:
            self._lbl_weights.setText("READY")
            self._lbl_weights.setStyleSheet("font-size:9px;font-weight:700;color:#10b981;")
            self._btn_dl_weights.hide()
            self._btn_rm_weights.show()
        else:
            self._lbl_weights.setText("MISSING")
            self._lbl_weights.setStyleSheet("font-size:9px;font-weight:700;color:#ef4444;")
            self._btn_dl_weights.show()
            self._btn_rm_weights.hide()

    def _get_runner(self, net_scale: int) -> RealESRGANRunner:
        key = (net_scale, VUP_TILE)
        if self._runner is not None and self._runner_key == key:
            return self._runner
        mp = self._model_mgr.path_for_net_scale(net_scale)
        self._runner = RealESRGANRunner(
            mp, net_scale=net_scale, tile=VUP_TILE, pre_pad=10, half=True
        )
        self._runner_key = key
        return self._runner

    def _process_frame(self, bgr, runner: RealESRGANRunner, user_scale: float):
        up = runner.enhance(bgr, user_scale=float(user_scale))
        up = _cap_long_edge_bgr(up, VUP_MAX_EDGE)
        up = _denoise_bgr_one_step(up)
        up = _post_color_bgr(up, 0.0, 1.0, 1.0, VUP_UNSHARP_STRENGTH)
        return up

    def _update_buttons(self):
        path = self._edit_video.text().strip()
        path_ok = bool(path and os.path.isfile(path))
        ns = net_scale_for_user_scale(_user_scale_from_index(self._combo_scale.currentIndex()))
        w_ok = self._model_mgr.is_ready(ns)
        t_ok, _ = check_ml_runtime()
        busy = self._setup_in_progress or self._job_in_progress
        self._btn_run.setEnabled(path_ok and w_ok and t_ok and not busy and bool(_ffmpeg_exe()))
        self._btn_browse.setEnabled(not busy)
        self._btn_dl_weights.setEnabled(not busy)
        self._btn_rm_weights.setEnabled(not busy and w_ok)
        self._btn_inst_torch.setEnabled(not busy or self._engine_just_installed)
        self._btn_rm_torch.setEnabled(not busy and t_ok and not self._engine_just_installed)
        self._sync_guide_pulse()

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
        ns = net_scale_for_user_scale(_user_scale_from_index(self._combo_scale.currentIndex()))
        if not self._model_mgr.is_ready(ns):
            return self._btn_dl_weights
        path = self._edit_video.text().strip()
        if not path or not os.path.isfile(path):
            return self._btn_browse
        return self._btn_run

    def _clear_guide_glow(self, w):
        if not w:
            return
        ew, eh = self._eng_btn_w, self._eng_btn_h
        if w == self._btn_run:
            w.setStyleSheet(_run_video_btn_stylesheet(pulse=False))
        elif w == self._btn_browse:
            w.setStyleSheet(
                upscaler_browse_btn_idle_qss(self._path_bar_h, self._browse_btn_w)
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
        if target == self._btn_run and not self._btn_run.isEnabled():
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
                target.setStyleSheet(_run_video_btn_stylesheet(pulse=True))
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

    def _load_video_preview_thumb(self):
        path = self._edit_video.text().strip()
        if not path or not os.path.isfile(path):
            self._lbl_orig.setText("No video")
            self._lbl_orig.setPixmap(QPixmap())
            return
        import cv2

        cap = cv2.VideoCapture(path)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        idx = max(0, n // 10) if n > 0 else 0
        fr = _read_video_frame(path, idx)
        if fr is None:
            self._lbl_orig.setText("Unreadable")
            return
        self._lbl_orig.setPixmap(_pixmap_from_bgr(fr))
        self._lbl_orig.setText("")
        self._lbl_prev.setText("—")
        self._lbl_prev.setPixmap(QPixmap())

    def _on_frame_progress(self, cur: int, total: int):
        if total <= 0:
            return
        self._bar.setVisible(True)
        self._bar.setRange(0, 100)
        self._bar.setValue(int(100 * cur / total))
        self._bar.setFormat(f"{cur} / {total} frames")

    def _run_full_job(self):
        path = self._edit_video.text().strip()
        ff = _ffmpeg_exe()
        if not ff:
            QMessageBox.warning(self, "FFmpeg", "FFmpeg not found in PATH.")
            return
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
        self._cancel_job.clear()
        self._job_in_progress = True
        self._bar.setVisible(True)
        self._bar.setValue(0)
        self._update_buttons()
        self._add_log(f"Starting upscale → {dest}")
        ns = net_scale_for_user_scale(_user_scale_from_index(self._combo_scale.currentIndex()))
        user_sc = _user_scale_from_index(self._combo_scale.currentIndex())

        try:
            runner = self._get_runner(ns)
        except Exception as e:
            self._job_in_progress = False
            self._bar.setVisible(False)
            self._update_buttons()
            self._add_log(f"ERROR: {e}")
            return

        def work():
            import cv2

            tmp_vid = None
            try:
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
                out0 = self._process_frame(fr0, runner, user_sc)
                oh, ow = out0.shape[:2]
                vcodec, vargs = _ffmpeg_av1_encoder(ff)
                fd, tmp_vid = tempfile.mkstemp(suffix="_ca_vup_av1_noaudio.mp4")
                os.close(fd)
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
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=10**7,
                )
                assert proc.stdin is not None

                def write_frame(bgr):
                    if bgr.shape[1] != ow or bgr.shape[0] != oh:
                        bgr = cv2.resize(bgr, (ow, oh), interpolation=cv2.INTER_AREA)
                    proc.stdin.write(bgr.tobytes())

                write_frame(out0)
                done = 1
                if n > 0:
                    self._sig.progress_frames.emit(done, n)
                while not self._cancel_job.is_set():
                    ok, fr = cap.read()
                    if not ok:
                        break
                    out = self._process_frame(fr, runner, user_sc)
                    write_frame(out)
                    done += 1
                    if n > 0:
                        self._sig.progress_frames.emit(done, n)
                cap.release()
                proc.stdin.close()
                proc.wait(timeout=3600)
                if proc.returncode != 0:
                    self._sig.log_msg.emit(
                        f"ffmpeg AV1 encode failed (encoder={vcodec}; need ffmpeg with libsvtav1 or libaom-av1)."
                    )
                    return

                # Optional audio copy
                try:
                    subprocess.run(
                        [
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
                        ],
                        check=True,
                        capture_output=True,
                        timeout=3600,
                    )
                except (subprocess.CalledProcessError, OSError):
                    shutil.copy2(tmp_vid, dest)
                    self._sig.log_msg.emit("Saved video-only (audio mux skipped or unavailable).")
                self._last_output_path = dest
                self._sig.log_msg.emit(f"Done: {dest}")
            except Exception as e:
                self._sig.log_msg.emit(f"ERROR: {e}")
            finally:
                if tmp_vid and os.path.isfile(tmp_vid):
                    try:
                        os.unlink(tmp_vid)
                    except OSError:
                        pass
                self._sig.full_job_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _finish_job_ui(self):
        self._job_in_progress = False
        self._bar.setFormat("Ready")
        self._bar.setValue(0)
        self._bar.setVisible(False)
        self._update_buttons()

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
            lines.append(f"  • {label}: {fmt_bytes(sz)}")
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
        dlg = EngineSetupDialog(self)
        self._engine_setup_dialog = dlg
        dlg._lbl_components.setText(
            f"{get_ml_torch_install_label()}\n\n{pytorch_installer_vram_guidance()}\n\n"
            + "\n".join([f"  • {lbl}: {fmt_bytes(sz)}" for lbl, sz in components])
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
        if not missing:
            self._refresh_engine_labels()
            self._update_buttons()
            return

        lines = [
            "Download Real-ESRGAN checkpoints to:",
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
                "2× scale needs x2plus; 3× / 4× need x4plus. Both are required for full app pre-reqs.",
                "",
                "Proceed with download?",
            ]
        )
        if (
            QMessageBox.question(
                self,
                "Download Real-ESRGAN weights",
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
            self._sig.setup_complete.emit(("weights", ok, err))

        dlg.show()
        threading.Thread(target=task, daemon=True).start()

    def _on_remove_weights(self):
        if (
            QMessageBox.question(
                self,
                "Remove weights",
                "Delete downloaded Real-ESRGAN .pth files?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        for name in ("RealESRGAN_x2plus.pth", "RealESRGAN_x4plus.pth"):
            p = self._model_mgr._root / name
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
        self._runner = None
        self._runner_key = None
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
            self._add_log("PyTorch stack removed.")
        elif isinstance(payload, tuple) and payload and payload[0] == "weights":
            ok = bool(payload[1])
            err = str(payload[2]).strip() if len(payload) > 2 and payload[2] else ""
            if ok:
                self._add_log("Real-ESRGAN weights ready (x2plus / x4plus as needed).")
            else:
                self._add_log(f"Weight download failed: {err or 'unknown error'}")
                QMessageBox.warning(
                    self,
                    "Real-ESRGAN weights",
                    f"Download did not finish successfully.\n\n{err or 'Unknown error.'}\n\n"
                    "Check your network, firewall, and that GitHub is reachable.",
                )
        # Defer FS-dependent row refresh to next event-loop tick so dialog teardown and
        # disk state match what the footer sees (singleShot(0, _refresh_footer) in app).
        QTimer.singleShot(0, self._apply_engine_row_after_setup)

    def _apply_engine_row_after_setup(self) -> None:
        self._refresh_engine_labels()
        self._update_buttons()
