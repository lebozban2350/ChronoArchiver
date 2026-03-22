"""
encoder_panel.py — Mass AV1 Encoder panel for ChronoArchiver.
Visual style exactly matches Mass AV1 Encoder v12.
Uses src/core/av1_engine.py and src/core/av1_settings.py unchanged.
"""

import os
import platform
import threading
import time
import subprocess

import psutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox,
    QProgressBar, QFileDialog, QComboBox, QSlider,
    QListWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.av1_engine import AV1EncoderEngine, EncodingProgress
from core.av1_settings import AV1Settings
from core.debug_logger import debug, UTILITY_MASS_AV1_ENCODER


class _Signals(QObject):
    progress  = Signal(int, object)   # job_id, EncodingProgress
    details   = Signal(int, str, str) # job_id, vid, aud
    finished  = Signal(int, bool, str, str)
    log_msg   = Signal(str)


class AV1EncoderPanel(QWidget):

    def __init__(self, log_callback=None, metrics_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb  = log_callback
        self._metrics_cb = metrics_callback
        self._sig     = _Signals()
        self._sig.progress.connect(self._on_progress)
        self._sig.details.connect(self._on_details)
        self._sig.finished.connect(self._on_encode_finished)
        self._sig.log_msg.connect(self._add_log)

        self._settings = AV1Settings()

        self._is_encoding    = False
        self._is_paused      = False
        self._engine_pool    = []
        self._queue          = []
        self._queue_lock     = threading.Lock()
        self._queue_sizes    = {}
        self._total_q_bytes  = 0.0
        self._done_bytes     = 0.0
        self._total_count    = 0
        self._done_count     = 0
        self._active_jobs    = 0
        self._active_lock    = threading.Lock()
        self._job_progress   = {}
        self._job_speeds     = {}
        self._current_files  = {}
        self._total_saved    = 0
        self._batch_start    = 0.0
        self._gpu_cache      = "0%"
        self._gpu_counter    = 0

        _shint = "font-size: 7px; color: #444; margin-top: -1px;"
        _slbl  = "font-size: 8px; font-weight: 700; color: #aaa;"
        _combo_style = (
            "QComboBox { font-size: 9px; padding: 0 4px; min-height: 12px; max-height: 16px; }"
            "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: right; width: 16px; }"
            "QComboBox QAbstractItemView { min-height: 80px; max-height: 160px; outline: none; padding: 2px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(1)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        # Layout: [Directories (top) | Options (right, full height)]
        #         [Configuration (bottom) |
        grid_strip = QGridLayout()
        grid_strip.setSpacing(6)

        # 1. Directories (top-left)
        grp_dir = QGroupBox("Directories")
        v_dir = QVBoxLayout(grp_dir)
        v_dir.setContentsMargins(6, 2, 6, 2)
        v_dir.setSpacing(1)

        self._edit_src = QLineEdit()
        self._edit_src.setPlaceholderText("SOURCE PATH (local or smb://)")
        self._edit_src.setStyleSheet(
            "color:#fff; font-size:12px; font-weight:500; "
            "background:#121212; border:1px solid #1a1a1a;")
        self._edit_src.setText(self._settings.get("source_folder") or "")

        h_src = QHBoxLayout(); h_src.setSpacing(4)
        h_src.addWidget(self._edit_src, 1)
        btn_src = QPushButton("Browse"); btn_src.setFixedWidth(52)
        btn_src.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        btn_src.clicked.connect(self._browse_src)
        h_src.addWidget(btn_src)
        v_dir.addLayout(h_src)
        self._scan_debounce = QTimer(self)
        self._scan_debounce.setSingleShot(True)
        self._scan_debounce.timeout.connect(self._auto_scan)
        self._edit_src.textChanged.connect(self._on_src_changed)
        self._edit_src.textChanged.connect(self._update_start_enabled)
        v_dir.addWidget(QLabel("Source — local path or smb:// network share",
                               styleSheet=_shint))

        self._edit_dst = QLineEdit()
        self._edit_dst.setPlaceholderText("TARGET PATH (local or smb://)")
        self._edit_dst.setStyleSheet(
            "color:#fff; font-size:12px; font-weight:500; "
            "background:#121212; border:1px solid #1a1a1a;")
        self._edit_dst.setText(self._settings.get("target_folder") or "")

        h_dst = QHBoxLayout()
        h_dst.addWidget(self._edit_dst, 1)
        btn_dst = QPushButton("Browse"); btn_dst.setFixedWidth(52)
        btn_dst.setStyleSheet("font-size:8px; font-weight:700; color:#aaa;")
        btn_dst.clicked.connect(self._browse_dst)
        h_dst.addWidget(btn_dst)
        self._edit_dst.textChanged.connect(self._update_start_enabled)
        v_dir.addLayout(h_dst)
        v_dir.addWidget(QLabel("Target — AV1 encoded output destination",
                               styleSheet=_shint))

        grp_dir.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid_strip.addWidget(grp_dir, 0, 0)

        # 2. Configuration (bottom-left)
        grp_cfg = QGroupBox("Configuration")
        v_cfg = QVBoxLayout(grp_cfg)
        v_cfg.setContentsMargins(6, 1, 6, 1)
        v_cfg.setSpacing(0)

        # Quality
        h_q = QHBoxLayout(); h_q.setSpacing(4)
        lbl_q = QLabel("Quality"); lbl_q.setStyleSheet(_slbl); lbl_q.setFixedWidth(42)
        self._lbl_qval = QLabel(str(self._settings.get("quality")))
        self._lbl_qval.setFixedWidth(20)
        self._lbl_qval.setStyleSheet("font-size:10px; color:#10b981; font-weight:bold;")
        self._slider_q = QSlider(Qt.Horizontal)
        self._slider_q.setRange(0, 63)
        self._slider_q.setValue(self._settings.get("quality"))
        self._slider_q.valueChanged.connect(self._on_quality_changed)
        h_q.addWidget(lbl_q); h_q.addWidget(self._lbl_qval)
        h_q.addWidget(self._slider_q, 1)
        self._lbl_cq_hint = QLabel("CQ — lower = better quality", styleSheet="font-size:7px; color:#444;")
        h_q.addWidget(self._lbl_cq_hint)
        v_cfg.addLayout(h_q)

        # Preset
        h_p = QHBoxLayout(); h_p.setSpacing(4)
        lbl_p = QLabel("Preset"); lbl_p.setStyleSheet(_slbl); lbl_p.setFixedWidth(42)
        self._combo_preset = QComboBox()
        self._combo_preset.setStyleSheet(_combo_style)
        self._combo_preset.setFixedHeight(16)
        self._combo_preset.addItems([
            "P7: Deep Archival", "P6: High Quality", "P5: Balanced",
            "P4: Standard", "P3: Fast", "P2: Draft", "P1: Preview"
        ])
        curr_p = self._settings.get("preset").upper()
        for i in range(self._combo_preset.count()):
            if self._combo_preset.itemText(i).startswith(curr_p):
                self._combo_preset.setCurrentIndex(i); break
        self._combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        self._combo_preset.currentIndexChanged.connect(self._update_cq_hint)
        h_p.addWidget(lbl_p); h_p.addWidget(self._combo_preset, 1)
        h_p.addWidget(QLabel("Encode speed vs. efficiency tradeoff", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_p)

        # Threads
        h_t = QHBoxLayout(); h_t.setSpacing(4)
        lbl_t = QLabel("Threads"); lbl_t.setStyleSheet(_slbl); lbl_t.setFixedWidth(42)
        self._combo_jobs = QComboBox()
        self._combo_jobs.setStyleSheet(_combo_style)
        self._combo_jobs.setFixedHeight(16)
        self._combo_jobs.addItems(["1", "2", "4"])
        j = self._settings.get("concurrent_jobs")
        self._combo_jobs.setCurrentIndex(0 if j == 1 else (1 if j == 2 else 2))
        self._combo_jobs.currentIndexChanged.connect(self._on_jobs_changed)
        h_t.addWidget(lbl_t); h_t.addWidget(self._combo_jobs, 1)
        h_t.addWidget(QLabel("Parallel encoding slots (1 / 2 / 4)", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_t)

        # Audio
        h_a = QHBoxLayout(); h_a.setSpacing(4)
        self._chk_audio = QCheckBox("Optimize Audio")
        self._chk_audio.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; spacing:4px;")
        self._chk_audio.setChecked(self._settings.get("reencode_audio"))
        self._chk_audio.stateChanged.connect(lambda v: self._settings.set("reencode_audio", bool(v)))
        h_a.addWidget(self._chk_audio)
        h_a.addWidget(QLabel("Re-encode PCM/unsupported to Opus", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_a)

        grp_cfg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid_strip.addWidget(grp_cfg, 1, 0)

        # 3. Options (right, same height as Directories + Configuration)
        grp_opts = QGroupBox("Options")
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(6, 2, 6, 2)
        v_opts.setSpacing(0)

        _hint_s  = "font-size:7px; color:#444; margin-left:14px; margin-top:-1px;"
        _check_s = "font-size:8px; font-weight:700; color:#aaa; spacing:2px;"

        def _mk_opt(cb, hint):
            w = QWidget(); vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(0)
            cb.setStyleSheet(_check_s); vl.addWidget(cb)
            vl.addWidget(QLabel(hint, styleSheet=_hint_s))
            return w

        self._chk_struct = QCheckBox("Keep Subdirs")
        self._chk_struct.setChecked(self._settings.get("maintain_structure"))
        self._chk_struct.stateChanged.connect(lambda v: self._settings.set("maintain_structure", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_struct, "Mirror source folder tree in target"))

        self._chk_shutdown = QCheckBox("Shutdown When Done")
        self._chk_shutdown.setChecked(self._settings.get("shutdown_on_finish"))
        self._chk_shutdown.stateChanged.connect(lambda v: self._settings.set("shutdown_on_finish", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_shutdown, "Power off system after queue finishes"))

        self._chk_hw = QCheckBox("HW Accelerated Decode")
        self._chk_hw.setChecked(self._settings.get("hw_accel_decode"))
        self._chk_hw.stateChanged.connect(lambda v: self._settings.set("hw_accel_decode", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_hw, "Use GPU for demux / decode stage"))

        self._chk_debug = QCheckBox("Debug Logging")
        self._chk_debug.setChecked(self._settings.get("debug_mode"))
        self._chk_debug.stateChanged.connect(lambda v: self._settings.set("debug_mode", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_debug, "Write verbose ffmpeg output to log"))

        # Rejects
        w_rej = QWidget(); h_rej = QHBoxLayout(w_rej)
        h_rej.setContentsMargins(0, 0, 0, 0); h_rej.setSpacing(4)
        self._chk_rej = QCheckBox("Skip Short Clips")
        self._chk_rej.setStyleSheet(_check_s)
        self._chk_rej.setChecked(self._settings.get("rejects_enabled"))
        self._chk_rej.stateChanged.connect(lambda v: self._settings.set("rejects_enabled", bool(v)))
        h_rej.addWidget(self._chk_rej, 1)
        self._edit_rej = QLineEdit()
        self._edit_rej.setInputMask("99:99:99")
        self._edit_rej.setFixedWidth(50)
        self._edit_rej.setStyleSheet("font-size:8px; color:#aaa; background:#121212; border:1px solid #1a1a1a; padding:1px;")
        h = self._settings.get("rejects_h"); m = self._settings.get("rejects_m"); s = self._settings.get("rejects_s")
        self._edit_rej.setText(f"{str(h).zfill(2)}:{str(m).zfill(2)}:{str(s).zfill(2)}")
        self._edit_rej.textChanged.connect(self._save_rej_time)
        h_rej.addWidget(self._edit_rej)

        wrap_rej = QWidget(); vr = QVBoxLayout(wrap_rej)
        vr.setContentsMargins(0, 0, 0, 0); vr.setSpacing(0)
        vr.addWidget(w_rej)
        vr.addWidget(QLabel("hh:mm:ss threshold", styleSheet=_hint_s))
        v_opts.addWidget(wrap_rej)

        # Delete (dual verification: label on top, checkboxes right-aligned underneath)
        lbl_del = QLabel("Delete Source on Success")
        lbl_del.setStyleSheet(_check_s)
        v_opts.addWidget(lbl_del)
        w_del_cbs = QWidget(); h_del_cbs = QHBoxLayout(w_del_cbs)
        h_del_cbs.setContentsMargins(0, 0, 0, 0); h_del_cbs.setSpacing(8)
        h_del_cbs.addStretch()
        self._chk_del1 = QCheckBox()
        self._chk_del1.setFixedWidth(18)
        self._chk_del1.setChecked(self._settings.get("delete_on_success"))
        self._chk_del1.stateChanged.connect(lambda v: self._settings.set("delete_on_success", bool(v)))
        h_del_cbs.addWidget(self._chk_del1)
        self._chk_del2 = QCheckBox()
        self._chk_del2.setFixedWidth(18)
        self._chk_del2.setChecked(self._settings.get("delete_on_success_confirm"))
        self._chk_del2.stateChanged.connect(lambda v: self._settings.set("delete_on_success_confirm", bool(v)))
        h_del_cbs.addWidget(self._chk_del2)
        v_opts.addWidget(w_del_cbs)
        v_opts.addWidget(QLabel("Both boxes must be checked to enable", styleSheet="font-size:7px; color:#5a1a1a; margin-left:0; margin-top:-1px;"))
        v_opts.addStretch()

        grp_opts.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        grid_strip.addWidget(grp_opts, 0, 1, 2, 1)  # Row 0-1, Col 1, span 2 rows
        grid_strip.setColumnStretch(0, 1)
        grid_strip.setRowStretch(0, 0)
        grid_strip.setRowStretch(1, 0)

        root.addLayout(grid_strip)

        # ── WORK PROGRESS ─────────────────────────────────────────────────────
        grp_work = QGroupBox("Work Progress")
        v_work = QVBoxLayout(grp_work)
        v_work.setSpacing(1)
        v_work.setContentsMargins(6, 2, 6, 4)

        # Telemetry strip
        h_tel = QHBoxLayout(); h_tel.setSpacing(20)
        self._lbl_io    = QLabel("I/O: 0.0 MB/s")
        self._lbl_saved = QLabel("Space Saved: 0 MB")
        self._lbl_time  = QLabel("Time: --:--:--")
        for lbl in [self._lbl_io, self._lbl_saved, self._lbl_time]:
            lbl.setObjectName("labelValue")
            lbl.setStyleSheet("color:#10b981; font-weight:bold; font-size:10px;")
        self._lbl_io.setFixedWidth(85)
        self._lbl_saved.setFixedWidth(120)
        self._lbl_time.setFixedWidth(85)
        h_tel.addWidget(self._lbl_io)
        h_tel.addStretch()
        h_tel.addWidget(self._lbl_saved)
        h_tel.addStretch()
        h_tel.addWidget(self._lbl_time)
        v_work.addLayout(h_tel)

        # Per-job slots (4 max)
        self._h_jobs = QHBoxLayout(); self._h_jobs.setSpacing(6)
        self._job_bars   = []
        self._job_labels = []
        self._job_speeds = []
        self._job_vid    = []
        self._job_aud    = []
        self._job_widgets = []

        for i in range(4):
            w = QWidget(); v = QVBoxLayout(w)
            v.setContentsMargins(0,0,0,0); v.setSpacing(0)

            lbl_name = QLabel(f"Thread {i+1}")
            lbl_name.setStyleSheet("font-size:9px; font-weight:600; color:#777;")
            lbl_name.setFixedWidth(220)
            v.addWidget(lbl_name)

            bar = QProgressBar(); bar.setFixedHeight(18); bar.setTextVisible(True)
            v.addWidget(bar)

            lbl_vid = QLabel("-"); lbl_vid.setStyleSheet("font-size:8px; color:#666;"); lbl_vid.setFixedWidth(220)
            lbl_aud = QLabel("-"); lbl_aud.setStyleSheet("font-size:8px; color:#666;"); lbl_aud.setFixedWidth(220)
            lbl_spd = QLabel("-"); lbl_spd.setStyleSheet("font-size:9px; font-weight:700; color:#aaa;")
            v.addWidget(lbl_vid); v.addWidget(lbl_aud); v.addWidget(lbl_spd)

            self._job_labels.append(lbl_name)
            self._job_bars.append(bar)
            self._job_speeds.append(lbl_spd)
            self._job_vid.append(lbl_vid)
            self._job_aud.append(lbl_aud)
            self._job_widgets.append(w)
            self._h_jobs.addWidget(w)
            w.hide()

        v_work.addLayout(self._h_jobs)

        # Master bar
        self._bar_master = QProgressBar()
        self._bar_master.setObjectName("masterBar")
        self._bar_master.setFixedHeight(18)
        self._bar_master.setTextVisible(True)
        self._bar_master.setFormat("0/0 Files")
        v_work.addWidget(self._bar_master)

        self._lbl_eta = QLabel("--:--:--")
        self._lbl_eta.setAlignment(Qt.AlignCenter)
        self._lbl_eta.setStyleSheet("color:#10b981; font-size:10px; font-weight:800; margin-top:-2px;")
        v_work.addWidget(self._lbl_eta)

        # Buttons
        h_ctrl = QHBoxLayout(); h_ctrl.setSpacing(8)
        self._btn_start = QPushButton("START ENCODING")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setMinimumHeight(35)
        self._btn_start.clicked.connect(self._toggle_encoding)
        h_ctrl.addWidget(self._btn_start, 2)

        self._btn_pause = QPushButton("PAUSE")
        self._btn_pause.setMinimumHeight(35)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_pause.setEnabled(False)
        h_ctrl.addWidget(self._btn_pause, 1)

        self._btn_logs = QPushButton("LOGS")
        self._btn_logs.setMinimumHeight(35)
        self._btn_logs.clicked.connect(self._open_logs)
        h_ctrl.addWidget(self._btn_logs, 1)

        v_work.addLayout(h_ctrl)
        grp_work.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(grp_work)

        # ── CONSOLE ───────────────────────────────────────────────────────────
        grp_log = QGroupBox("Console")
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(6, 4, 6, 4); v_log.setSpacing(0)
        self._log_list = QListWidget()
        v_log.addWidget(self._log_list)
        root.addWidget(grp_log, 1)  # Stretch: console takes all remaining vertical space

        # Telemetry timer
        self._tel_timer = QTimer(self)
        self._tel_timer.setInterval(2000)
        self._tel_timer.timeout.connect(self._poll_telemetry)
        self._tel_timer.start()

        # Initialise slot visibility and CQ hint
        self._on_jobs_changed(self._combo_jobs.currentIndex())
        self._update_cq_hint()
        self._update_start_enabled()
        # Auto-scan if source path already set (e.g. from settings)
        QTimer.singleShot(300, self._auto_scan)

    # ── settings helpers ──────────────────────────────────────────────────────

    def _on_quality_changed(self, val):
        self._lbl_qval.setText(str(val))
        self._settings.set("quality", val)

    def _on_preset_changed(self, idx):
        p_list = ["p7", "p6", "p5", "p4", "p3", "p2", "p1"]
        if idx < len(p_list):
            self._settings.set("preset", p_list[idx])

    def _update_cq_hint(self):
        hints = ["18-28", "22-32", "25-35", "28-38", "30-40", "32-42", "35-45"]
        idx = self._combo_preset.currentIndex()
        h = hints[min(idx, len(hints) - 1)]
        self._lbl_cq_hint.setText(f"CQ suggested {h}")

    def _on_jobs_changed(self, idx):
        jobs = [1, 2, 4][idx]
        self._settings.set("concurrent_jobs", jobs)
        for i, w in enumerate(self._job_widgets):
            w.setVisible(i < jobs)

    def _save_rej_time(self, t):
        parts = t.split(":")
        if len(parts) == 3:
            try:
                self._settings.set("rejects_h", int(parts[0]))
                self._settings.set("rejects_m", int(parts[1]))
                self._settings.set("rejects_s", int(parts[2]))
            except ValueError:
                pass

    def _browse_src(self):
        f = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if f:
            self._edit_src.setText(f)
            self._settings.set("source_folder", f)
            self._auto_scan()

    def _on_src_changed(self):
        self._scan_debounce.stop()
        self._scan_debounce.start(400)

    def _can_start(self):
        if self._is_encoding:
            return False
        src = self._edit_src.text().strip()
        dst = self._edit_dst.text().strip()
        return bool(src and os.path.isdir(src) and dst and os.path.isdir(dst))

    def _update_start_enabled(self):
        if self._btn_start.text() == "ENCODING COMPLETE":
            return
        self._btn_start.setEnabled(self._can_start())

    def _auto_scan(self):
        if self._is_encoding:
            return
        src = self._edit_src.text().strip()
        self._queue.clear()
        if not src or not os.path.isdir(src):
            return
        def _scan():
            items = list(AV1EncoderEngine().scan_files(src))
            QTimer.singleShot(0, lambda: self._apply_scan_result(items))
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_scan_result(self, items):
        self._queue.clear()
        self._queue.extend(items)
        n = len(items)
        src = self._edit_src.text().strip()
        self._add_log(f"Scanned: {n} file{'s' if n != 1 else ''} ready.")
        debug(UTILITY_MASS_AV1_ENCODER, f"Scan complete: {n} files from {src}")
        if self._log_cb and n > 0:
            self._log_cb(f"AV1 Encoder: {n} files in queue.")
        self._update_start_enabled()

    def _browse_dst(self):
        f = QFileDialog.getExistingDirectory(self, "Select Target Folder")
        if f:
            self._edit_dst.setText(f)
            self._settings.set("target_folder", f)

    # ── encoding lifecycle ────────────────────────────────────────────────────

    def _toggle_encoding(self):
        if self._is_encoding:
            self._stop_encoding()
        else:
            self._start_encoding()

    def _start_encoding(self):
        src = self._edit_src.text().strip()
        dst = self._edit_dst.text().strip()
        if not src or not dst:
            self._add_log("ERROR: Please select source and target directories.")
            return

        if not self._queue:
            self._add_log("Scanning source...")
            self._queue = list(AV1EncoderEngine().scan_files(src))
        if not self._queue:
            self._add_log("No compatible files found.")
            debug(UTILITY_MASS_AV1_ENCODER, f"No compatible files in {src}")
            return

        self._queue_sizes = {p: s for p, s in self._queue}
        self._total_q_bytes   = sum(s for _, s in self._queue)
        self._done_bytes      = 0.0
        self._total_count     = len(self._queue)
        self._done_count     = 0
        self._active_jobs    = 0
        self._active_lock    = threading.Lock()
        self._job_progress   = {}
        self._job_speeds     = {}
        self._current_files  = {}
        self._total_saved    = 0
        self._is_encoding    = True
        self._is_paused       = False
        self._batch_start     = time.time()

        self._bar_master.setValue(0)
        self._bar_master.setFormat(f"0/{self._total_count} Files")
        self._lbl_eta.setText("--:--:--")

        self._btn_start.setText("STOP ENCODING")
        self._btn_start.setObjectName("btnStop")
        self._btn_start.setStyle(self.style())
        self._btn_pause.setEnabled(True)

        self._add_log(f"Starting encode — {self._total_count} files.")
        debug(UTILITY_MASS_AV1_ENCODER, f"Encode start: {self._total_count} files, src={src}, dst={dst}")
        if self._log_cb:
            self._log_cb(f"AV1 Encoder: {self._total_count} files queued.")

        num_workers = self._settings.get("concurrent_jobs")
        self._engine_pool = [AV1EncoderEngine(job_id=i) for i in range(num_workers)]
        for eng in self._engine_pool:
            eng.on_progress = lambda j, p: self._sig.progress.emit(j, p)
            eng.on_details  = lambda j, v, a: self._sig.details.emit(j, v, a)
            threading.Thread(target=self._job_worker, args=(eng, src, dst), daemon=True).start()

    def _stop_encoding(self):
        self._is_encoding = False
        for eng in self._engine_pool:
            eng.cancel()
        self._btn_start.setText("START ENCODING")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setStyle(self.style())
        self._btn_pause.setEnabled(False)
        self._update_start_enabled()
        self._add_log("Encoding stopped.")
        debug(UTILITY_MASS_AV1_ENCODER, "Encoding stopped by user.")

    def _toggle_pause(self):
        paused = any(e._is_paused for e in self._engine_pool)
        for eng in self._engine_pool:
            if paused:
                eng.resume()
            else:
                eng.pause()
        self._btn_pause.setText("PAUSE" if paused else "RESUME")

    def _job_worker(self, engine, src, dst):
        with self._active_lock:
            self._active_jobs += 1
        q_lock = self._queue_lock

        while self._is_encoding:
            input_path = None
            with q_lock:
                if self._queue:
                    input_path, size = self._queue.pop(0)
                    self._current_files[engine.job_id] = input_path

            if not input_path:
                break

            # Skip threshold
            if self._settings.get("rejects_enabled"):
                dur = engine._get_video_duration(input_path)
                thr = (self._settings.get("rejects_h") * 3600 +
                       self._settings.get("rejects_m") * 60 +
                       self._settings.get("rejects_s"))
                if dur <= thr:
                    self._add_log(f"REJECTED: {os.path.basename(input_path)} ({dur:.1f}s)")
                    debug(UTILITY_MASS_AV1_ENCODER, f"Rejected (short): {input_path} ({dur:.1f}s)")
                    self._sig.finished.emit(engine.job_id, True, input_path, "")
                    continue

            # Build output path: stem_av1.mp4 always
            fname = os.path.basename(input_path)
            stem = os.path.splitext(fname)[0]
            out_name = stem + "_av1.mp4"
            if self._settings.get("maintain_structure") and src:
                rel = os.path.relpath(input_path, src)
                rel_stem = os.path.splitext(rel)[0]
                tpath = os.path.join(dst, rel_stem + "_av1.mp4")
                os.makedirs(os.path.dirname(tpath), exist_ok=True)
            else:
                tpath = os.path.join(dst, out_name)

            ok, in_p, out_p = engine.encode_file(
                input_path, tpath,
                self._settings.get("quality"),
                self._settings.get("preset"),
                self._settings.get("reencode_audio"),
                hw_accel=self._settings.get("hw_accel_decode"),
            )
            self._sig.finished.emit(engine.job_id, ok, in_p, out_p)

        with self._active_lock:
            self._active_jobs -= 1
        if self._active_jobs == 0 and not self._queue:
            self._sig.log_msg.emit("Encoding batch complete.")
            debug(UTILITY_MASS_AV1_ENCODER, "Encoding batch complete.")
            if self._settings.get("shutdown_on_finish") and self._is_encoding:
                if platform.system() == "Windows":
                    os.system("shutdown /s /t 0")
                else:
                    os.system("shutdown -h now")

    # ── signal handlers ───────────────────────────────────────────────────────

    def _on_progress(self, job_id, p: EncodingProgress):
        if not self._is_encoding or job_id >= len(self._job_bars):
            return
        fname = p.file_name
        if len(fname) > 28:
            fname = fname[:12] + "..." + fname[-13:]
        self._job_labels[job_id].setText(f"{job_id+1}: {fname}")
        self._job_bars[job_id].setValue(int(p.percent))
        self._job_speeds[job_id].setText(f"{p.fps:.1f} fps / {p.speed:.2f}x")
        self._job_progress[job_id] = p.percent

        # Master
        if self._total_q_bytes > 0:
            active_bytes = 0.0
            for jid, pct in self._job_progress.items():
                if jid in self._current_files:
                    active_bytes += (pct / 100) * self._queue_sizes.get(
                        self._current_files[jid], 0.0)
            done = self._done_bytes + active_bytes
            pct_total = min(100.0, done / self._total_q_bytes * 100)
            self._bar_master.setValue(int(pct_total))
            self._bar_master.setFormat(
                f"{self._done_count}/{self._total_count} Files — {pct_total:.1f}%")

    def _on_details(self, job_id, vid, aud):
        if job_id < len(self._job_vid):
            self._job_vid[job_id].setText(vid)
            self._job_aud[job_id].setText(aud)

    def _on_encode_finished(self, job_id, success, in_p, out_p):
        self._job_progress[job_id] = 0.0
        self._current_files.pop(job_id, None)

        if success and in_p and out_p and os.path.exists(out_p):
            try:
                saved = os.path.getsize(in_p) - os.path.getsize(out_p)
                if saved > 0:
                    self._total_saved += saved
                mb = self._total_saved / (1024 * 1024)
                self._lbl_saved.setText(
                    f"Space Saved: {mb/1024:.2f} GB" if mb > 1024 else f"Space Saved: {mb:.1f} MB")
                self._add_log(f"DONE: {os.path.basename(in_p)} | Saved {saved//(1024*1024)} MB")
                debug(UTILITY_MASS_AV1_ENCODER, f"Done: {os.path.basename(in_p)} -> {os.path.basename(out_p)}, saved {saved//(1024*1024)} MB")
                if self._chk_del1.isChecked() and self._chk_del2.isChecked():
                    try:
                        os.remove(in_p)
                        self._add_log(f"Deleted: {os.path.basename(in_p)}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Deleted source: {in_p}")
                    except Exception as e:
                        self._add_log(f"Delete error: {e}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Delete error: {in_p} — {e}")
            except Exception:
                pass
        elif not success:
            bn = os.path.basename(in_p) if in_p else "?"
            self._add_log(f"FAILED: {bn}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encode FAILED: {in_p or '?'}")

        f_size = self._queue_sizes.get(in_p, 0.0)
        self._done_bytes += f_size
        self._done_count += 1

        if job_id < len(self._job_bars):
            self._job_bars[job_id].setValue(0)
            self._job_speeds[job_id].setText("-")
            self._job_labels[job_id].setText(f"Thread {job_id+1}")
            self._job_vid[job_id].setText("-")
            self._job_aud[job_id].setText("-")

        if self._done_count >= self._total_count and self._is_encoding:
            self._is_encoding = False
            self._btn_start.setText("ENCODING COMPLETE")
            self._btn_start.setEnabled(False)
            self._btn_pause.setEnabled(False)

    # ── telemetry ─────────────────────────────────────────────────────────────

    def _poll_telemetry(self):
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            self._gpu_counter += 1
            if self._gpu_counter >= 3:
                self._gpu_cache   = self._get_gpu()
                self._gpu_counter = 0
            if self._metrics_cb:
                self._metrics_cb(f"{cpu}%", self._gpu_cache, f"{ram}%")

            if self._is_encoding and self._batch_start > 0:
                dt = time.time() - self._batch_start
                h = int(dt // 3600); m = int((dt % 3600) // 60); s = int(dt % 60)
                self._lbl_time.setText(f"Time: {h:02}:{m:02}:{s:02}")
        except Exception:
            pass

    def _get_gpu(self) -> str:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.encoder",
                 "--format=csv,noheader,nounits"],
                text=True, stderr=subprocess.DEVNULL).strip()
            return f"{out}%"
        except Exception:
            return "0%"

    def _open_logs(self):
        import platformdirs
        log_dir = platformdirs.user_log_dir("ChronoArchiver", "UnDadFeated")
        if os.path.exists(log_dir):
            try:
                if platform.system() == "Windows":
                    os.startfile(log_dir)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", log_dir])
                else:
                    subprocess.Popen(["xdg-open", log_dir])
            except Exception:
                pass

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
