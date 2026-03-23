"""
scanner_panel.py — AI Media Scanner panel for ChronoArchiver.
Visual style exactly matches Mass AV1 Encoder v12.
"""

import csv
import os
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
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QSpinBox, QFrame, QDialog, QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtGui import QPixmap

import pathlib
import platformdirs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.scanner import ScannerEngine, OPENCV_AVAILABLE
from core.model_manager import ModelManager
from core.venv_manager import (
    get_pip_exe, install_package, ensure_venv,
    detect_gpu, get_opencv_install_size, install_opencv, uninstall_opencv,
)
from core.debug_logger import debug, UTILITY_AI_MEDIA_SCANNER


class _Signals(QObject):
    log_msg  = Signal(str)
    progress = Signal(float)
    finished = Signal()
    setup_complete = Signal(bool)
    remove_done = Signal()
    version_check_done = Signal(bool, bool)  # models_update, opencv_update
    setup_phase = Signal(str, str)  # phase_name, detail


class OpenCVSetupDialog(QDialog):
    """Popup for OpenCV install progress."""
    phase_update = Signal(str, str)  # phase, detail — emitted from worker, handled on main thread

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
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(14)
        v.addWidget(self._bar)
        v.addStretch()
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self.phase_update.connect(self._on_phase_update)

    def _on_phase_update(self, phase: str, detail: str):
        self._lbl_phase.setText(phase)
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

        _model_dir = pathlib.Path(platformdirs.user_data_dir("ChronoArchiver", "UnDadFeated")) / "models"
        _model_dir.mkdir(parents=True, exist_ok=True)
        self._model_mgr = ModelManager(str(_model_dir))

        self._engine = None  # Initialized in _run_job
        self._is_running = False

        _shint = "font-size: 7px; color: #444; margin-top: -1px;"

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(2)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        h_strip = QHBoxLayout()
        h_strip.setSpacing(6)
        _strip_h = 70  # Compact height for top row

        # 1. Directories (compact)
        grp_dir = QGroupBox("Directories")
        grp_dir.setFixedHeight(_strip_h)
        v_dir = QVBoxLayout(grp_dir)
        v_dir.setContentsMargins(6, 2, 6, 2)
        v_dir.setSpacing(0)
        h_src = QHBoxLayout()
        h_src.setSpacing(4)
        self._edit_path = QLineEdit()
        self._edit_path.setPlaceholderText("SELECT PHOTO LIBRARY...")
        self._edit_path.textChanged.connect(self._update_start_enabled)
        self._edit_path.setStyleSheet(
            "color:#fff; font-size:11px; font-weight:500; min-height:22px; "
            "background:#121212; border:1px solid #1a1a1a;")
        h_src.addWidget(self._edit_path, 1)
        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setFixedWidth(48)
        self._btn_browse.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; border:2px solid transparent; min-height:22px;")
        self._btn_browse.clicked.connect(self._browse)
        h_src.addWidget(self._btn_browse)
        v_dir.addLayout(h_src)
        v_dir.addWidget(QLabel("Photos for AI detection (YuNet/SSD)", styleSheet=_shint))
        h_strip.addWidget(grp_dir, 10)

        # 2. Options (compact, single row)
        grp_opts = QGroupBox("Options")
        grp_opts.setFixedHeight(_strip_h)
        h_opts = QHBoxLayout(grp_opts)
        h_opts.setContentsMargins(6, 2, 6, 2)
        h_opts.setSpacing(8)
        self._chk_recursive = QCheckBox("Recursive")
        self._chk_recursive.setChecked(True)
        self._chk_recursive.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        self._chk_animals = QCheckBox("Keep Animals")
        self._chk_animals.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        self._chk_animals.setToolTip("Also keep photos with detected animals")
        lbl_conf = QLabel("Conf:")
        lbl_conf.setStyleSheet("font-size:7px; color:#888;")
        self._spin_thresh = QSpinBox()
        self._spin_thresh.setRange(10, 90)
        self._spin_thresh.setValue(40)
        self._spin_thresh.setSuffix("%")
        self._spin_thresh.setStyleSheet("font-size:8px;")
        self._spin_thresh.setFixedWidth(55)
        h_opts.addWidget(self._chk_recursive)
        h_opts.addWidget(self._chk_animals)
        h_opts.addWidget(lbl_conf)
        h_opts.addWidget(self._spin_thresh)
        h_opts.addStretch()
        h_strip.addWidget(grp_opts, 2)

        # 3. Engine Status (expanded: OpenCV row + Models row)
        grp_mod = QGroupBox("Engine Status")
        grp_mod.setFixedHeight(100)
        v_mod = QVBoxLayout(grp_mod)
        v_mod.setContentsMargins(6, 2, 6, 2)
        v_mod.setSpacing(2)
        h_cv = QHBoxLayout()
        self._lbl_opencv = QLabel("Checking...")
        self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
        h_cv.addWidget(QLabel("OpenCV:", styleSheet="font-size:7px; color:#888;"))
        h_cv.addWidget(self._lbl_opencv, 1)
        self._btn_install_cv = QPushButton("Install OpenCV")
        self._btn_install_cv.setStyleSheet("font-size:7px; font-weight:700; min-height:16px;")
        self._btn_install_cv.clicked.connect(self._on_install_opencv)
        self._btn_uninstall_cv = QPushButton("Uninstall OpenCV")
        self._btn_uninstall_cv.setStyleSheet("font-size:7px; font-weight:700; min-height:16px; color:#6b7280;")
        self._btn_uninstall_cv.clicked.connect(self._on_uninstall_opencv)
        h_cv.addWidget(self._btn_install_cv)
        h_cv.addWidget(self._btn_uninstall_cv)
        v_mod.addLayout(h_cv)
        h_mod = QHBoxLayout()
        self._lbl_model = QLabel("Checking...")
        self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
        h_mod.addWidget(QLabel("Models:", styleSheet="font-size:7px; color:#888;"))
        h_mod.addWidget(self._lbl_model, 1)
        self._btn_update = QPushButton("Update!")
        self._btn_update.setStyleSheet("font-size:7px; font-weight:700; color:#eab308; border:2px solid #eab308; min-height:16px;")
        self._btn_update.clicked.connect(self._setup_models_only)
        self._btn_update.hide()
        self._btn_setup = QPushButton("Setup Models")
        self._btn_setup.setStyleSheet("font-size:7px; font-weight:700; min-height:16px;")
        self._btn_setup.clicked.connect(self._on_setup_models)
        self._btn_remove = QPushButton("Remove Models")
        self._btn_remove.setStyleSheet("font-size:7px; font-weight:700; min-height:16px; color:#6b7280;")
        self._btn_remove.clicked.connect(self._remove_models_only)
        self._btn_remove.setToolTip("Remove AI model files only")
        h_mod.addWidget(self._btn_update)
        h_mod.addWidget(self._btn_setup)
        h_mod.addWidget(self._btn_remove)
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
        self._btn_start.setFixedHeight(28)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self._run_job)
        h_exec.addWidget(self._btn_start)
        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setFixedHeight(28)
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
        h_btns.addWidget(QLabel("Target:", styleSheet="font-size:8px; color:#888;"))
        self._edit_target = QLineEdit()
        self._edit_target.setPlaceholderText("Select target folder...")
        self._edit_target.setStyleSheet(
            "color:#fff; font-size:10px; min-height:20px; "
            "background:#121212; border:1px solid #1a1a1a;")
        self._edit_target.textChanged.connect(self._update_move_start)
        h_btns.addWidget(self._edit_target, 1)
        self._btn_browse_target = QPushButton("Browse")
        self._btn_browse_target.setFixedWidth(52)
        self._btn_browse_target.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; border:2px solid transparent; min-height:20px;")
        self._btn_browse_target.clicked.connect(self._browse_target)
        h_btns.addWidget(self._btn_browse_target)
        self._combo_action = QComboBox()
        self._combo_action.addItems(["Move", "Copy"])
        self._combo_action.setStyleSheet("font-size:8px; min-width:72px;")
        self._combo_action.setCurrentIndex(0)
        self._combo_action.currentTextChanged.connect(self._update_move_copy_label)
        h_btns.addWidget(self._combo_action)
        self._btn_start_move = QPushButton("START")
        self._btn_start_move.setObjectName("btnStartMove")
        self._btn_start_move.setStyleSheet(
            "font-size:8px; font-weight:700; min-height:20px; "
            "background:#1a1a1a; color:#6b7280; border:1px solid #262626;")
        self._btn_start_move.clicked.connect(self._apply_move_copy)
        self._btn_start_move.setEnabled(False)
        h_btns.addWidget(self._btn_start_move)
        self._btn_export = QPushButton("Export CSV")
        self._btn_export.setStyleSheet("font-size:8px; font-weight:700;")
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
        self._log_list = QListWidget()
        self._log_list.setMaximumHeight(100)
        v_log.addWidget(self._log_list)
        root.addWidget(grp_log, 0)

        self._model_update_available = False
        self._opencv_update_available = False
        self._version_check_started = False
        self._setup_in_progress = False
        # Check models and version on init
        QTimer.singleShot(500, self._check_models)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if not self._setup_in_progress:
            self._check_models()

    def _check_models(self):
        if not OPENCV_AVAILABLE:
            self._lbl_opencv.setText("Not installed")
            self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#ef4444;")
            self._btn_install_cv.show()
            self._btn_uninstall_cv.hide()
        else:
            gpu = detect_gpu()
            suf = " (CUDA)" if gpu == "nvidia" else (" (OpenCL)" if gpu == "amd" else "")
            self._lbl_opencv.setText(f"Ready{suf}")
            self._lbl_opencv.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
            self._btn_install_cv.hide()
            self._btn_uninstall_cv.show()

        ready = self._model_mgr.is_up_to_date()
        if ready:
            self._lbl_model.setText("Ready")
            self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
            self._btn_setup.hide()
            update_avail = self._model_update_available or self._opencv_update_available
            self._btn_update.setVisible(update_avail)
            self._start_version_check()
        else:
            self._lbl_model.setText("Missing")
            self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#ef4444;")
            self._btn_setup.show()
            self._btn_update.hide()

        self._update_start_enabled()

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
            models_up = False
            opencv_up = False
            try:
                models_up = self._model_mgr.check_model_update_available()
            except Exception:
                pass
            try:
                pip_exe = get_pip_exe()
                if pip_exe.exists():
                    r = subprocess.run(
                        [str(pip_exe), "list", "--outdated"],
                        capture_output=True, text=True, timeout=10
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
        if not OPENCV_AVAILABLE:
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
        can = OPENCV_AVAILABLE and models_ready and path_ok and not self._is_running
        self._btn_start.setEnabled(can)
        busy = self._setup_in_progress or self._is_running
        self._btn_remove.setEnabled(not busy)
        self._btn_install_cv.setEnabled(not busy)
        self._btn_uninstall_cv.setEnabled(not busy and OPENCV_AVAILABLE)
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _clear_guide_glow(self, w):
        if not w:
            return
        if w == self._btn_start:
            w.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid transparent; font-size:10px; font-weight:900;")
        elif w == self._btn_start_move:
            if self._btn_start_move.isEnabled():
                w.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid transparent; font-size:9px; font-weight:900; min-height:20px;")
            else:
                w.setStyleSheet("font-size:8px; font-weight:700; min-height:20px; background:#1a1a1a; color:#6b7280; border:1px solid #262626;")
        elif w == self._btn_browse:
            w.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; border:2px solid transparent; min-height:22px;")
        elif w == self._btn_browse_target:
            w.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; border:2px solid transparent; min-height:20px;")
        elif w == self._btn_setup:
            w.setStyleSheet("font-size:7px; font-weight:700; min-height:16px;")
        elif w == self._btn_install_cv:
            w.setStyleSheet("font-size:7px; font-weight:700; min-height:16px;")
        elif w == self._btn_update:
            w.setStyleSheet("font-size:8px; font-weight:700; color:#eab308; border:2px solid #eab308; min-height:18px; min-width:52px;")

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
        if self._guide_glow_phase:
            if target == self._btn_start:
                target.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid #ef4444; font-size:10px; font-weight:900;")
            elif target == self._btn_start_move:
                target.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid #ef4444; font-size:9px; font-weight:900; min-height:20px;")
            else:
                style = "font-size:8px; font-weight:700; color:#ef4444; border:2px solid #ef4444;"
                if target == self._btn_browse or target == self._btn_browse_target:
                    style += " min-height:22px;" if target == self._btn_browse else " min-height:20px;"
                elif target == self._btn_setup:
                    style += " min-height:16px;"
                elif target == self._btn_install_cv:
                    style += " min-height:16px;"
                elif target == self._btn_update:
                    style += " min-height:18px; min-width:52px;"
                target.setStyleSheet(style)
        else:
            self._clear_guide_glow(target)

    def _on_install_opencv(self):
        use_cuda = detect_gpu() == "nvidia"
        _, size_str = get_opencv_install_size(use_cuda)
        pkg = "OpenCV (CUDA)" if use_cuda else "OpenCV"
        reply = QMessageBox.question(
            self,
            "Install OpenCV",
            f"Download and install {pkg}?\n\n"
            f"Approximate download size: {size_str}\n\n"
            f"This will install into the app's private venv (no sudo required).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._setup_in_progress = True
        self._update_start_enabled()
        dlg = OpenCVSetupDialog(self)

        def _prog(phase, detail=""):
            dlg.phase_update.emit(phase, detail)

        def _task():
            try:
                pip = get_pip_exe()
                if not pip.exists():
                    _prog("Creating venv...", "")
                    ok = ensure_venv(progress_callback=_prog, skip_opencv=True)
                    if not ok:
                        _prog("Failed", "Could not create venv")
                        time.sleep(2)
                        self._sig.setup_complete.emit(False)
                        return
                ok = install_opencv(progress_callback=_prog, use_cuda=use_cuda)
                self._sig.setup_complete.emit(ok)
            except Exception as e:
                _prog("Failed", str(e)[:80])
                time.sleep(2)
                self._sig.setup_complete.emit(False)

        def _on_done(ok):
            self._setup_in_progress = False
            dlg.close()
            self._check_models()
            self._update_start_enabled()
            self._add_log("OpenCV installed. Restart ChronoArchiver." if ok else "OpenCV install failed.")

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
        if uninstall_opencv():
            self._add_log("OpenCV uninstalled. Restart ChronoArchiver.")
        else:
            self._add_log("OpenCV uninstall failed or not found.")
        self._check_models()
        self._update_start_enabled()

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
            f"Download AI models (Face YuNet, Animals SSD)?\n\n"
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

        def _progress(downloaded, total_size, filename, overall, label, url):
            dlg.progress_update.emit(url, label, filename, downloaded, total_size, overall)
            self._sig.log_msg.emit(f"Downloading: {label} ({int(overall * 100)}%)")

        def _on_done(ok):
            self._setup_in_progress = False
            dlg.close()
            self._bar.setFormat("Ready")
            self._lbl_status.setText("Ready")
            self._bar.setValue(0)
            self._check_models()
            self._update_start_enabled()
            self._add_log("Model setup complete." if ok else "Model setup failed or cancelled.")

        self._sig.setup_complete.connect(_on_done, Qt.ConnectionType.SingleShotConnection)

        def _task():
            ok = self._model_mgr.download_models(_progress)
            self._sig.setup_complete.emit(ok)

        dlg.show()
        threading.Thread(target=_task, daemon=True).start()

    def _remove_models_only(self):
        reply = QMessageBox.question(
            self,
            "Remove AI Models",
            "Remove AI model files only?\n\nRun Setup Models to re-download.",
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

        def _log(msg): self._sig.log_msg.emit(msg)
        self._engine = ScannerEngine(logger_callback=_log, model_dir=str(self._model_mgr.model_dir))
        # progress_callback is an attribute, not a constructor arg
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
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".heic"}
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
                "background-color:#10b981; color:#064e3b; border:2px solid transparent; "
                "font-size:9px; font-weight:900; min-height:20px;")
        else:
            self._btn_start_move.setStyleSheet(
                "font-size:8px; font-weight:700; min-height:20px; "
                "background:#1a1a1a; color:#6b7280; border:1px solid #262626;")
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

    def _add_log(self, msg):
        sb = self._log_list.verticalScrollBar()
        at_bot = sb.value() >= sb.maximum() - 4
        self._log_list.addItem(msg)
        if at_bot:
            self._log_list.scrollToBottom()
        if self._log_list.count() > 1000:
            self._log_list.takeItem(0)
        if self._log_cb:
            self._log_cb(msg)
