"""
AI Image Upscaler panel for ChronoArchiver (Z-Image-Turbo; PyTorch row + models row, engine setup).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tempfile
from pathlib import Path
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QCloseEvent, QIcon, QImage, QPixmap, QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
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
    QStyle,
    QToolButton,
    QCheckBox,
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

from PIL import Image, ImageOps

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.app_paths import settings_dir
from core.debug_logger import (
    INSTALLER_APP_AI_IMAGE_UPSCALER,
    UTILITY_APP,
    log_exception,
    log_installer_popup,
    debug as _debug_installer,
    UTILITY_INSTALLER_POPUP,
)
from core.upscaler_settings import UpscalerPanelSettings
from core.venv_manager import format_pytorch_ready_line, get_ml_torch_install_label
from core.ml_runtime import (
    check_ml_runtime,
    install_ml_runtime,
    uninstall_ml_runtime,
    estimate_ml_runtime_components,
)
from core.lama_inpaint_models import LamaInpaintModelManager
from core.lama_inpaint_runner import LamaInpaintRunner
from core.model_manager import REPO_ID, ZImageModelManager
from core.network_status import (
    NO_NETWORK_LABEL_STYLE_9,
    NO_NETWORK_MESSAGE,
    is_network_reachable,
)
from core.restart import restart_application
from core.zimage_engine import ZImageUpscaleEngine
from core.zimage_auto_params import infer_zimage_params
from core.zimage_beautify_prompts import PIKASO_HIGH_END_SKIN_SPACE_URL
from core.beautify_visual_analysis import analyze_beautify_imperfections
from core.zimage_portrait import portrait_signals_from_path_detailed


def _run_upscale_btn_stylesheet(*, pulse: bool = False) -> str:
    """Run upscale (#btnStart): same geometry/fonts always; guide pulse only changes border color."""
    bd = "#ef4444" if pulse else "#10b981"
    return (
        "QPushButton#btnStart {"
        "background-color:#10b981; color:#064e3b; "
        f"border:2px solid {bd}; "
        "font-size:10px; font-weight:900; "
        "min-width:108px; max-width:108px; min-height:28px; max-height:28px; padding:0px; "
        "}"
        "QPushButton#btnStart:hover:enabled {"
        "background-color:#34d399; color:#064e3b; "
        f"border:2px solid {bd}; "
        "}"
        "QPushButton#btnStart:disabled {"
        "background-color:#1a1a1a; color:#6b7280; border:2px solid #262626; "
        "font-size:10px; font-weight:900; "
        "min-width:108px; max-width:108px; min-height:28px; max-height:28px; padding:0px; "
        "}"
    )


class _Signals(QObject):
    log_msg = Signal(str)
    setup_complete = Signal(object)
    upscale_done = Signal(object)
    upscale_failed = Signal(str)


class EngineSetupDialog(QDialog):
    """Same pattern as ChronoArchiver OpenCVSetupDialog — pip install progress."""

    phase_update = Signal(str, str, int, int)

    def __init__(self, parent=None, *, app_label: str = INSTALLER_APP_AI_IMAGE_UPSCALER):
        super().__init__(parent)
        self._app_label = app_label
        self._last_logged_phase: str | None = None
        self._last_progress_log_ts = 0.0
        self.setWindowTitle("PyTorch & diffusers setup")
        self.setModal(False)
        self.setFixedSize(460, 248)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl_phase = QLabel("Preparing...")
        self._lbl_phase.setStyleSheet("font-size: 10px; font-weight: 600; color: #10b981;")
        v.addWidget(self._lbl_phase)
        self._lbl_components = QLabel("")
        self._lbl_components.setStyleSheet("font-size: 8px; color: #6b7280;")
        self._lbl_components.setWordWrap(True)
        v.addWidget(self._lbl_components)
        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("font-size: 8px; color: #6b7280;")
        v.addWidget(self._lbl_detail)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(14)
        self._bar.setFormat("%p%")
        v.addWidget(self._bar)
        v.addStretch()
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self.phase_update.connect(self._on_phase_update)
        self._net_spd_t: float | None = None
        self._net_spd_b: int = 0

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        log_installer_popup(self._app_label, "EngineSetupDialog", "opened")

    def closeEvent(self, event: QCloseEvent) -> None:
        log_installer_popup(self._app_label, "EngineSetupDialog", "closed")
        super().closeEvent(event)

    def _on_phase_update(self, phase: str, detail: str, downloaded: int, total: int):
        self._lbl_phase.setText(phase)
        now = time.monotonic()
        spd = ""
        if downloaded == 0 or (self._net_spd_b and downloaded < self._net_spd_b):
            self._net_spd_t = None
            self._net_spd_b = 0
        if total > 0 and downloaded > 0 and self._net_spd_t is not None and downloaded > self._net_spd_b:
            dt = now - self._net_spd_t
            if dt > 1e-6:
                bps = (downloaded - self._net_spd_b) / dt
                spd = f" · {format_net_speed(bps)}"
        if total > 0 and downloaded >= 0:
            self._net_spd_t = now
            self._net_spd_b = downloaded
            pct = min(100, int(100 * downloaded / total)) if total else 0
            self._bar.setRange(0, 100)
            self._bar.setValue(pct)
            self._bar.setFormat("%p%")
            gb_d = downloaded / (1024**3)
            gb_t = total / (1024**3)
            if gb_t >= 0.1:
                size_str = f"{gb_d:.2f} / {gb_t:.2f} GB"
            else:
                mb_d = downloaded / (1024 * 1024)
                mb_t = total / (1024 * 1024)
                size_str = f"{mb_d:.0f} / {mb_t:.0f} MB"
            tail = f"{size_str}{spd}  ·  {detail}" if detail else f"{size_str}{spd}"
            self._lbl_detail.setText(tail)
        else:
            self._lbl_detail.setText(detail[:120] if detail else "")
        now = time.monotonic()
        if phase != self._last_logged_phase or (now - self._last_progress_log_ts) >= 2.0:
            self._last_logged_phase = phase
            self._last_progress_log_ts = now
            log_installer_popup(
                self._app_label,
                "EngineSetupDialog",
                "progress",
                f"phase={phase!r} downloaded={downloaded} total={total} detail={(detail or '')[:120]!r}",
            )


class ZImageModelSetupDialog(QDialog):
    """Same pattern as ChronoArchiver ModelSetupDialog (AI Scanner)."""

    progress_update = Signal(str, str, str, int, int, float)

    def __init__(self, model_mgr: ZImageModelManager, parent=None):
        super().__init__(parent)
        self._model_mgr = model_mgr
        self.setWindowTitle("AI Model Setup")
        self.setModal(False)
        self.setFixedSize(420, 220)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)

        self._lbl_url = QLabel("Connecting...")
        self._lbl_url.setStyleSheet("font-size: 9px; color: #6b7280;")
        self._lbl_url.setWordWrap(True)
        v.addWidget(self._lbl_url)

        self._lbl_model = QLabel("")
        self._lbl_model.setStyleSheet("font-size: 10px; font-weight: 600; color: #10b981;")
        v.addWidget(self._lbl_model)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(14)
        self._bar.setFormat("%p%")
        v.addWidget(self._bar)

        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("font-size: 8px; color: #6b7280;")
        v.addWidget(self._lbl_detail)

        v.addStretch()
        h = QHBoxLayout()
        h.addStretch()
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setStyleSheet("font-size: 9px;")
        self._btn_cancel.clicked.connect(self._on_cancel)
        h.addWidget(self._btn_cancel)
        v.addLayout(h)

        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self.progress_update.connect(self.update_progress)
        self._net_spd_key = ""
        self._net_spd_t: float | None = None
        self._net_spd_b: int = 0
        self._last_zimage_log_key: str | None = None
        self._last_zimage_log_ts = 0.0

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        log_installer_popup(INSTALLER_APP_AI_IMAGE_UPSCALER, "ZImageModelSetupDialog", "opened")

    def closeEvent(self, event: QCloseEvent) -> None:
        log_installer_popup(INSTALLER_APP_AI_IMAGE_UPSCALER, "ZImageModelSetupDialog", "closed")
        super().closeEvent(event)

    def _on_cancel(self):
        log_installer_popup(INSTALLER_APP_AI_IMAGE_UPSCALER, "ZImageModelSetupDialog", "cancel_requested")
        self._model_mgr.cancel()
        self._btn_cancel.setEnabled(False)
        self._lbl_model.setText("Cancelling...")

    def update_progress(self, url: str, label: str, filename: str, downloaded: int, total: int, overall: float):
        if self._bar.minimum() == 0 and self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._lbl_url.setText(f"From: {url[:70]}..." if len(url) > 70 else f"From: {url}")
        now = time.monotonic()
        special = filename.startswith("Extracting") or "Installing models" in filename or filename == "Verifying"
        if special:
            self._net_spd_key = ""
            self._net_spd_t = None
            self._net_spd_b = 0
            self._lbl_model.setText("Installing models... please wait...")
            self._lbl_detail.setText("")
        else:
            if filename != self._net_spd_key:
                self._net_spd_key = filename
                self._net_spd_t = None
                self._net_spd_b = 0
            if self._net_spd_b and downloaded < self._net_spd_b:
                self._net_spd_t = None
                self._net_spd_b = 0
            spd_suffix = ""
            if downloaded > 0 and self._net_spd_t is not None and downloaded > self._net_spd_b:
                dt = now - self._net_spd_t
                if dt > 1e-6:
                    spd_suffix = f" · {format_net_speed((downloaded - self._net_spd_b) / dt)}"
            self._lbl_model.setText(f"Downloading: {label} ({filename})")
            if total > 0:
                mb_d = downloaded / (1024 * 1024)
                mb_t = total / (1024 * 1024)
                if mb_t >= 0.01:
                    self._lbl_detail.setText(f"{mb_d:.2f} / {mb_t:.2f} MB{spd_suffix}")
                else:
                    kb_d = downloaded / 1024
                    kb_t = total / 1024
                    self._lbl_detail.setText(f"{kb_d:.1f} / {kb_t:.1f} KB{spd_suffix}")
            else:
                self._lbl_detail.setText(f"{downloaded:,} bytes{spd_suffix}")
            self._net_spd_t = now
            self._net_spd_b = downloaded

        pct = int(overall * 100)
        self._bar.setValue(min(100, pct))
        now = time.monotonic()
        log_key = f"{label}|{filename}|{pct}"
        if log_key != self._last_zimage_log_key or (now - self._last_zimage_log_ts) >= 2.0:
            self._last_zimage_log_key = log_key
            self._last_zimage_log_ts = now
            log_installer_popup(
                INSTALLER_APP_AI_IMAGE_UPSCALER,
                "ZImageModelSetupDialog",
                "progress",
                f"label={label!r} file={filename[:100]!r} pct={pct} overall={overall:.4f}",
            )


