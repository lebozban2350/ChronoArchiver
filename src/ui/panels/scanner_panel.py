"""
scanner_panel.py — AI Media Scanner panel for ChronoArchiver.
Visual style exactly matches Mass AV1 Encoder v12.
"""

import csv
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QSpinBox, QFrame, QDialog, QComboBox, QMessageBox,
    QInputDialog, QTextEdit, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QShowEvent, QPixmap, QTextCursor

import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.scanner import ScannerEngine, OPENCV_AVAILABLE
from ui.console_style import message_to_html, PANEL_CONSOLE_TEXTEDIT_STYLE
from core.model_manager import ModelManager
from core.app_paths import models_dir
from core.venv_manager import (
    get_pip_exe, ensure_venv,
    get_opencv_variant, get_opencv_variant_label,
    get_opencv_install_components, install_opencv, uninstall_opencv,
    check_opencv_in_venv,
)
from core.debug_logger import debug, UTILITY_AI_MEDIA_SCANNER, UTILITY_OPENCV_INSTALL, UTILITY_MODEL_SETUP
from core.updater import restart_app
from core.subprocess_tee import set_subprocess_channel


def _scan_browse_btn_qss(bar_h: int, btn_w: int, border: str, fg: str) -> str:
    """Browse buttons: idle and guide pulse only swap colors (fixed box, no layout warp)."""
    return (
        f"font-size:9px; font-weight:700; color:{fg}; border:2px solid {border}; "
        f"min-width:{btn_w}px; max-width:{btn_w}px; "
        f"min-height:{bar_h}px; max-height:{bar_h}px; padding:0px;"
    )


def _scan_eng_btn_qss(w: int, h: int, fg: str, bd: str, bg: str = "transparent") -> str:
    """Engine row buttons: fixed size; idle vs pulse only changes colors."""
    return (
        f"font-size:7px; font-weight:700; color:{fg}; background-color:{bg}; "
        f"border:2px solid {bd}; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
    )


class _Signals(QObject):
    log_msg  = Signal(str)
    progress = Signal(float)
    finished = Signal()
    setup_complete = Signal(object)  # (ok, err) for OpenCV install, bool for uninstall/model setup
    remove_done = Signal()
    version_check_done = Signal(bool, bool)  # models_update, opencv_update
    setup_phase = Signal(str, str)  # phase_name, detail
    prereqs_changed = Signal()  # OpenCV or models installed/uninstalled — refresh footer


class OpenCVSetupDialog(QDialog):
    """Popup for OpenCV install progress."""
    phase_update = Signal(str, str, int, int)  # phase, detail, downloaded, total

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenCV Setup")
        self.setModal(False)
        self.setFixedSize(420, 180)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl_phase = QLabel("Preparing...")
        self._lbl_phase.setStyleSheet("font-size: 10px; font-weight: 600; color: #10b981;")
        v.addWidget(self._lbl_phase)
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

    def _on_phase_update(self, phase: str, detail: str, downloaded: int, total: int):
        self._lbl_phase.setText(phase)
        if total > 0 and downloaded >= 0:
            pct = min(100, int(100 * downloaded / total)) if total else 0
            self._bar.setRange(0, 100)
            self._bar.setValue(pct)
            self._bar.setFormat("%p%")
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            if mb_t >= 0.01:
                size_str = f"{mb_d:.2f} / {mb_t:.2f} MB"
                self._lbl_detail.setText(f"{size_str}  ·  {detail}" if detail else size_str)
            else:
                self._lbl_detail.setText(detail[:120] if detail else "")
        else:
            self._lbl_detail.setText(detail[:120] if detail else "")


class ModelSetupDialog(QDialog):
    """Popup showing model download progress: URL, model name, fixed progress bar."""
    progress_update = Signal(str, str, str, int, int, float)

    def __init__(self, model_mgr, parent=None):
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

    def _on_cancel(self):
        self._model_mgr.cancel()
        self._btn_cancel.setEnabled(False)
        self._lbl_model.setText("Cancelling...")

    def update_progress(self, url: str, label: str, filename: str, downloaded: int, total: int, overall: float):
        if self._bar.minimum() == 0 and self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._lbl_url.setText(f"From: {url[:70]}..." if len(url) > 70 else f"From: {url}")
        if filename.startswith("Extracting") or "Installing models" in filename:
            self._lbl_model.setText("Installing models... please wait...")
            self._lbl_detail.setText("")
        else:
            self._lbl_model.setText(f"Downloading: {label} ({filename})")
        pct = int(overall * 100)
        self._bar.setValue(min(100, pct))
        if total > 0:
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            if mb_t >= 0.01:
                self._lbl_detail.setText(f"{mb_d:.2f} / {mb_t:.2f} MB")
            else:
                kb_d = downloaded / 1024
                kb_t = total / 1024
                self._lbl_detail.setText(f"{kb_d:.1f} / {kb_t:.1f} KB")
        else:
            self._lbl_detail.setText(f"{downloaded:,} bytes")


