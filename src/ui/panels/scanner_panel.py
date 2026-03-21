"""
scanner_panel.py — AI Media Scanner panel for ChronoArchiver.
Visual style exactly matches Mass AV1 Encoder v12.
"""

import csv
import os
import shutil
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QSpinBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QPixmap

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.scanner import ScannerEngine
from core.model_manager import ModelManager
from core.debug_logger import debug, UTILITY_AI_MEDIA_SCANNER


class _Signals(QObject):
    log_msg  = Signal(str)
    progress = Signal(float)
    finished = Signal()


class AIScannerPanel(QWidget):

    def __init__(self, log_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb = log_callback
        self._sig    = _Signals()
        self._sig.log_msg.connect(self._add_log)
        self._sig.progress.connect(self._on_progress)
        self._sig.finished.connect(self._on_finished)

        _base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _model_dir = os.path.join(_base, 'core', 'models')
        self._model_mgr = ModelManager(_model_dir)

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
        self._edit_path.setStyleSheet(
            "color:#fff; font-size:11px; font-weight:500; min-height:22px; "
            "background:#121212; border:1px solid #1a1a1a;")
        h_src.addWidget(self._edit_path, 1)
        btn_br = QPushButton("Browse")
        btn_br.setFixedWidth(48)
        btn_br.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; min-height:22px;")
        btn_br.clicked.connect(self._browse)
        h_src.addWidget(btn_br)
        v_dir.addLayout(h_src)
        v_dir.addWidget(QLabel("Photos for AI detection (YuNet/SSD)", styleSheet=_shint))
        h_strip.addWidget(grp_dir, 10)

        # 2. Options (compact)
        grp_opts = QGroupBox("Options")
        grp_opts.setFixedHeight(_strip_h)
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(6, 2, 6, 2)
        v_opts.setSpacing(2)
        h_opts = QHBoxLayout()
        self._chk_recursive = QCheckBox("Recursive")
        self._chk_recursive.setChecked(True)
        self._chk_recursive.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        self._chk_animals = QCheckBox("Keep Animals")
        self._chk_animals.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        self._chk_animals.setToolTip("Also keep photos with detected animals")
        h_opts.addWidget(self._chk_recursive)
        h_opts.addWidget(self._chk_animals)
        v_opts.addLayout(h_opts)
        h_thr = QHBoxLayout()
        h_thr.setSpacing(4)
        lbl_thr = QLabel("Conf:"); lbl_thr.setStyleSheet("font-size:7px; color:#888;")
        self._spin_thresh = QSpinBox()
        self._spin_thresh.setRange(10, 90)
        self._spin_thresh.setValue(40)
        self._spin_thresh.setSuffix("%")
        self._spin_thresh.setStyleSheet("font-size:8px;")
        self._spin_thresh.setFixedWidth(55)
        h_thr.addWidget(lbl_thr)
        h_thr.addWidget(self._spin_thresh)
        v_opts.addLayout(h_thr)
        h_strip.addWidget(grp_opts, 2)

        # 3. Engine Status (compact)
        grp_mod = QGroupBox("Engine Status")
        grp_mod.setFixedHeight(_strip_h)
        v_mod = QVBoxLayout(grp_mod)
        v_mod.setContentsMargins(6, 2, 6, 2)
        v_mod.setSpacing(2)
        self._lbl_model = QLabel("Checking models...")
        self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
        v_mod.addWidget(self._lbl_model)
        self._btn_setup = QPushButton("Setup Models")
        self._btn_setup.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        self._btn_setup.clicked.connect(self._setup_models)
        v_mod.addWidget(self._btn_setup)
        h_strip.addWidget(grp_mod, 2)

        root.addLayout(h_strip)

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
        self._list_keep.itemSelectionChanged.connect(self._on_selection_changed)
        v_k.addWidget(self._list_keep)
        v_m = QVBoxLayout()
        v_m.addWidget(QLabel("Move (others)", styleSheet="font-size:8px; font-weight:700;"))
        self._list_move = QListWidget()
        self._list_move.setMinimumWidth(160)
        self._list_move.itemSelectionChanged.connect(self._on_selection_changed)
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
        self._btn_move_files = QPushButton("Move Files")
        self._btn_move_files.setStyleSheet("font-size:8px; font-weight:700;")
        self._btn_move_files.clicked.connect(self._move_others)
        self._btn_export = QPushButton("Export CSV")
        self._btn_export.setStyleSheet("font-size:8px; font-weight:700;")
        self._btn_export.clicked.connect(self._export_csv)
        h_btns.addWidget(self._btn_move_files)
        h_btns.addWidget(self._btn_export)
        h_btns.addStretch()
        v_res.addLayout(h_btns)
        root.addWidget(grp_res, 1)

        # ── CONSOLE ───────────────────────────────────────────────────────────
        grp_log = QGroupBox("Console")
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(6, 4, 6, 4)
        v_log.setSpacing(0)
        self._log_list = QListWidget()
        v_log.addWidget(self._log_list)
        root.addWidget(grp_log, 1)

        # Check models on init
        QTimer.singleShot(500, self._check_models)

    def _check_models(self):
        if self._model_mgr.is_up_to_date():
            self._lbl_model.setText("Models Ready")
            self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#10b981;")
            self._btn_setup.hide()
            debug(UTILITY_AI_MEDIA_SCANNER, "Models check: ready")
        else:
            self._lbl_model.setText("ResNet Needs Setup")
            self._lbl_model.setStyleSheet("font-size:8px; font-weight:700; color:#ef4444;")
            self._btn_setup.show()
            debug(UTILITY_AI_MEDIA_SCANNER, f"Models check: missing {self._model_mgr.get_missing_models()}")

    def _setup_models(self):
        self._add_log("Starting model setup...")
        debug(UTILITY_AI_MEDIA_SCANNER, "Model setup started")
        def _progress(downloaded, total_size, filename):
            if total_size > 0:
                pct = int(downloaded / total_size * 100)
                self._sig.log_msg.emit(f"Downloading: {filename} ({pct}%)")
            else:
                self._sig.log_msg.emit(f"Downloading: {filename}...")
        def _task():
            ok = self._model_mgr.download_models(_progress)
            debug(UTILITY_AI_MEDIA_SCANNER, f"Model setup complete: ok={ok}")
            QTimer.singleShot(0, self._check_models)
        threading.Thread(target=_task, daemon=True).start()

    def _browse(self):
        f = QFileDialog.getExistingDirectory(self, "Select Library to Scan")
        if f:
            self._edit_path.setText(f)

    def _run_job(self):
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            self._add_log("ERROR: Invalid directory.")
            debug(UTILITY_AI_MEDIA_SCANNER, f"ERROR: Invalid directory: {path or '(empty)'}")
            return

        debug(UTILITY_AI_MEDIA_SCANNER, f"Scan start: path={path}, recursive={self._chk_recursive.isChecked()}, keep_animals={self._chk_animals.isChecked()}")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

        def _log(msg): self._sig.log_msg.emit(msg)
        self._engine = ScannerEngine(logger_callback=_log)
        # progress_callback is an attribute, not a constructor arg
        self._engine.progress_callback = lambda c, t, eta, f: self._sig.progress.emit(c / max(t,1))

        def _run():
            self._engine.run_scan(path,
                include_subfolders=self._chk_recursive.isChecked(),
                keep_animals=self._chk_animals.isChecked(),
                animal_threshold=self._spin_thresh.value() / 100.0)
            self._sig.finished.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _stop_job(self):
        if self._engine:
            self._engine.cancel()
            debug(UTILITY_AI_MEDIA_SCANNER, "Scan stopped by user")
        self._is_running = False
        self._btn_stop.setEnabled(False)

    def _on_progress(self, val):
        self._bar.setValue(int(val * 100))

    def _on_finished(self):
        self._is_running = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._bar.setFormat("Complete")
        self._lbl_status.setText("Scan Complete")
        self._add_log("Batch scan complete.")
        if self._engine:
            debug(UTILITY_AI_MEDIA_SCANNER, f"Scan finished: keep={len(self._engine.keep_list)}, move={len(self._engine.others_list)}")
        self._populate_results()

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

    def _on_selection_changed(self):
        for lst in (self._list_keep, self._list_move):
            items = lst.selectedItems()
            if items:
                path = items[0].data(Qt.UserRole)
                if path and os.path.isfile(path):
                    pix = QPixmap(path)
                    if not pix.isNull():
                        scaled = pix.scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self._lbl_preview.setPixmap(scaled)
                        self._lbl_preview.setText("")
                        return
                else:
                    self._lbl_preview.clear()
                    self._lbl_preview.setText("Preview unavailable")
                    return
        self._lbl_preview.clear()
        self._lbl_preview.setText("Select an item to preview")

    def _move_others(self):
        if not self._engine or not self._engine.others_list:
            self._add_log("No files to move. Run a scan first.")
            debug(UTILITY_AI_MEDIA_SCANNER, "Move Files: no files to move")
            return
        base = self._edit_path.text().strip()
        if not base or not os.path.isdir(base):
            self._add_log("ERROR: Invalid source path.")
            debug(UTILITY_AI_MEDIA_SCANNER, f"Move Files ERROR: invalid base path {base}")
            return
        dest_dir = os.path.join(base, "Archived_Others")
        os.makedirs(dest_dir, exist_ok=True)
        moved = 0
        for p in self._engine.others_list:
            if os.path.isfile(p):
                try:
                    shutil.move(p, os.path.join(dest_dir, os.path.basename(p)))
                    moved += 1
                except Exception as e:
                    self._add_log(f"Move failed: {p} — {e}")
                    debug(UTILITY_AI_MEDIA_SCANNER, f"Move failed: {p} — {e}")
        self._add_log(f"Moved {moved} files to {dest_dir}.")
        debug(UTILITY_AI_MEDIA_SCANNER, f"Move Files: moved {moved} to {dest_dir}")
        self._list_move.clear()
        self._engine.others_list.clear()

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