class AIImageUpscalerPanel(QWidget):
    """Formerly named ``ZImageProUpscalerPanel`` — AI image refinement upscaler."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sig = _Signals()
        _q = Qt.ConnectionType.QueuedConnection
        self._sig.log_msg.connect(self._add_log, _q)
        self._sig.setup_complete.connect(self._on_setup_complete_generic, _q)
        self._sig.upscale_done.connect(self._on_upscale_done, _q)
        self._sig.upscale_failed.connect(self._on_upscale_failed, _q)

        # Keep Upscaler state under ChronoArchiver/Settings (user request: settings/stuff lives there).
        self._z_settings = settings_dir() / "z_image_pro_upscaler"
        try:
            self._z_settings.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._model_mgr = ZImageModelManager(self._z_settings / "models")
        self._lama_mgr = LamaInpaintModelManager(settings_dir() / "ai_video_upscaler" / "models")
        self._lama_runner: LamaInpaintRunner | None = None
        self._lama_runner_key: str | None = None
        self._engine = ZImageUpscaleEngine(self._model_mgr.snapshot_dir)
        self._panel_prefs = UpscalerPanelSettings(self._z_settings)
        self._loading_panel_prefs = False
        self._setup_in_progress = False
        self._upscale_in_progress = False
        self._last_result = None
        self._source_path = ""
        self._engine_just_installed = False
        self._pending_setup_kind: str | None = None
        self._active_setup_dialog: QDialog | None = None
        self._runtime_cache_ok: bool = False
        self._runtime_cache_reason: str = "unknown"
        self._runtime_cache_ts: float = 0.0
        self._runtime_cache_ttl_s: float = 2.5

        # Photo edit / preview state (rotate / crop / flip / zoom).
        self._preview_zoom: float = 1.0
        self._preview_resize_timer = QTimer(self)
        self._preview_resize_timer.setSingleShot(True)
        self._preview_resize_timer.setInterval(75)
        self._preview_resize_timer.timeout.connect(self._refresh_previews_for_zoom_only)
        self._work_pil: Image.Image | None = None
        self._edited_path: str | None = None
        # Working edited image written under Settings so the engine always uses final adjusted pixels.
        self._edit_dir: Path = self._z_settings / "work"
        try:
            self._edit_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback to temp dir if settings isn't writable.
            self._edit_dir = Path(tempfile.mkdtemp(prefix="zimage_pro_upscaler_edit_"))
        self._edited_tmp_png: Path = self._edit_dir / "edited.png"

        # Undo stack (pixel edits only) — keep last 10 steps.
        self._undo_stack: deque[Image.Image] = deque(maxlen=10)

        # SOURCE strip: single path row (28px) + GroupBox chrome — shorter than Engine Status.
        # Engine Status: PyTorch + Models rows only (no footer hint label).
        # Source path row: same height as Media Organizer / Encoder / Scanner (_bar_h=28, browse 60×28).
        _strip_src = 56
        _strip_eng = 72
        _bar_h = 28
        _browse_w, _browse_h = 60, _bar_h
        _src_edit_ss = (
            f"color:#fff; font-size:11px; font-weight:500; background:#121212; border:1px solid #1a1a1a; "
            f"padding:2px 6px; min-height:{_bar_h}px; max-height:{_bar_h}px;"
        )
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

        grp_opts = QGroupBox("SOURCE")
        grp_opts.setFixedHeight(_strip_src)
        grp_opts.setToolTip(
            "Optional artifact cleanup (LaMa or OpenCV Telea) on detected problem regions, then "
            "LANCZOS resize to target resolution, then Z-Image-Turbo img2img for refinement."
        )
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(9, 2, 9, 3)
        v_opts.setSpacing(0)

        h_img = QHBoxLayout()
        h_img.setSpacing(6)
        h_img.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        h_img.addWidget(field_label("Image", 40))
        self._edit_image = QLineEdit()
        self._edit_image.setPlaceholderText("Path to image…")
        self._edit_image.setStyleSheet(_src_edit_ss)
        self._edit_image.setFixedHeight(_bar_h)
        self._edit_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit_image.textChanged.connect(self._update_buttons)
        h_img.addWidget(self._edit_image, 1)
        self._btn_browse_img = QPushButton("Browse")
        self._btn_browse_img.setObjectName("browseBtn")
        self._btn_browse_img.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_img.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._btn_browse_img.setStyleSheet(
            path_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#262626", "#aaa")
        )
        self._btn_browse_img.clicked.connect(self._browse_image)
        h_img.addWidget(self._btn_browse_img, 0, Qt.AlignmentFlag.AlignVCenter)
        v_opts.addLayout(h_img)

        grp_mod = QGroupBox("Engine Status")
        grp_mod.setFixedHeight(_strip_eng)
        grp_mod.setMinimumWidth(248)
        grp_mod.setToolTip(
            "All inference is local.\n\n"
            "• Z-Image-Turbo (Setup Models) — one HF snapshot for upscale, cleanup, and Beautify "
            "(same weights; Beautify uses stronger img2img + magazine-style prompts than plain upscale).\n"
            "• OpenCV — face region for Beautify crops.\n"
            "• BLIP (image-captioning-base) — full face + split facial regions (heuristic zones) before img2img; "
            "first run downloads ~1 GB into the Hugging Face cache.\n\n"
            "No Freepik/cloud APIs. Beautify analysis uses local BLIP (separate HF download, ~1 GB once)."
        )
        v_mod = QVBoxLayout(grp_mod)
        v_mod.setContentsMargins(4, 2, 4, 2)
        v_mod.setSpacing(2)

        h_pt = QHBoxLayout()
        h_pt.setSpacing(2)
        self._lbl_pytorch = QLabel("CHECKING…")
        self._lbl_pytorch.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_pytorch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lbl_pytorch.setWordWrap(False)
        lbl_pt = QLabel("PyTorch:", styleSheet="font-size:8px; color:#888;")
        lbl_pt.setFixedWidth(44)
        h_pt.addWidget(lbl_pt)
        h_pt.addWidget(self._lbl_pytorch, 1)
        h_pt.addSpacing(2)
        self._btn_install_engine = QPushButton("Install PyTorch")
        self._btn_install_engine.setFixedSize(_ew, _eh)
        self._btn_install_engine.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_install_engine.clicked.connect(self._on_install_engine_clicked)
        self._btn_uninstall_engine = QPushButton("Uninstall PyTorch")
        self._btn_uninstall_engine.setFixedSize(_ew, _eh)
        self._btn_uninstall_engine.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_uninstall_engine.clicked.connect(self._on_uninstall_engine)
        h_pt.addWidget(self._btn_install_engine)
        h_pt.addWidget(self._btn_uninstall_engine)
        v_mod.addLayout(h_pt)

        h_md = QHBoxLayout()
        h_md.setSpacing(2)
        self._lbl_model = QLabel("CHECKING…")
        self._lbl_model.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
        self._lbl_model.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lbl_model.setWordWrap(False)
        lbl_md = QLabel("Models:", styleSheet="font-size:8px; color:#888;")
        lbl_md.setFixedWidth(44)
        lbl_md.setToolTip(
            "Z-Image-Turbo weights cover upscale and Beautify (same download). "
            "Setup Models may also fetch optional LaMa weights (shared with AI Video Upscaler) for neural cleanup; "
            "otherwise OpenCV Telea is used. OpenCV is bundled for face/freckle hints — no extra model files."
        )
        h_md.addWidget(lbl_md)
        h_md.addWidget(self._lbl_model, 1)
        h_md.addSpacing(2)
        self._btn_update_models = QPushButton("Update!")
        self._btn_update_models.setFixedSize(_ew, _eh)
        self._btn_update_models.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#eab308", "#eab308"))
        self._btn_update_models.clicked.connect(self._setup_models_only)
        self._btn_update_models.hide()
        self._btn_setup_models = QPushButton("Setup Models")
        self._btn_setup_models.setFixedSize(_ew, _eh)
        self._btn_setup_models.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_setup_models.clicked.connect(self._on_setup_models)
        self._btn_uninstall_models = QPushButton("Uninstall Models")
        self._btn_uninstall_models.setFixedSize(_ew, _eh)
        self._btn_uninstall_models.setStyleSheet(eng_row_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_uninstall_models.setToolTip(
            "Remove Z-Image-Turbo snapshot only (upscale + Beautify). OpenCV is not removed."
        )
        self._btn_uninstall_models.clicked.connect(self._on_remove_models)
        h_md.addWidget(self._btn_update_models)
        h_md.addWidget(self._btn_setup_models)
        h_md.addWidget(self._btn_uninstall_models)
        v_mod.addLayout(h_md)
        left_strip_col = QWidget()
        left_strip_col.setFixedHeight(_strip_src)
        v_left_strip = QVBoxLayout(left_strip_col)
        v_left_strip.setContentsMargins(0, 0, 0, 0)
        v_left_strip.setSpacing(0)
        v_left_strip.addWidget(grp_opts)
        h_strip.addWidget(left_strip_col, 7)
        h_strip.addWidget(grp_mod, 3)
        root.addLayout(h_strip)

        # PNGs under ui/panels/assets/upscaler/ — only for the strip between the two vertical separators
        # (undo/reset and the Original preview row use Qt standard icons only).
        icons_dir = Path(__file__).resolve().parent / "assets" / "upscaler"

        def _mk_tool_btn(
            icon_sp: QStyle.StandardPixmap, tip: str, handler, file_name: str | None = None
        ) -> QToolButton:
            btn = QToolButton()
            btn.setToolTip(tip)
            custom_icon = None
            if file_name:
                p = icons_dir / file_name
                if p.is_file():
                    custom_icon = QIcon(str(p))
            btn.setIcon(custom_icon if custom_icon and not custom_icon.isNull() else self.style().standardIcon(icon_sp))
            btn.setIconSize(QSize(18, 18))
            btn.setFixedSize(28, 28)
            btn.setStyleSheet("background-color:#181818; border:1px solid #2a2a2a; border-radius:3px;")
            btn.clicked.connect(handler)
            return btn

        grp_prev = QGroupBox("Preview")
        h_prev = QHBoxLayout(grp_prev)
        h_prev.setContentsMargins(9, 4, 9, 7)
        h_prev.setSpacing(10)

        fr_o = QFrame()
        fr_o.setObjectName("previewCard")
        fr_o.setFrameShape(QFrame.Shape.NoFrame)
        vo = QVBoxLayout(fr_o)
        vo.setContentsMargins(2, 2, 2, 2)
        vo.setSpacing(2)
        pt_o = QLabel("Original")
        pt_o.setObjectName("previewTitle")
        vo.addWidget(pt_o)
        self._lbl_orig = QLabel("No image")
        self._lbl_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_orig.setMinimumSize(280, 280)
        self._lbl_orig.setStyleSheet("color:#3f3f46; font-size:10px;")
        vo.addWidget(self._lbl_orig, 1)
        h_prev.addWidget(fr_o, 1)

        sep = QFrame()
        sep.setFixedWidth(3)
        sep.setStyleSheet("background:#141414; border:none;")
        h_prev.addWidget(sep, 0)

        fr_u = QFrame()
        fr_u.setObjectName("previewCard")
        fr_u.setFrameShape(QFrame.Shape.NoFrame)
        vu = QVBoxLayout(fr_u)
        vu.setContentsMargins(2, 2, 2, 2)
        vu.setSpacing(2)
        pt_u = QLabel("Upscaled + AI")
        pt_u.setObjectName("previewTitle")
        vu.addWidget(pt_u)
        self._lbl_up = QLabel("—")
        self._lbl_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_up.setMinimumSize(280, 280)
        self._lbl_up.setStyleSheet("color:#3f3f46; font-size:10px;")
        vu.addWidget(self._lbl_up, 1)
        h_prev.addWidget(fr_u, 1)
        root.addWidget(grp_prev, 3)

        h_tools_root = QHBoxLayout()
        h_tools_root.setContentsMargins(0, 0, 0, 0)
        h_tools_root.setSpacing(8)

        grp_src_tools = QGroupBox("Source Photo Adjustment Tools")
        v_src_tools = QVBoxLayout(grp_src_tools)
        v_src_tools.setContentsMargins(7, 3, 7, 3)
        v_src_tools.setSpacing(4)

        h_src_tools = QHBoxLayout()
        h_src_tools.setSpacing(6)
        # UNDO + counter (left aligned)
        self._btn_undo = _mk_tool_btn(
            QStyle.StandardPixmap.SP_ArrowBack, "Undo last edit", self._undo_last, None
        )
        self._lbl_undo_left = QLabel("0")
        self._lbl_undo_left.setToolTip("Undos left")
        self._lbl_undo_left.setFixedWidth(16)
        self._lbl_undo_left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_undo_left.setStyleSheet("color:#6b7280; font-size:9px; font-weight:800;")
        self._btn_undo.setEnabled(False)

        # PNG icons only between separators; undo/reset use Qt standard (above).
        self._btn_rot_left = _mk_tool_btn(
            QStyle.StandardPixmap.SP_ArrowBack, "Rotate left 90°", self._rotate_left, "rotate_left_90.png"
        )
        self._btn_rot_right = _mk_tool_btn(
            QStyle.StandardPixmap.SP_ArrowForward, "Rotate right 90°", self._rotate_right, "rotate_right_90.png"
        )
        self._btn_flip_h = _mk_tool_btn(
            QStyle.StandardPixmap.SP_BrowserReload, "Flip horizontal", self._flip_horizontal, "flip_horizontal.png"
        )
        self._btn_flip_v = _mk_tool_btn(
            QStyle.StandardPixmap.SP_BrowserStop, "Flip vertical", self._flip_vertical, "flip_vertical.png"
        )
        self._btn_zoom_out = _mk_tool_btn(
            QStyle.StandardPixmap.SP_MediaSeekBackward, "Zoom out (preview)", self._zoom_out_preview, "zoom_out.png"
        )
        self._btn_zoom_in = _mk_tool_btn(
            QStyle.StandardPixmap.SP_MediaSeekForward, "Zoom in (preview)", self._zoom_in_preview, "zoom_in.png"
        )
        self._btn_crop = _mk_tool_btn(
            QStyle.StandardPixmap.SP_FileDialogDetailedView, "Center crop (basic)", self._crop_center, "crop.png"
        )
        # RESET (right aligned) — Qt icon only
        self._btn_reset_edits = _mk_tool_btn(
            QStyle.StandardPixmap.SP_DialogResetButton, "Reset edits", self._reset_edits, None
        )

        def _vsep() -> QFrame:
            s = QFrame()
            s.setFixedWidth(1)
            s.setStyleSheet("background:#141414; border:none;")
            return s

        h_src_tools.addWidget(self._btn_undo)
        h_src_tools.addWidget(self._lbl_undo_left)
        h_src_tools.addStretch(1)

        h_src_tools.addWidget(_vsep())
        h_src_tools.addWidget(self._btn_rot_left)
        h_src_tools.addWidget(self._btn_rot_right)
        h_src_tools.addWidget(self._btn_flip_h)
        h_src_tools.addWidget(self._btn_flip_v)
        h_src_tools.addWidget(self._btn_zoom_out)
        h_src_tools.addWidget(self._btn_zoom_in)
        h_src_tools.addWidget(self._btn_crop)
        h_src_tools.addWidget(_vsep())

        h_src_tools.addStretch(1)
        h_src_tools.addWidget(self._btn_reset_edits)
        v_src_tools.addLayout(h_src_tools)
        h_tools_root.addWidget(grp_src_tools, 1)

        grp_out_tools = QGroupBox("Output actions")
        v_out_tools = QVBoxLayout(grp_out_tools)
        v_out_tools.setContentsMargins(7, 3, 7, 5)
        v_out_tools.setSpacing(4)

        h_out_actions = QHBoxLayout()
        h_out_actions.setSpacing(6)
        h_out_actions.addStretch(1)

        self._chk_beautify = QCheckBox("Beautify")
        self._chk_beautify.setChecked(False)
        self._chk_beautify.setToolTip(
            "When a face is detected: magazine / movie-star editorial polish (stronger refinement than plain upscale) — "
            "dimensional light, luminous skin, camera-ready grooming, same person (identity preserved). "
            f"Pikaso-style skin reference (not an API): {PIKASO_HIGH_END_SKIN_SPACE_URL}\n"
            "Unchecked: high-detail upscale only, minimal img2img change."
        )
        self._chk_beautify.setStyleSheet("color:#d4d4d8; font-size:9px; font-weight:600;")
        self._chk_beautify.setFixedHeight(28)
        h_out_actions.addWidget(self._chk_beautify, 0, Qt.AlignmentFlag.AlignVCenter)

        self._btn_run = QPushButton("UPSCALE")
        self._btn_run.setObjectName("btnStart")
        self._btn_run.setFixedSize(108, 28)
        self._btn_run.setStyleSheet(_run_upscale_btn_stylesheet(pulse=False))
        self._btn_run.clicked.connect(self._run_upscale)
        h_out_actions.addWidget(self._btn_run)

        self._btn_save = QPushButton("Save")
        self._btn_save.setObjectName("saveBtn")
        self._btn_save.setFixedSize(72, 28)
        self._btn_save.clicked.connect(self._save_result)
        h_out_actions.addWidget(self._btn_save)

        self._combo_save_fmt = QComboBox()
        self._combo_save_fmt.addItems(["PNG", "JPG"])
        self._combo_save_fmt.setCurrentText("PNG")
        self._combo_save_fmt.setStyleSheet(_combo_style)
        self._combo_save_fmt.setFixedSize(56, 18)
        h_out_actions.addWidget(self._combo_save_fmt, 0, Qt.AlignmentFlag.AlignVCenter)

        v_out_tools.addLayout(h_out_actions)

        h_prog = QHBoxLayout()
        h_prog.setContentsMargins(0, 0, 0, 0)
        h_prog.setSpacing(8)
        self._bar = QProgressBar()
        self._bar.setObjectName("masterBar")
        self._bar.setFixedHeight(14)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("Ready")
        self._bar.setVisible(False)
        h_prog.addWidget(self._bar, 1)
        self._lbl_exec = QLabel("Ready")
        self._lbl_exec.setFixedWidth(62)
        self._lbl_exec.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_exec.setStyleSheet("color:#10b981; font-size:9px; font-weight:800;")
        self._lbl_exec.setVisible(False)
        h_prog.addWidget(self._lbl_exec)
        v_out_tools.addLayout(h_prog)

        h_tools_root.addWidget(grp_out_tools, 1)
        root.addLayout(h_tools_root)

        grp_log = QGroupBox("Console")
        grp_log.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(8, 3, 8, 5)
        v_log.setSpacing(0)
        self._log_edit = QTextEdit()
        self._log_edit.setObjectName("panelConsole")
        self._log_edit.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        self._log_edit.setReadOnly(True)
        self._log_edit.setAcceptRichText(True)
        self._log_edit.setMinimumHeight(96)
        self._log_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._log_edit.document().setMaximumBlockCount(800)
        v_log.addWidget(self._log_edit, 1)
        root.addWidget(grp_log, 2)

        self._loading_panel_prefs = True
        try:
            prefs = self._panel_prefs.load()
            fmt = str(prefs.get("save_fmt", "PNG")).upper()
            if fmt in ("PNG", "JPG"):
                self._combo_save_fmt.setCurrentText(fmt)
            self._chk_beautify.setChecked(bool(prefs.get("beautify", False)))
        finally:
            self._loading_panel_prefs = False

        self._edit_image.textChanged.connect(lambda *_: self._persist_panel_prefs())
        self._combo_save_fmt.currentTextChanged.connect(lambda *_: self._persist_panel_prefs())
        self._chk_beautify.stateChanged.connect(lambda *_: self._persist_panel_prefs())

        self._refresh_engine_and_models()
        self._update_buttons()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._get_active_image_path():
            self._preview_resize_timer.start()

    def _panel_prefs_payload(self) -> dict:
        return {
            "source_image": "",
            "save_fmt": (self._combo_save_fmt.currentText().strip().upper() or "PNG"),
            "beautify": self._chk_beautify.isChecked(),
        }

    def _persist_panel_prefs(self) -> None:
        if self._loading_panel_prefs:
            return
        self._panel_prefs.save(self._panel_prefs_payload())

    def _apply_source_path(self, p: str) -> None:
        """Load image path like Browse (clears edits, refreshes previews)."""
        p = (p or "").strip()
        if not p:
            return
        self._edit_image.setText(p)
        self._source_path = p
        self._preview_zoom = 1.0
        self._edited_path = None
        self._undo_stack.clear()
        try:
            with Image.open(p) as im:
                self._work_pil = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:
            self._work_pil = None
        QTimer.singleShot(0, lambda p=p: self._show_original_preview(p))
        self._lbl_up.clear()
        self._lbl_up.setText("—")
        self._last_result = None
        self._update_buttons()
        self._update_undo_ui()
        self._persist_panel_prefs()

    def _update_undo_ui(self) -> None:
        n = len(self._undo_stack)
        try:
            self._lbl_undo_left.setText(str(n))
            self._btn_undo.setEnabled(n > 0 and not self._setup_in_progress and not self._upscale_in_progress)
        except Exception:
            pass

    def _push_undo(self) -> None:
        """Push current working image to undo stack (pixel edits only)."""
        if self._work_pil is None:
            return
        try:
            self._undo_stack.append(self._work_pil.copy())
        except Exception:
            return
        self._update_undo_ui()

    def _undo_last(self) -> None:
        if not self._undo_stack:
            self._update_undo_ui()
            return
        try:
            prev = self._undo_stack.pop()
        except Exception:
            self._update_undo_ui()
            return
        self._work_pil = prev
        # Persist and refresh previews; undo is a pixel edit and invalidates prior upscale.
        if self._commit_work_pil_to_temp():
            self._show_original_preview(self._edited_path or self._source_path)
        self._clear_upscaled_preview()
        self._update_buttons()
        self._update_undo_ui()

    def _on_setup_complete_generic(self, result):
        """Dispatches engine / engine_uninstall / model completion via _pending_setup_kind."""
        kind = self._pending_setup_kind
        self._pending_setup_kind = None
        dlg = self._active_setup_dialog
        self._active_setup_dialog = None
        if dlg:
            dlg.close()
        self._setup_in_progress = False
        self._update_undo_ui()

        if kind == "engine_uninstall":
            self._engine_just_installed = False
            self._engine.unload()
            self._add_log("PyTorch stack uninstalled.")
            QTimer.singleShot(0, self._apply_engine_row_after_setup)
            return

        if kind == "engine":
            ok = result[0] if isinstance(result, tuple) else bool(result)
            err = result[1] if isinstance(result, tuple) and len(result) > 1 else None
            if ok:
                self._engine_just_installed = True
                self._add_log("PyTorch / diffusers install finished. Restart ChronoArchiver to load new packages.")
            else:
                self._add_log(f"Engine setup failed: {err or 'unknown error'}")
            QTimer.singleShot(0, self._apply_engine_row_after_setup)
            return

        if kind == "models":
            ok = bool(result) if not isinstance(result, tuple) else bool(result[0])
            self._add_log("Model setup complete." if ok else "Model setup failed or cancelled.")
            if ok:
                self._engine.unload()
            QTimer.singleShot(0, self._apply_engine_row_after_setup)
            return

        QTimer.singleShot(0, self._apply_engine_row_after_setup)

    def _apply_engine_row_after_setup(self) -> None:
        self._refresh_engine_and_models()
        self._update_buttons()

    def get_activity(self) -> str:
        return "upscaling" if self._upscale_in_progress else "idle"

    def _sync_guide_pulse(self) -> None:
        busy = self._setup_in_progress or self._upscale_in_progress
        if busy:
            self._guide_pulse_timer.stop()
            self._clear_guide_glow(self._guide_target)
            self._guide_target = None
            return
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _get_guide_target(self):
        if self._setup_in_progress or self._upscale_in_progress:
            return None
        if self._engine_just_installed:
            return self._btn_install_engine
        runtime_ok, _ = self._get_runtime_cached()
        if not runtime_ok:
            return self._btn_install_engine
        if not self._model_mgr.is_up_to_date():
            return self._btn_setup_models
        path = self._edit_image.text().strip()
        if not path or not os.path.isfile(path):
            return self._btn_browse_img
        return self._btn_run

    def _clear_guide_glow(self, w):
        if not w:
            return
        ew, eh = self._eng_btn_w, self._eng_btn_h
        if w == self._btn_run:
            w.setStyleSheet(_run_upscale_btn_stylesheet(pulse=False))
        elif w == self._btn_browse_img:
            w.setStyleSheet(
                path_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#262626", "#aaa")
            )
        elif w == self._btn_install_engine:
            if self._engine_just_installed:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#064e3b", "#064e3b", "#10b981"))
            elif not self._get_runtime_cached()[0]:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#aaa", "#262626"))
            else:
                w.setStyleSheet(eng_row_btn_qss(ew, eh, "#aaa", "#262626"))
        elif w == self._btn_setup_models:
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
                target.setStyleSheet(_run_upscale_btn_stylesheet(pulse=True))
            elif target == self._btn_browse_img:
                target.setStyleSheet(
                    path_browse_btn_qss(
                        self._path_bar_h, self._browse_btn_w, "#ef4444", "#ef4444", border_px=1
                    )
                )
            elif target == self._btn_install_engine and self._engine_just_installed:
                target.setStyleSheet(eng_row_btn_qss(ew, eh, "#064e3b", "#34d399", "#10b981"))
            elif target in (self._btn_install_engine, self._btn_setup_models):
                target.setStyleSheet(eng_row_btn_qss(ew, eh, "#ef4444", "#ef4444", "transparent"))
        else:
            self._clear_guide_glow(target)

    def _get_runtime_cached(self, force: bool = False) -> tuple[bool, str]:
        """Cache `check_ml_runtime()` to avoid repeated heavy imports/CUDA checks in timers."""
        now = time.monotonic()
        if force or (now - self._runtime_cache_ts) > self._runtime_cache_ttl_s:
            try:
                ok, reason = check_ml_runtime()
            except Exception:
                ok, reason = False, "import_error"
            self._runtime_cache_ok = ok
            self._runtime_cache_reason = reason
            self._runtime_cache_ts = now
        return self._runtime_cache_ok, self._runtime_cache_reason

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

    def _refresh_engine_and_models(self):
        try:
            net_ok = is_network_reachable()
        except Exception:
            net_ok = True
        ok, reason = self._get_runtime_cached(force=True)
        if self._engine_just_installed:
            self._lbl_pytorch.setText("RESTART REQUIRED")
            self._lbl_pytorch.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
            self._btn_install_engine.setText("Restart")
            self._btn_install_engine.setToolTip("Restart ChronoArchiver to use the new PyTorch install")
            self._btn_install_engine.show()
            self._btn_uninstall_engine.hide()
        elif not ok:
            if not net_ok:
                self._lbl_pytorch.setText(NO_NETWORK_MESSAGE)
                self._lbl_pytorch.setStyleSheet(NO_NETWORK_LABEL_STYLE_9)
                self._btn_install_engine.setText("Install PyTorch")
                self._btn_install_engine.setToolTip("Internet required to install PyTorch.")
            elif reason == "missing_torch":
                txt, col = "NOT INSTALLED", "#ef4444"
                self._lbl_pytorch.setText(txt)
                self._lbl_pytorch.setStyleSheet(f"font-size:9px; font-weight:700; color:{col};")
                self._btn_install_engine.setToolTip(
                    f"{get_ml_torch_install_label()} + diffusers stack (pip)"
                )
            elif reason == "missing_diffusers":
                txt, col = "NO DIFFUSERS", "#ef4444"
                self._lbl_pytorch.setText(txt)
                self._lbl_pytorch.setStyleSheet(f"font-size:9px; font-weight:700; color:{col};")
                self._btn_install_engine.setToolTip(
                    f"{get_ml_torch_install_label()} + diffusers stack (pip)"
                )
            elif reason == "no_cuda":
                txt, col = "NO CUDA GPU", "#eab308"
                self._lbl_pytorch.setText(txt)
                self._lbl_pytorch.setStyleSheet(f"font-size:9px; font-weight:700; color:{col};")
                self._btn_install_engine.setToolTip(
                    f"{get_ml_torch_install_label()} + diffusers stack (pip)"
                )
            else:
                txt, col = "ERROR", "#ef4444"
                self._lbl_pytorch.setText(txt)
                self._lbl_pytorch.setStyleSheet(f"font-size:9px; font-weight:700; color:{col};")
                self._btn_install_engine.setToolTip(
                    f"{get_ml_torch_install_label()} + diffusers stack (pip)"
                )
            self._btn_install_engine.show()
            self._btn_uninstall_engine.hide()
        else:
            text, tip = format_pytorch_ready_line()
            self._lbl_pytorch.setText(text)
            self._lbl_pytorch.setToolTip(tip)
            self._lbl_pytorch.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
            self._btn_install_engine.setText("Install PyTorch")
            self._btn_install_engine.setToolTip("")
            self._btn_install_engine.hide()
            self._btn_uninstall_engine.show()

        models_ready = self._model_mgr.is_up_to_date()
        if models_ready:
            self._lbl_model.setText("READY")
            self._lbl_model.setStyleSheet("font-size:9px; font-weight:700; color:#10b981;")
            self._btn_setup_models.hide()
            self._btn_uninstall_models.show()
            self._btn_update_models.hide()
        else:
            if not net_ok:
                self._lbl_model.setText(NO_NETWORK_MESSAGE)
                self._lbl_model.setStyleSheet(NO_NETWORK_LABEL_STYLE_9)
                self._btn_setup_models.setToolTip(
                    "Internet required to download Z-Image-Turbo (one snapshot for upscale + Beautify)."
                )
            else:
                self._lbl_model.setText("MISSING")
                self._lbl_model.setStyleSheet("font-size:9px; font-weight:700; color:#ef4444;")
                self._btn_setup_models.setToolTip(
                    "Download Z-Image-Turbo from Hugging Face (single model — upscale, cleanup, Beautify)."
                )
            self._btn_setup_models.show()
            self._btn_uninstall_models.hide()
            self._btn_update_models.hide()

    def _update_buttons(self):
        active = self._get_active_image_path()
        path_ok = bool(active and os.path.isfile(active))
        models_ok = self._model_mgr.is_up_to_date()
        runtime_ok, _ = self._get_runtime_cached()
        busy = self._setup_in_progress or self._upscale_in_progress
        try:
            net_ok = is_network_reachable()
        except Exception:
            net_ok = True
        need_engine_net = not runtime_ok and not self._engine_just_installed
        need_models_net = not models_ok

        can_run = path_ok and models_ok and runtime_ok and not busy
        self._btn_run.setEnabled(can_run)
        self._btn_save.setEnabled(self._last_result is not None and not self._upscale_in_progress)
        self._combo_save_fmt.setEnabled(not self._upscale_in_progress)

        self._btn_install_engine.setEnabled(
            not busy and (not need_engine_net or net_ok or self._engine_just_installed)
        )
        self._btn_uninstall_engine.setEnabled(
            not busy and not self._engine_just_installed and runtime_ok
        )
        self._btn_setup_models.setEnabled(not busy and (not need_models_net or net_ok))
        self._btn_uninstall_models.setEnabled(not busy and models_ok)
        self._btn_update_models.setEnabled(not busy and models_ok)

        self._sync_guide_pulse()

    def _on_install_engine_clicked(self):
        if self._engine_just_installed:
            if restart_application():
                QApplication.instance().quit()
            return
        components, total_bytes = estimate_ml_runtime_components()
        lines = [
            "Download and install PyTorch + diffusers stack?",
            "",
            "Selected install:",
            f"  • {get_ml_torch_install_label()}",
            "",
            "Components:",
        ]
        for label, sz in components:
            lines.append(
                f"  • {label}: {fmt_bytes(sz)}" if sz > 0 else f"  • {label}"
            )
        lines.append("")
        lines.append(f"Estimated total download: {fmt_bytes(total_bytes)}")
        lines.append("")
        lines.append(pytorch_installer_vram_guidance())
        lines.append("")
        lines.append("Requires internet. You may need to restart the app afterward.")
        reply = QMessageBox.question(
            self,
            "Install PyTorch",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._setup_in_progress = True
        self._pending_setup_kind = "engine"
        self._update_buttons()
        dlg = EngineSetupDialog(self)
        dlg._lbl_components.setText(
            f"{get_ml_torch_install_label()}\n\n"
            f"{pytorch_installer_vram_guidance()}\n\n"
            "Components:\n"
            + "\n".join(
                [
                    f"  • {label}: {fmt_bytes(sz)}" if sz > 0 else f"  • {label}"
                    for (label, sz) in components
                ]
            )
            + f"\n\nEstimated total download: {fmt_bytes(total_bytes)}"
        )
        self._active_setup_dialog = dlg

        def _task():
            def prog(phase, detail, downloaded, total):
                dlg.phase_update.emit(phase, detail, downloaded, total)

            ok, err = install_ml_runtime(prog)
            self._sig.setup_complete.emit((ok, err))

        dlg.show()
        threading.Thread(target=_task, daemon=True).start()

    def _on_uninstall_engine(self):
        reply = QMessageBox.question(
            self,
            "Uninstall PyTorch stack",
            "Remove torch, torchvision, torchaudio, diffusers, transformers, accelerate, "
            "safetensors, and huggingface_hub from this environment?\n\n"
            "Upscale will be disabled until you install again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_in_progress = True
        self._pending_setup_kind = "engine_uninstall"
        self._update_buttons()

        def _task():
            uninstall_ml_runtime(None)
            self._sig.setup_complete.emit(True)

        threading.Thread(target=_task, daemon=True).start()

    def _on_setup_models(self):
        if self._model_mgr.is_up_to_date():
            reply = QMessageBox.question(
                self,
                "Models present",
                "Weights already look complete. Re-download anyway?\n\n"
                f"Target folder:\n{self._model_mgr.snapshot_dir}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            est = self._model_mgr.estimate_total_bytes()
            mb = est / (1024 * 1024)
            gb = est / (1024**3)
            sz = f"{gb:.1f} GB" if gb >= 1.0 else f"{mb:.0f} MB"
            reply = QMessageBox.question(
                self,
                "Setup AI Models",
                f"Download Z-Image-Turbo weights (~{sz}) from Hugging Face?\n\n"
                f"Repo: {REPO_ID}\n\n"
                "Internet required. Same diffusers layout as Hugging Face docs.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._setup_models_only()

    def _setup_models_only(self):
        self._setup_in_progress = True
        self._pending_setup_kind = "models"
        self._update_buttons()
        self._add_log("Starting model download…")
        dlg = ZImageModelSetupDialog(self._model_mgr, self)
        self._active_setup_dialog = dlg

        def _task():
            def prog(dl, tot, fn, ov, lbl, url):
                _debug_installer(
                    UTILITY_INSTALLER_POPUP,
                    f"Z-Image models popup: label={lbl!r} file={fn[:140]!r} overall={ov:.6f} "
                    f"downloaded={dl} total={tot} url={url[:120]}",
                )
                dlg.progress_update.emit(url, lbl, fn, dl, tot, ov)

            ok = self._model_mgr.download_models(prog)
            self._sig.setup_complete.emit(ok)

        dlg.show()
        threading.Thread(target=_task, daemon=True).start()

    def _browse_image(self):
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Open image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)",
        )
        if p:
            self._apply_source_path(p)

    def _preview_target_size_for_label(self, label: QLabel) -> tuple[int, int]:
        """Max size for scaled pixmap: fit the preview label (× zoom); square fallback before layout."""
        z = max(0.75, min(float(self._preview_zoom), 1.75))
        w = label.width()
        h = label.height()
        if w < 16 or h < 16:
            w, h = 320, 320
        return max(64, int(w * z)), max(64, int(h * z))

    def _get_active_image_path(self) -> str:
        if self._edited_path and os.path.isfile(self._edited_path):
            return self._edited_path
        return self._edit_image.text().strip()

    def _show_original_preview(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            self._lbl_orig.setText("Could not load")
            return
        w, h = self._preview_target_size_for_label(self._lbl_orig)
        scaled = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl_orig.setPixmap(scaled)
        self._lbl_orig.setText("")

    def _show_result_preview(self, pil_image):
        im = pil_image.convert("RGB")
        w, h = im.size
        data = im.tobytes("raw", "RGB")
        qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        if pix.isNull():
            self._lbl_up.setText("Preview error")
            return
        tw, th = self._preview_target_size_for_label(self._lbl_up)
        scaled = pix.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl_up.setPixmap(scaled)
        self._lbl_up.setText("")

    def _refresh_previews_for_zoom_only(self) -> None:
        """Zoom affects preview rendering only; pixel edits (rotate/crop/flip) clear the AI result."""
        p = self._get_active_image_path()
        if p:
            self._show_original_preview(p)
        if self._last_result is not None:
            self._show_result_preview(self._last_result)

    def _clear_upscaled_preview(self) -> None:
        self._lbl_up.clear()
        self._lbl_up.setText("—")
        self._last_result = None

    def _ensure_work_pil(self) -> Image.Image | None:
        if self._work_pil is not None:
            return self._work_pil
        path = self._get_active_image_path()
        if not path or not os.path.isfile(path):
            return None
        try:
            with Image.open(path) as im:
                self._work_pil = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:
            self._work_pil = None
        return self._work_pil

    def _commit_work_pil_to_temp(self) -> bool:
        """Persist the current working PIL image so the engine can load it via `image_path`."""
        if self._work_pil is None:
            return False
        try:
            self._work_pil.save(self._edited_tmp_png, format="PNG")
            self._edited_path = str(self._edited_tmp_png)
            return True
        except Exception:
            return False

    def _apply_pixel_edit(self) -> None:
        """Called after rotate/crop/flip. Updates active image and invalidates the previous upscale."""
        if self._work_pil is None:
            return
        if self._commit_work_pil_to_temp():
            self._show_original_preview(self._edited_path or self._source_path)
            self._clear_upscaled_preview()
            self._update_buttons()
            self._update_undo_ui()

    def _rotate_left(self) -> None:
        img = self._ensure_work_pil()
        if img is None:
            return
        self._push_undo()
        self._work_pil = img.transpose(Image.Transpose.ROTATE_90)
        self._apply_pixel_edit()

    def _rotate_right(self) -> None:
        img = self._ensure_work_pil()
        if img is None:
            return
        self._push_undo()
        self._work_pil = img.transpose(Image.Transpose.ROTATE_270)
        self._apply_pixel_edit()

    def _flip_horizontal(self) -> None:
        img = self._ensure_work_pil()
        if img is None:
            return
        self._push_undo()
        self._work_pil = ImageOps.mirror(img)
        self._apply_pixel_edit()

    def _flip_vertical(self) -> None:
        img = self._ensure_work_pil()
        if img is None:
            return
        self._push_undo()
        self._work_pil = ImageOps.flip(img)
        self._apply_pixel_edit()

    def _crop_center(self) -> None:
        img = self._ensure_work_pil()
        if img is None:
            return
        keep_pct, ok = QInputDialog.getInt(
            self,
            "Crop",
            "Keep center area (%)",
            85,
            10,
            100,
            1,
        )
        if not ok:
            return
        keep_pct = max(10, min(int(keep_pct), 100))
        w, h = img.size
        nw = max(8, int(w * keep_pct / 100))
        nh = max(8, int(h * keep_pct / 100))
        left = max(0, (w - nw) // 2)
        top = max(0, (h - nh) // 2)
        right = min(w, left + nw)
        bottom = min(h, top + nh)
        if right <= left or bottom <= top:
            return
        self._push_undo()
        self._work_pil = img.crop((left, top, right, bottom))
        self._apply_pixel_edit()

    def _zoom_in_preview(self) -> None:
        self._preview_zoom = min(1.75, float(self._preview_zoom) + 0.1)
        self._refresh_previews_for_zoom_only()

    def _zoom_out_preview(self) -> None:
        self._preview_zoom = max(0.75, float(self._preview_zoom) - 0.1)
        self._refresh_previews_for_zoom_only()

    def _reset_edits(self) -> None:
        if not self._source_path or not os.path.isfile(self._source_path):
            return
        # Reset is a pixel-state change; allow undo back to the prior edit state.
        if self._work_pil is not None:
            self._push_undo()
        self._preview_zoom = 1.0
        self._edited_path = None
        try:
            with Image.open(self._source_path) as im:
                self._work_pil = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:
            self._work_pil = None
        self._clear_upscaled_preview()
        self._show_original_preview(self._source_path)
        self._update_buttons()
        self._update_undo_ui()

    def _on_remove_models(self):
        reply = QMessageBox.question(
            self,
            "Uninstall Models",
            "Remove downloaded Z-Image weight files?\n\nRun Setup Models to download again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._engine.unload()
        self._model_mgr.remove_snapshot()
        self._refresh_engine_and_models()
        self._add_log("AI models removed.")
        self._update_buttons()

    def _run_upscale(self):
        path = self._get_active_image_path()
        if not path or not os.path.isfile(path):
            self._add_log("ERROR: Select a valid image file.")
            return
        self._upscale_in_progress = True
        self._bar.setVisible(True)
        self._lbl_exec.setVisible(True)
        self._bar.setRange(0, 0)
        self._bar.setFormat("Running…")
        self._lbl_exec.setText("Working…")
        self._update_buttons()
        self._update_undo_ui()

        def _log(msg: str):
            self._sig.log_msg.emit(msg)

        beautify = self._chk_beautify.isChecked()
        try:
            with Image.open(path) as im:
                ow, oh = im.size
        except Exception:
            self._upscale_in_progress = False
            self._bar.setVisible(False)
            self._lbl_exec.setVisible(False)
            self._update_buttons()
            self._add_log("ERROR: Could not read image dimensions.")
            return
        portrait, freckle_heavy, face_bbox = portrait_signals_from_path_detailed(path)
        auto = infer_zimage_params(
            ow=ow,
            oh=oh,
            portrait_detected=portrait,
            freckle_heavy=freckle_heavy,
            beautify=beautify,
        )

        def _work():
            try:
                _log(auto.summary)
                beautify_analysis: str | None = None
                if beautify and portrait and face_bbox:
                    _log("Beautify: analyzing scene (whole image) + full face + facial zones with local BLIP…")
                    notes = analyze_beautify_imperfections(path, face_bbox, _log)
                    beautify_analysis = notes if notes else None
                    if beautify_analysis:
                        _log("Beautify: applying magazine-style glam (Z-Image + analysis + identity-locked prompt).")
                    else:
                        _log(
                            "Beautify: no BLIP notes — using built-in movie-star / editorial template "
                            "(see Beautify tooltip)."
                        )
                    if freckle_heavy:
                        _log("Freckle-dense heuristic: extra soften line in retouch text.")
                elif beautify and not portrait:
                    _log("Beautify checked but no face detected — high-fidelity upscale, minimal change.")
                else:
                    _log("Beautify off — high-fidelity upscale, minimal change to the original.")
                lama = self._get_lama_runner()
                img = self._engine.run(
                    image_path=path,
                    scale=auto.scale,
                    max_side=auto.max_side,
                    strength=auto.strength,
                    num_inference_steps=auto.steps,
                    cfg=auto.cfg,
                    log=_log,
                    portrait_detected=portrait,
                    freckle_heavy=freckle_heavy,
                    beautify=beautify,
                    beautify_analysis=beautify_analysis,
                    lama_runner=lama,
                )
                self._sig.upscale_done.emit(img)
            except Exception as e:
                self._sig.upscale_failed.emit(str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_upscale_done(self, img):
        self._last_result = img
        self._upscale_in_progress = False
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._bar.setFormat("Complete")
        self._lbl_exec.setText("Done")
        self._show_result_preview(img)
        self._update_buttons()
        self._update_undo_ui()
        self._add_log("Upscale complete.")
        QTimer.singleShot(2000, self._reset_bar)

    def _reset_bar(self):
        if not self._upscale_in_progress:
            self._bar.setFormat("Ready")
            self._bar.setValue(0)
            self._lbl_exec.setText("Ready")
            self._bar.setVisible(False)
            self._lbl_exec.setVisible(False)

    def _on_upscale_failed(self, err: str):
        self._upscale_in_progress = False
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("Failed")
        self._lbl_exec.setText("Error")
        self._bar.setVisible(True)
        self._lbl_exec.setVisible(True)
        self._update_buttons()
        self._update_undo_ui()
        self._add_log(f"ERROR: {err}")
        u = (err or "").lower()
        if "not enough gpu memory" in u or "out of memory" in u:
            from core.ai_inference_resources import ZIMAGE_VRAM_BASELINE_LOG

            try:
                log_exception(
                    RuntimeError(err),
                    context="AI Image Upscaler · Z-Image OOM",
                    utility=UTILITY_APP,
                    extra=ZIMAGE_VRAM_BASELINE_LOG,
                )
            except Exception:
                pass
            QMessageBox.warning(self, "GPU memory", (err or "")[:1200])

    def _save_result(self):
        if self._last_result is None:
            return
        fmt = (self._combo_save_fmt.currentText().strip().upper() if hasattr(self, "_combo_save_fmt") else "PNG")
        ext = ".jpg" if fmt == "JPG" else ".png"
        default = ""
        if self._source_path:
            base, _ = os.path.splitext(self._source_path)
            default = f"{base}_upscaled{ext}"
        if fmt == "JPG":
            filt = "JPEG (*.jpg *.jpeg)"
            title = "Save JPG"
        else:
            filt = "PNG (*.png)"
            title = "Save PNG"
        path, _ = QFileDialog.getSaveFileName(self, title, default, filt)
        if not path:
            return
        try:
            if fmt == "JPG":
                p = path
                if not p.lower().endswith((".jpg", ".jpeg")):
                    p += ".jpg"
                self._last_result.convert("RGB").save(p, format="JPEG", quality=90, optimize=True)
            else:
                p = path
                if not p.lower().endswith(".png"):
                    p += ".png"
                self._last_result.save(p, format="PNG")
            self._add_log(f"Saved: {p}")
        except Exception as e:
            self._add_log(f"ERROR saving: {e}")

    def _add_log(self, msg: str):
        sb = self._log_edit.verticalScrollBar()
        at_bot = sb.value() >= sb.maximum() - 4
        html_line = message_to_html(msg)
        cursor = self._log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html_line + "<br>")
        if at_bot:
            sb.setValue(sb.maximum())

    def append_external_line(self, msg: str):
        self._add_log(msg)


# Backward-compatible import name
ZImageProUpscalerPanel = AIImageUpscalerPanel