class AIScannerPanel(QWidget):

    def __init__(self, log_callback=None, status_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb = log_callback
        self._status_cb = status_callback
        self._sig    = _Signals()
        self._sig.log_msg.connect(self._add_log)
        self._sig.progress.connect(self._on_progress)
        self._sig.finished.connect(self._on_finished)
        self._sig.version_check_done.connect(self._on_version_check)

        self._model_mgr = ModelManager(str(models_dir()))

        self._engine = None  # Initialized in _run_job
        self._is_running = False
        self._cap_request_queue = queue.Queue()  # (list_name, current_cap, result_holder, done_event)
        self._cap_timer = QTimer(self)
        self._cap_timer.setInterval(80)
        self._cap_timer.timeout.connect(self._process_cap_requests)

        _shint = "font-size: 7px; color: #444; margin-top: -1px;"

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(2)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        h_strip = QHBoxLayout()
        h_strip.setSpacing(6)
        _strip_h = 84  # Directories / Options / Engine Status — tighter bottom (was 108)

        _bar_h = 28
        _browse_w, _browse_h = 60, _bar_h
        self._path_bar_h = _bar_h
        self._browse_btn_w = _browse_w
        self._eng_btn_w = 82
        self._eng_btn_h = 22
        _ew, _eh = self._eng_btn_w, self._eng_btn_h
        _edit_ss = (
            f"color:#fff; font-size:11px; font-weight:500; min-height:{_bar_h}px; max-height:{_bar_h}px; "
            "padding:2px 6px; background:#121212; border:1px solid #1a1a1a;"
        )
        _btn_ss = _scan_browse_btn_qss(_bar_h, _browse_w, "#262626", "#aaa")

        # 1. Directories
        grp_dir = QGroupBox("Directories")
        grp_dir.setFixedHeight(_strip_h)
        v_dir = QVBoxLayout(grp_dir)
        v_dir.setContentsMargins(6, 6, 6, 0)
        v_dir.setSpacing(0)
        h_src = QHBoxLayout()
        h_src.setSpacing(6)
        h_src.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._edit_path = QLineEdit()
        self._edit_path.setPlaceholderText("SELECT PHOTO LIBRARY...")
        self._edit_path.textChanged.connect(self._update_start_enabled)
        self._edit_path.setStyleSheet(_edit_ss)
        self._edit_path.setFixedHeight(_bar_h)
        h_src.addWidget(self._edit_path, 1, Qt.AlignmentFlag.AlignVCenter)
        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setFixedSize(_browse_w, _browse_h)
        self._btn_browse.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_browse.setStyleSheet(_btn_ss)
        self._btn_browse.clicked.connect(self._browse)
        h_src.addWidget(self._btn_browse, 0, Qt.AlignmentFlag.AlignVCenter)
        v_dir.addLayout(h_src)
        v_dir.addWidget(QLabel("Photos for AI detection (YuNet/YOLOv8)", styleSheet=_shint))
        h_strip.addWidget(grp_dir, 9)

        # 2. Options (stacked vertically)
        grp_opts = QGroupBox("Options")
        grp_opts.setFixedHeight(_strip_h)
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(6, 2, 6, 0)
        v_opts.setSpacing(2)
        self._chk_recursive = QCheckBox("Recursive")
        self._chk_recursive.setChecked(True)
        self._chk_recursive.setStyleSheet("font-size:9px; font-weight:700; color:#aaa;")
        self._chk_animals = QCheckBox("Keep Animals")
        self._chk_animals.setStyleSheet("font-size:9px; font-weight:700; color:#aaa;")
        self._chk_animals.setToolTip("Also keep photos with detected persons and animals")
        h_conf = QHBoxLayout()
        h_conf.setSpacing(4)
        h_conf.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl_conf = QLabel("Confidence:")
        lbl_conf.setStyleSheet("font-size:8px; color:#888;")
        lbl_conf.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._spin_thresh = QSpinBox()
        self._spin_thresh.setRange(10, 90)
        self._spin_thresh.setValue(40)
        self._spin_thresh.setSuffix("%")
        self._spin_thresh.setStyleSheet(
            "font-size:8px; padding-left:2px; padding-right:4px; min-height:18px; max-height:18px;"
        )
        self._spin_thresh.setFixedWidth(58)
        h_conf.addWidget(lbl_conf, 0, Qt.AlignmentFlag.AlignVCenter)
        h_conf.addWidget(self._spin_thresh, 0, Qt.AlignmentFlag.AlignVCenter)
        h_conf.addStretch()
        v_opts.addWidget(self._chk_recursive)
        v_opts.addWidget(self._chk_animals)
        v_opts.addLayout(h_conf)
        h_strip.addWidget(grp_opts, 2)

        # 3. Engine Status (fixed min width to prevent stretch when Install text changes)
        grp_mod = QGroupBox("Engine Status")
        grp_mod.setFixedHeight(_strip_h)
        grp_mod.setMinimumWidth(228)
        v_mod = QVBoxLayout(grp_mod)
        v_mod.setContentsMargins(6, 2, 6, 0)
        v_mod.setSpacing(2)
        h_cv = QHBoxLayout()
        self._lbl_opencv = QLabel("CHECKING…")
        self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
        self._lbl_opencv.setMinimumWidth(98)  # Reserve space to prevent layout shift
        h_cv.addWidget(QLabel("OpenCV:", styleSheet="font-size:7px; color:#888;"))
        h_cv.addWidget(self._lbl_opencv, 1)
        self._btn_install_cv = QPushButton("Install OpenCV")
        self._btn_install_cv.setFixedSize(_ew, _eh)
        self._btn_install_cv.setStyleSheet(_scan_eng_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_install_cv.clicked.connect(self._on_install_opencv)
        self._btn_uninstall_cv = QPushButton("Uninstall OpenCV")
        self._btn_uninstall_cv.setFixedSize(_ew, _eh)
        self._btn_uninstall_cv.setStyleSheet(_scan_eng_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_uninstall_cv.clicked.connect(self._on_uninstall_opencv)
        h_cv.addWidget(self._btn_install_cv)
        h_cv.addWidget(self._btn_uninstall_cv)
        v_mod.addLayout(h_cv)
        h_mod = QHBoxLayout()
        self._lbl_model = QLabel("CHECKING…")
        self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
        self._lbl_model.setMinimumWidth(70)  # Reserve space to prevent layout shift
        h_mod.addWidget(QLabel("Models:", styleSheet="font-size:7px; color:#888;"))
        h_mod.addWidget(self._lbl_model, 1)
        self._btn_update = QPushButton("Update!")
        self._btn_update.setFixedSize(_ew, _eh)
        self._btn_update.setStyleSheet(_scan_eng_btn_qss(_ew, _eh, "#eab308", "#eab308"))
        self._btn_update.clicked.connect(self._setup_models_only)
        self._btn_update.hide()
        self._btn_setup = QPushButton("Setup Models")
        self._btn_setup.setFixedSize(_ew, _eh)
        self._btn_setup.setStyleSheet(_scan_eng_btn_qss(_ew, _eh, "#aaa", "#262626"))
        self._btn_setup.clicked.connect(self._on_setup_models)
        self._btn_uninstall_models = QPushButton("Uninstall Models")
        self._btn_uninstall_models.setFixedSize(_ew, _eh)
        self._btn_uninstall_models.setStyleSheet(_scan_eng_btn_qss(_ew, _eh, "#6b7280", "#262626"))
        self._btn_uninstall_models.clicked.connect(self._remove_models_only)
        self._btn_uninstall_models.setToolTip("Remove AI model files only")
        h_mod.addWidget(self._btn_update)
        h_mod.addWidget(self._btn_setup)
        h_mod.addWidget(self._btn_uninstall_models)
        v_mod.addLayout(h_mod)
        h_strip.addWidget(grp_mod, 3)

        root.addLayout(h_strip)
        self._guide_pulse_timer = QTimer(self)
        self._guide_pulse_timer.setInterval(550)
        self._guide_pulse_timer.timeout.connect(self._pulse_guide)
        self._guide_glow_phase = 0
        self._guide_target = None

        # ── SCANNING PROGRESS ──────────────────────────────────────────────────
        grp_exec = QGroupBox("Scanning Progress")
        h_exec = QHBoxLayout(grp_exec)
        h_exec.setContentsMargins(6, 2, 6, 2)
        h_exec.setSpacing(8)
        self._bar = QProgressBar()
        self._bar.setObjectName("masterBar")
        self._bar.setFixedHeight(18)
        self._bar.setTextVisible(True)
        self._bar.setFormat("Ready")
        h_exec.addWidget(self._bar, 1)
        self._lbl_status = QLabel("Ready")
        self._lbl_status.setStyleSheet("color:#10b981; font-size:8px; font-weight:700; min-width:70px;")
        h_exec.addWidget(self._lbl_status)
        h_exec.addStretch()
        self._btn_start = QPushButton("START AI SCAN")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setFixedHeight(32)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self._run_job)
        h_exec.addWidget(self._btn_start)
        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setFixedHeight(32)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_job)
        h_exec.addWidget(self._btn_stop)
        root.addWidget(grp_exec)

        # ── RESULTS (Keep | Move | Preview) ───────────────────────────────────
        grp_res = QGroupBox("Results")
        v_res = QVBoxLayout(grp_res)
        v_res.setContentsMargins(6, 2, 6, 2)
        h_res = QHBoxLayout()
        h_res.setSpacing(8)
        v_k = QVBoxLayout()
        v_k.addWidget(QLabel("Keep (subjects)", styleSheet="font-size:8px; font-weight:700;"))
        self._list_keep = QListWidget()
        self._list_keep.setMinimumWidth(160)
        self._list_keep.itemSelectionChanged.connect(self._on_keep_selection_changed)
        v_k.addWidget(self._list_keep)
        v_m = QVBoxLayout()
        self._lbl_move_copy = QLabel("Move (others)", styleSheet="font-size:8px; font-weight:700;")
        v_m.addWidget(self._lbl_move_copy)
        self._list_move = QListWidget()
        self._list_move.setMinimumWidth(160)
        self._list_move.itemSelectionChanged.connect(self._on_move_selection_changed)
        v_m.addWidget(self._list_move)
        h_res.addLayout(v_k, 1)
        h_res.addLayout(v_m, 1)
        # Image preview
        frm_preview = QFrame()
        frm_preview.setFrameShape(QFrame.StyledPanel)
        frm_preview.setStyleSheet("background:#0a0a0a; border:1px solid #1a1a1a;")
        frm_preview.setMinimumWidth(220)
        frm_preview.setMinimumHeight(160)
        v_preview = QVBoxLayout(frm_preview)
        v_preview.setContentsMargins(4, 4, 4, 4)
        self._lbl_preview = QLabel("Select an item to preview")
        self._lbl_preview.setAlignment(Qt.AlignCenter)
        self._lbl_preview.setStyleSheet("color:#444; font-size:9px;")
        self._lbl_preview.setMinimumSize(200, 140)
        v_preview.addWidget(self._lbl_preview, 1, Qt.AlignCenter)
        h_res.addWidget(frm_preview, 1)
        v_res.addLayout(h_res)
        h_btns = QHBoxLayout()
        h_btns.setSpacing(6)
        h_btns.addWidget(QLabel("Target:", styleSheet="font-size:8px; color:#888;"))
        self._edit_target = QLineEdit()
        self._edit_target.setPlaceholderText("Select target folder...")
        self._edit_target.setStyleSheet(_edit_ss)
        self._edit_target.setMinimumHeight(_bar_h)
        self._edit_target.textChanged.connect(self._update_move_start)
        h_btns.addWidget(self._edit_target, 1)
        self._btn_browse_target = QPushButton("Browse")
        self._btn_browse_target.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_target.setStyleSheet(_btn_ss)
        self._btn_browse_target.clicked.connect(self._browse_target)
        h_btns.addWidget(self._btn_browse_target)
        self._combo_action = QComboBox()
        self._combo_action.addItems(["Move", "Copy"])
        self._combo_action.setStyleSheet("font-size:8px; min-width:72px; min-height:24px;")
        self._combo_action.setCurrentIndex(0)
        self._combo_action.currentTextChanged.connect(self._update_move_copy_label)
        h_btns.addWidget(self._combo_action)
        self._btn_start_move = QPushButton("START")
        self._btn_start_move.setObjectName("btnStartMove")
        self._btn_start_move.setFixedHeight(_bar_h)
        self._btn_start_move.setStyleSheet(
            "font-size:8px; font-weight:700; "
            "background:#1a1a1a; color:#6b7280; border:2px solid #262626;")
        self._btn_start_move.clicked.connect(self._apply_move_copy)
        self._btn_start_move.setEnabled(False)
        h_btns.addWidget(self._btn_start_move)
        self._btn_export = QPushButton("Export CSV")
        self._btn_export.setFixedHeight(_bar_h)
        self._btn_export.setStyleSheet("font-size:8px; font-weight:700; border:2px solid #262626;")
        self._btn_export.clicked.connect(self._export_csv)
        h_btns.addWidget(self._btn_export)
        h_btns.addStretch()
        v_res.addLayout(h_btns)
        root.addWidget(grp_res, 1)

        # ── CONSOLE ───────────────────────────────────────────────────────────
        grp_log = QGroupBox("Console")
        grp_log.setMaximumHeight(140)
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(6, 4, 6, 4)
        v_log.setSpacing(0)
        self._log_edit = QTextEdit()
        self._log_edit.setObjectName("panelConsole")
        self._log_edit.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        self._log_edit.setReadOnly(True)
        self._log_edit.setAcceptRichText(True)
        self._log_edit.setMaximumHeight(100)
        self._log_edit.document().setMaximumBlockCount(1000)
        v_log.addWidget(self._log_edit)
        root.addWidget(grp_log, 0)

        self._model_update_available = False
        self._opencv_update_available = False
        self._version_check_started = False
        self._setup_in_progress = False
        self._opencv_just_installed = False
        self._cached_cv_ok = False  # Updated by _check_models; used by _get_guide_target, _update_start_enabled
        # _check_models runs when prereqs done (app calls it) and on showEvent — avoids blocking main thread during FFmpeg install

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if not self._setup_in_progress:
            self._check_models()

    def _opencv_available_sync(self) -> bool:
        """Synchronous: avoid calling from main thread (blocks ~500ms)."""
        if get_pip_exe().exists():
            return check_opencv_in_venv()
        return bool(OPENCV_AVAILABLE)

    def _check_models(self):
        """Run OpenCV check off main thread, then apply UI updates."""
        def _apply(cv_ok: bool):
            self._cached_cv_ok = cv_ok
            debug(UTILITY_AI_MEDIA_SCANNER, f"_check_models: cv_ok={cv_ok} _opencv_just_installed={self._opencv_just_installed}")
            if self._opencv_just_installed:
                self._lbl_opencv.setText("RESTART REQUIRED")
                self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
                self._btn_install_cv.setText("RESTART")
                self._btn_install_cv.setFixedSize(self._eng_btn_w, self._eng_btn_h)
                self._btn_install_cv.setToolTip("Restart ChronoArchiver to use the new OpenCV installation")
                self._btn_install_cv.show()
                self._btn_uninstall_cv.hide()
            elif not cv_ok:
                self._lbl_opencv.setText("NOT INSTALLED")
                self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#ef4444;")
                self._btn_install_cv.setText("Install OpenCV")
                self._btn_install_cv.setFixedSize(self._eng_btn_w, self._eng_btn_h)
                self._btn_install_cv.setToolTip(get_opencv_variant_label())
                self._btn_install_cv.show()
                self._btn_uninstall_cv.hide()
            else:
                v = get_opencv_variant()
                suf = " (CUDA)" if v == "cuda" else " (OpenCL)"
                self._lbl_opencv.setText(f"READY{suf}")
                self._btn_install_cv.setToolTip("")
                self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
                self._btn_install_cv.hide()
                self._btn_uninstall_cv.show()

            ready = self._model_mgr.is_up_to_date()
            if ready:
                self._lbl_model.setText("READY")
                self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
                self._btn_setup.hide()
                self._btn_uninstall_models.show()
                update_avail = self._model_update_available or self._opencv_update_available
                self._btn_update.setVisible(update_avail)
                self._start_version_check()
            else:
                self._lbl_model.setText("MISSING")
                self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#ef4444;")
                self._btn_setup.show()
                self._btn_uninstall_models.hide()
                self._btn_update.hide()

            self._update_start_enabled()

        if get_pip_exe().exists():
            check_queue = queue.Queue()

            def _task():
                cv_ok = check_opencv_in_venv()
                try:
                    check_queue.put_nowait(cv_ok)
                except queue.Full:
                    pass

            def _poll():
                try:
                    cv_ok = check_queue.get_nowait()
                    if getattr(self, "_check_poll_timer", None):
                        self._check_poll_timer.stop()
                        self._check_poll_timer = None
                    _apply(cv_ok)
                except queue.Empty:
                    pass

            self._check_poll_timer = QTimer(self)
            self._check_poll_timer.timeout.connect(_poll)
            self._check_poll_timer.start(80)
            threading.Thread(target=_task, daemon=True).start()
        else:
            _apply(self._opencv_available_sync())

    def _on_version_check(self, models_update: bool, opencv_update: bool):
        self._model_update_available = bool(models_update)
        self._opencv_update_available = bool(opencv_update)
        if self._model_mgr.is_up_to_date():
            self._check_models()

    def _start_version_check(self):
        if self._version_check_started:
            return
        self._version_check_started = True

        def _task():
            set_subprocess_channel("scanner")
            models_up = False
            opencv_up = False
            try:
                models_up = self._model_mgr.check_model_update_available()
            except Exception:
                pass
            try:
                pip_exe = get_pip_exe()
                if pip_exe.exists():
                    _wh = {}
                    if platform.system() == "Windows":
                        _wh = {"creationflags": subprocess.CREATE_NO_WINDOW}
                    r = subprocess.run(
                        [str(pip_exe), "list", "--outdated"],
                        capture_output=True, text=True, timeout=10,
                        **_wh,
                    )
                    if r.returncode == 0 and "opencv-python" in (r.stdout or ""):
                        opencv_up = True
            except Exception:
                pass
            self._sig.version_check_done.emit(models_up, opencv_up)

        threading.Thread(target=_task, daemon=True).start()

    def _get_guide_target(self):
        if self._is_running or self._setup_in_progress:
            return None
        if self._opencv_just_installed or not self._cached_cv_ok:
            return self._btn_install_cv
        if not self._model_mgr.is_up_to_date():
            return self._btn_setup
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            return self._btn_browse
        has_others = self._engine and self._engine.others_list
        if has_others:
            target = self._edit_target.text().strip()
            if not target or not os.path.isdir(target):
                return self._btn_browse_target
            return self._btn_start_move
        return self._btn_start

    def _update_start_enabled(self):
        models_ready = self._model_mgr.is_up_to_date()
        path = self._edit_path.text().strip()
        path_ok = bool(path and os.path.isdir(path))
        cv_ok = self._cached_cv_ok
        can = cv_ok and models_ready and path_ok and not self._is_running
        self._btn_start.setEnabled(can)
        busy = self._setup_in_progress or self._is_running
        self._btn_uninstall_models.setEnabled(not busy and models_ready)
        self._btn_install_cv.setEnabled(not busy)
        self._btn_uninstall_cv.setEnabled(not busy and cv_ok)
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _clear_guide_glow(self, w):
        if not w:
            return
        ew, eh = self._eng_btn_w, self._eng_btn_h
        if w == self._btn_start:
            w.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid #064e3b; font-size:10px; font-weight:900;")
        elif w == self._btn_start_move:
            if self._btn_start_move.isEnabled():
                w.setStyleSheet(
                    "font-size:9px; font-weight:900; min-height:28px; max-height:28px; "
                    "background-color:#10b981; color:#064e3b; border:2px solid #064e3b; padding:0px;"
                )
            else:
                w.setStyleSheet(
                    "font-size:9px; font-weight:700; min-height:28px; max-height:28px; "
                    "background:#1a1a1a; color:#6b7280; border:2px solid #262626; padding:0px;"
                )
        elif w == self._btn_browse:
            w.setStyleSheet(
                _scan_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#262626", "#aaa")
            )
        elif w == self._btn_browse_target:
            w.setStyleSheet(
                _scan_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#262626", "#aaa")
            )
        elif w == self._btn_setup:
            w.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#aaa", "#262626"))
        elif w == self._btn_uninstall_models:
            w.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#6b7280", "#262626"))
        elif w == self._btn_install_cv:
            if self._opencv_just_installed:
                w.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#064e3b", "#064e3b", "#10b981"))
            else:
                w.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#aaa", "#262626"))
        elif w == self._btn_update:
            w.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#eab308", "#eab308"))

    def _pulse_guide(self):
        target = self._get_guide_target()
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
            if target == self._btn_start:
                target.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid #ef4444; font-size:10px; font-weight:900;")
            elif target == self._btn_start_move:
                target.setStyleSheet(
                    "font-size:9px; font-weight:900; min-height:28px; max-height:28px; "
                    "background-color:#10b981; color:#064e3b; border:2px solid #ef4444; padding:0px;"
                )
            elif target == self._btn_install_cv and self._opencv_just_installed:
                target.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#064e3b", "#34d399", "#10b981"))
            elif target == self._btn_browse or target == self._btn_browse_target:
                target.setStyleSheet(
                    _scan_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#ef4444", "#ef4444")
                )
            elif target in (self._btn_setup, self._btn_install_cv):
                target.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#ef4444", "#ef4444", "transparent"))
            else:
                target.setStyleSheet(_scan_eng_btn_qss(ew, eh, "#ef4444", "#ef4444", "transparent"))
        else:
            self._clear_guide_glow(target)

    def _on_install_opencv(self):
        if self._opencv_just_installed:
            if restart_app():
                QApplication.instance().quit()
            return
        variant = get_opencv_variant()
        components = get_opencv_install_components(variant)
        pkg = get_opencv_variant_label()
        lines = [f"Download and install {pkg}?", ""]
        if components:
            lines.append("Components:")
            total = 0
            for label, size_bytes in components:
                mb = size_bytes / (1024 * 1024)
                gb = size_bytes / (1024**3)
                sz = f"{gb:.2f} GB" if gb >= 0.1 else f"{mb:.1f} MB"
                lines.append(f"  • {label}: {sz}")
                total += size_bytes
            total_mb = total / (1024 * 1024)
            total_gb = total / (1024**3)
            total_sz = f"{total_gb:.2f} GB" if total_gb >= 0.1 else f"{total_mb:.1f} MB"
            lines.append(f"\nTotal download: {total_sz}")
        if variant == "cuda":
            lines.append("\nCUDA runtime, cuBLAS, cuFFT, and cuDNN install via pip into venv (no sudo).")
        lines.append("\nInstall into app's private venv (no sudo required).")
        reply = QMessageBox.question(
            self,
            "Install OpenCV",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_in_progress = True
        self._update_start_enabled()
        dlg = OpenCVSetupDialog(self)

        def _prog(phase, detail="", downloaded=0, total=0):
            dlg.phase_update.emit(phase, detail, downloaded, total)

        def _task():
            set_subprocess_channel("scanner")
            try:
                debug(UTILITY_OPENCV_INSTALL, "OpenCV install _task START")
                pip = get_pip_exe()
                if not pip.exists():
                    debug(UTILITY_OPENCV_INSTALL, "OpenCV install: pip not found, ensuring venv")
                    _prog("Creating venv...", "")
                    ok = ensure_venv(progress_callback=_prog)
                    if not ok:
                        debug(UTILITY_OPENCV_INSTALL, "OpenCV install: ensure_venv FAILED")
                        _prog("Failed", "Could not create venv")
                        time.sleep(2)
                        self._sig.setup_complete.emit((False, "Could not create venv"))
                        return
                ok, err = install_opencv(progress_callback=_prog, variant=variant)
                debug(UTILITY_OPENCV_INSTALL, f"OpenCV install _task: install_opencv returned ok={ok} err={err[:100] if err else None}")
                if not ok and err and variant == "cuda":
                    debug(UTILITY_OPENCV_INSTALL, "OpenCV install: trying OpenCL fallback")
                    _prog("Trying OpenCL fallback...", "")
                    ok, err = install_opencv(progress_callback=_prog, variant="opencl")
                    debug(UTILITY_OPENCV_INSTALL, f"OpenCV install _task: fallback returned ok={ok}")
                debug(UTILITY_OPENCV_INSTALL, f"OpenCV install _task: emitting setup_complete ({ok}, {err[:50] if err else None})")
                self._sig.setup_complete.emit((ok, err))
            except Exception as e:
                debug(UTILITY_OPENCV_INSTALL, f"OpenCV install _task EXCEPTION: {e}")
                _prog("Failed", str(e)[:80])
                time.sleep(2)
                self._sig.setup_complete.emit((False, str(e)))

        def _on_done(result):
            debug(UTILITY_OPENCV_INSTALL, f"OpenCV install _on_done RECV: type={type(result).__name__} value={str(result)[:200]}")
            ok = result[0] if isinstance(result, tuple) else result
            err = result[1] if isinstance(result, tuple) and len(result) > 1 else None
            debug(UTILITY_OPENCV_INSTALL, f"OpenCV install popup DONE ok={ok} err={str(err)[:300] if err else 'None'}")
            self._setup_in_progress = False
            dlg.close()
            if ok:
                self._opencv_just_installed = True
            self._check_models()
            self._update_start_enabled()
            if ok:
                self._add_log("OpenCV installed. Restart ChronoArchiver.")
            else:
                self._add_log("OpenCV install failed.")
                if err:
                    for line in err.strip().split("\n")[:10]:
                        if line.strip():
                            self._add_log(f"  {line[:200]}")
            self._sig.prereqs_changed.emit()

        self._sig.setup_complete.connect(_on_done, Qt.ConnectionType.SingleShotConnection)
        dlg.show()
        threading.Thread(target=_task, daemon=True).start()

    def _on_uninstall_opencv(self):
        reply = QMessageBox.question(
            self,
            "Uninstall OpenCV",
            "Remove OpenCV from the app venv?\n\nAI Scanner will be disabled until you install OpenCV again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_in_progress = True
        self._update_start_enabled()

        def _task():
            ok = uninstall_opencv()
            self._sig.setup_complete.emit(ok)

        def _on_done(ok):
            debug(UTILITY_OPENCV_INSTALL, f"OpenCV uninstall _on_done ok={ok}")
            self._setup_in_progress = False
            if ok:
                self._opencv_just_installed = False
            self._add_log("OpenCV uninstalled." if ok else "OpenCV uninstall failed or not found.")
            self._check_models()
            self._update_start_enabled()
            self._sig.prereqs_changed.emit()

        self._sig.setup_complete.connect(_on_done, Qt.ConnectionType.SingleShotConnection)
        threading.Thread(target=_task, daemon=True).start()

    def _on_setup_models(self):
        missing = self._model_mgr.get_missing_models()
        if not missing:
            self._add_log("All models already present.")
            return
        total = self._model_mgr.get_total_download_size()
        mb = total / (1024 * 1024)
        size_str = f"~{mb:.1f} MB" if mb >= 0.1 else f"~{total / 1024:.1f} KB"
        reply = QMessageBox.question(
            self,
            "Setup AI Models",
            f"Download AI models (Face YuNet, Persons & Animals YOLOv8)?\n\n"
            f"Approximate download size: {size_str}\n\n"
            f"Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_models_only()

    def _setup_models_only(self):
        self._add_log("Starting model download...")
        self._setup_in_progress = True
        self._update_start_enabled()
        dlg = ModelSetupDialog(self._model_mgr, self)

        _last_log = [None]
        def _progress(downloaded, total_size, filename, overall, label, url):
            dlg.progress_update.emit(url, label, filename, downloaded, total_size, overall)
            pct = int(overall * 100)
            key = (label, pct)
            if key != _last_log[0]:
                _last_log[0] = key
                self._sig.log_msg.emit(f"Downloading: {label} ({pct}%)")

        def _on_done(ok):
            debug(UTILITY_MODEL_SETUP, f"Model setup _on_done RECV ok={ok} type={type(ok).__name__}")
            self._setup_in_progress = False
            dlg.close()
            self._bar.setFormat("Ready")
            self._lbl_status.setText("Ready")
            self._bar.setValue(0)
            self._check_models()
            self._update_start_enabled()
            self._add_log("Model setup complete." if ok else "Model setup failed or cancelled.")
            self._sig.prereqs_changed.emit()

        self._sig.setup_complete.connect(_on_done, Qt.ConnectionType.SingleShotConnection)

        def _task():
            debug(UTILITY_MODEL_SETUP, "Model setup popup: starting download_models")
            ok = self._model_mgr.download_models(_progress)
            self._sig.setup_complete.emit(ok)

        dlg.show()
        threading.Thread(target=_task, daemon=True).start()

    def _remove_models_only(self):
        reply = QMessageBox.question(
            self,
            "Uninstall Models",
            "Remove AI model files?\n\nRun Setup Models to re-download.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_in_progress = True
        self._update_start_enabled()

        def _task():
            try:
                model_dir = pathlib.Path(self._model_mgr.model_dir)
                if model_dir.exists():
                    for f in model_dir.iterdir():
                        try:
                            if f.is_file():
                                f.unlink()
                        except OSError as e:
                            self._sig.log_msg.emit(f"Could not remove {f.name}: {e}")
                    self._sig.log_msg.emit("AI models removed.")
                self._sig.remove_done.emit()
            except Exception as e:
                debug(UTILITY_AI_MEDIA_SCANNER, f"Remove models exception: {e}")
                self._sig.remove_done.emit()

        def _on_done():
            self._setup_in_progress = False
            self._check_models()
            self._update_start_enabled()
            self._sig.prereqs_changed.emit()

        self._sig.remove_done.connect(_on_done, Qt.ConnectionType.SingleShotConnection)
        threading.Thread(target=_task, daemon=True).start()

    def _browse(self):
        f = QFileDialog.getExistingDirectory(self, "Select Library to Scan")
        if f:
            self._edit_path.setText(f)

    def _browse_target(self):
        f = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if f:
            self._edit_target.setText(f)

    def _ask_raise_cap(self, list_name: str, current_cap: int) -> int | None:
        """
        Show dialog asking user to raise list cap. Called from main thread.
        Returns new cap (int > current_cap) or None to keep current cap.
        """
        label = "Keep list" if list_name == "keep" else "Others list"
        reply = QMessageBox.question(
            self,
            "List Cap Reached",
            f"The {label} has reached {current_cap:,} entries.\n\n"
            "Raise the cap for this session? (Reverts to 100,000 on next app start.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None
        new_cap, ok = QInputDialog.getInt(
            self,
            "Raise Cap",
            f"New cap for {label}:",
            value=current_cap * 2,
            minValue=current_cap + 1,
            maxValue=10_000_000,
            step=50_000,
        )
        return new_cap if ok and new_cap > current_cap else None

    def _process_cap_requests(self):
        """Process pending cap-raise requests from scanner thread (main-thread timer)."""
        try:
            while True:
                list_name, current_cap, result_holder, done_event = self._cap_request_queue.get_nowait()
                try:
                    result_holder.append(self._ask_raise_cap(list_name, current_cap))
                except Exception as e:
                    debug(UTILITY_AI_MEDIA_SCANNER, f"Cap dialog error: {e}")
                finally:
                    done_event.set()  # Always unblock worker so scan can continue
        except queue.Empty:
            pass

    def _run_job(self):
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            self._add_log("ERROR: Invalid directory.")
            debug(UTILITY_AI_MEDIA_SCANNER, f"ERROR: Invalid directory: {path or '(empty)'}")
            return

        debug(UTILITY_AI_MEDIA_SCANNER, f"Scan start: path={path}, recursive={self._chk_recursive.isChecked()}, keep_animals={self._chk_animals.isChecked()}")
        self._is_running = True
        self._bar.setFormat("%p%")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._lbl_status.setText("Scanning...")
        if self._status_cb:
            self._status_cb("scanning")
        self._update_start_enabled()
        self._btn_stop.setEnabled(True)
        self._cap_timer.start()

        def _log(msg): self._sig.log_msg.emit(msg)
        def _cap_callback(list_name: str, current_cap: int):
            """Request main-thread dialog; blocks until user responds."""
            result_holder = []
            done_event = threading.Event()
            self._cap_request_queue.put((list_name, current_cap, result_holder, done_event))
            done_event.wait()
            return result_holder[0] if result_holder else None
        self._engine = ScannerEngine(
            logger_callback=_log,
            model_dir=str(self._model_mgr.model_dir),
            on_list_cap_reached=_cap_callback,
        )
        self._engine.progress_callback = lambda c, t, eta, f: self._sig.progress.emit(
            min(1.0, c / max(t, 1)))

        def _run():
            try:
                self._engine.run_scan(path,
                    include_subfolders=self._chk_recursive.isChecked(),
                    keep_animals=self._chk_animals.isChecked(),
                    animal_threshold=self._spin_thresh.value() / 100.0)
            except Exception as e:
                self._sig.log_msg.emit(f"ERROR: {e}")
                debug(UTILITY_AI_MEDIA_SCANNER, f"Scanner thread exception: {e}")
            finally:
                self._sig.finished.emit()

        threading.Thread(target=_run, daemon=True).start()

    def get_activity(self):
        return "scanning" if self._is_running else "idle"

    def _stop_job(self):
        if self._engine:
            self._engine.cancel()
            debug(UTILITY_AI_MEDIA_SCANNER, "Scan stopped by user")
        self._is_running = False
        if self._status_cb:
            self._status_cb("idle")
        self._update_start_enabled()
        self._btn_stop.setEnabled(False)

    def _on_progress(self, val):
        self._bar.setValue(int(val * 100))

    def _on_finished(self):
        self._cap_timer.stop()
        self._is_running = False
        if self._status_cb:
            self._status_cb("idle")
        self._update_start_enabled()
        self._btn_stop.setEnabled(False)
        self._bar.setValue(100)
        self._bar.setFormat("Complete")
        self._lbl_status.setText("Scan Complete")
        self._add_log("Batch scan complete.")
        if self._engine:
            debug(UTILITY_AI_MEDIA_SCANNER, f"Scan finished: keep={len(self._engine.keep_list)}, move={len(self._engine.others_list)}")
        self._populate_results()
        self._update_move_start()
        QTimer.singleShot(2000, self._reset_bar_to_ready)

    def _reset_bar_to_ready(self):
        """After scan complete, reset bar to Ready state."""
        if not self._is_running:
            self._bar.setFormat("Ready")
            self._bar.setValue(0)
            self._lbl_status.setText("Ready")

    def _populate_results(self):
        self._list_keep.clear()
        self._list_move.clear()
        self._lbl_preview.clear()
        self._lbl_preview.setText("Select an item to preview")
        if not self._engine:
            return
        for p in self._engine.keep_list:
            it = QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            self._list_keep.addItem(it)
        for p in self._engine.others_list:
            it = QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            self._list_move.addItem(it)

    def _show_preview(self, path):
        """Show image preview for path, or placeholder."""
        if path and os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                scaled = pix.scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._lbl_preview.setPixmap(scaled)
                self._lbl_preview.setText("")
                return
        self._lbl_preview.clear()
        self._lbl_preview.setText("Preview unavailable" if path else "Select an item to preview")

    def _on_keep_selection_changed(self):
        self._list_move.blockSignals(True)
        self._list_move.clearSelection()
        self._list_move.blockSignals(False)
        items = self._list_keep.selectedItems()
        path = items[0].data(Qt.UserRole) if items else None
        self._show_preview(path)

    def _on_move_selection_changed(self):
        self._list_keep.blockSignals(True)
        self._list_keep.clearSelection()
        self._list_keep.blockSignals(False)
        items = self._list_move.selectedItems()
        path = items[0].data(Qt.UserRole) if items else None
        self._show_preview(path)

    def _update_move_copy_label(self):
        self._lbl_move_copy.setText(f"{self._combo_action.currentText()} (others)")

    def _copy_or_move_with_exif_correction(self, src: str, dest: str, action: str) -> bool:
        """Copy or move file with EXIF orientation correction for images. Returns True on success."""
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif", ".heic", ".heif"}
        ext = os.path.splitext(src)[1].lower()
        if PIL_AVAILABLE and ext in IMAGE_EXTS:
            try:
                with Image.open(src) as img:
                    corrected = ImageOps.exif_transpose(img)
                    save_kw = {}
                    if ext in (".jpg", ".jpeg"):
                        if corrected.mode in ("RGBA", "P"):
                            corrected = corrected.convert("RGB")
                        save_kw["quality"] = 95
                    corrected.save(dest, **save_kw)
                if action == "move":
                    os.unlink(src)
                return True
            except Exception as e:
                debug(UTILITY_AI_MEDIA_SCANNER, f"EXIF correct failed for {src}: {e}")
                return False
        if action == "move":
            shutil.move(src, dest)
        else:
            shutil.copy2(src, dest)
        return True

    def _update_move_start(self):
        target = self._edit_target.text().strip()
        target_ok = bool(target and os.path.isdir(target))
        has_files = self._engine and self._engine.others_list
        can = target_ok and bool(has_files)
        self._btn_start_move.setEnabled(can)
        if can:
            self._btn_start_move.setStyleSheet(
                "background-color:#10b981; color:#064e3b; border:2px solid #064e3b; "
                "font-size:9px; font-weight:900; min-height:24px;")
        else:
            self._btn_start_move.setStyleSheet(
                "font-size:8px; font-weight:700; min-height:24px; "
                "background:#1a1a1a; color:#6b7280; border:2px solid #262626;")
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _apply_move_copy(self):
        if not self._engine or not self._engine.others_list:
            if self._engine:
                self._add_log("No files to process. Run a scan first.")
            return
        dest_dir = self._edit_target.text().strip()
        if not dest_dir or not os.path.isdir(dest_dir):
            self._add_log("ERROR: Select a valid target folder.")
            debug(UTILITY_AI_MEDIA_SCANNER, f"Apply ERROR: invalid target {dest_dir}")
            return
        action = self._combo_action.currentText().lower()
        count = 0
        for p in self._engine.others_list:
            if os.path.isfile(p):
                try:
                    dest_path = os.path.join(dest_dir, os.path.basename(p))
                    if os.path.exists(dest_path):
                        base, ext = os.path.splitext(os.path.basename(p))
                        for n in range(1, 1000):
                            dest_path = os.path.join(dest_dir, f"{base}_{n}{ext}")
                            if not os.path.exists(dest_path):
                                break
                    if self._copy_or_move_with_exif_correction(p, dest_path, action):
                        count += 1
                    else:
                        # Fallback to plain copy/move if EXIF correction failed
                        if action == "move":
                            shutil.move(p, dest_path)
                        else:
                            shutil.copy2(p, dest_path)
                        count += 1
                except Exception as e:
                    self._add_log(f"{action.title()} failed: {p} — {e}")
                    debug(UTILITY_AI_MEDIA_SCANNER, f"{action} failed: {p} — {e}")
        self._add_log(f"{action.title()}ed {count} files to {dest_dir}.")
        debug(UTILITY_AI_MEDIA_SCANNER, f"Apply: {action}ed {count} to {dest_dir}")
        if action == "move":
            self._list_move.clear()
            self._engine.others_list.clear()
        self._update_move_start()

    def _export_csv(self):
        if not self._engine:
            self._add_log("Run a scan first.")
            debug(UTILITY_AI_MEDIA_SCANNER, "Export CSV: no scan results")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Category", "Path"])
                for p in self._engine.keep_list:
                    w.writerow(["Keep", p])
                for p in self._engine.others_list:
                    w.writerow(["Move", p])
            self._add_log(f"Exported to {path}.")
            debug(UTILITY_AI_MEDIA_SCANNER, f"Export CSV: {path} (keep={len(self._engine.keep_list)}, move={len(self._engine.others_list)})")
        except Exception as e:
            self._add_log(f"Export failed: {e}")
            debug(UTILITY_AI_MEDIA_SCANNER, f"Export CSV failed: {e}")

    def append_external_line(self, msg: str):
        """Subprocess / pip output (main thread)."""
        self._add_log(msg)

    def _add_log(self, msg):
        sb = self._log_edit.verticalScrollBar()
        at_bot = sb.value() >= sb.maximum() - 4
        html_line = message_to_html(msg)
        cursor = self._log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html_line + "<br>")
        if at_bot:
            sb.setValue(sb.maximum())
        if self._log_cb:
            self._log_cb(msg)
