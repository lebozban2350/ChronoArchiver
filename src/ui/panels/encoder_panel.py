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
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox,
    QProgressBar, QFileDialog, QComboBox, QSlider,
    QListWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.av1_engine import AV1EncoderEngine, EncodingProgress
from core.av1_settings import AV1Settings

import concurrent.futures


class _Signals(QObject):
    progress  = Signal(int, object)   # job_id, EncodingProgress
    details   = Signal(int, str, str) # job_id, vid, aud
    finished  = Signal(int, bool, str, str)
    log_msg   = Signal(str)
    telemetry = Signal(dict)


class AV1EncoderPanel(QWidget):

    def __init__(self, log_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb  = log_callback
        self._sig     = _Signals()
        self._sig.progress.connect(self._on_progress)
        self._sig.details.connect(self._on_details)
        self._sig.finished.connect(self._on_encode_finished)
        self._sig.log_msg.connect(self._add_log)
        self._sig.telemetry.connect(self._on_telemetry)

        self._settings = AV1Settings()

        self._is_encoding    = False
        self._is_paused      = False
        self._engine_pool    = []
        self._worker_lock    = threading.Lock()
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

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(2)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        h_strip = QHBoxLayout()
        h_strip.setSpacing(6)

        # 1. Directories
        grp_dir = QGroupBox("Directories")
        v_dir = QVBoxLayout(grp_dir)
        v_dir.setContentsMargins(8, 2, 8, 2); v_dir.setSpacing(1)

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
        v_dir.addLayout(h_dst)
        v_dir.addWidget(QLabel("Target — AV1 encoded output destination",
                               styleSheet=_shint))

        grp_dir.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        h_strip.addWidget(grp_dir, 11)

        # 2. Configuration
        grp_cfg = QGroupBox("Configuration")
        v_cfg = QVBoxLayout(grp_cfg)
        v_cfg.setContentsMargins(8, 4, 8, 4); v_cfg.setSpacing(4)

        # Quality
        h_q = QHBoxLayout(); h_q.setSpacing(5)
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
        h_q.addWidget(QLabel("CQ level — lower = better quality", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_q)

        # Preset
        h_p = QHBoxLayout(); h_p.setSpacing(5)
        lbl_p = QLabel("Preset"); lbl_p.setStyleSheet(_slbl); lbl_p.setFixedWidth(42)
        self._combo_preset = QComboBox()
        self._combo_preset.addItems([
            "P7: Deep Archival", "P6: High Quality", "P5: Balanced",
            "P4: Standard", "P3: Fast", "P2: Draft", "P1: Preview"
        ])
        curr_p = self._settings.get("preset").upper()
        for i in range(self._combo_preset.count()):
            if self._combo_preset.itemText(i).startswith(curr_p):
                self._combo_preset.setCurrentIndex(i); break
        self._combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        h_p.addWidget(lbl_p); h_p.addWidget(self._combo_preset, 1)
        h_p.addWidget(QLabel("Encode speed vs. efficiency tradeoff", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_p)

        # Threads
        h_t = QHBoxLayout(); h_t.setSpacing(5)
        lbl_t = QLabel("Threads"); lbl_t.setStyleSheet(_slbl); lbl_t.setFixedWidth(42)
        self._combo_jobs = QComboBox()
        self._combo_jobs.addItems(["1", "2", "4"])
        j = self._settings.get("concurrent_jobs")
        self._combo_jobs.setCurrentIndex(0 if j == 1 else (1 if j == 2 else 2))
        self._combo_jobs.currentIndexChanged.connect(self._on_jobs_changed)
        h_t.addWidget(lbl_t); h_t.addWidget(self._combo_jobs, 1)
        h_t.addWidget(QLabel("Parallel encoding slots (1 / 2 / 4)", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_t)

        # Audio
        h_a = QHBoxLayout(); h_a.setSpacing(5)
        self._chk_audio = QCheckBox("Optimize Audio")
        self._chk_audio.setStyleSheet("font-size:8px; font-weight:700; color:#aaa; spacing:4px;")
        self._chk_audio.setChecked(self._settings.get("reencode_audio"))
        self._chk_audio.stateChanged.connect(lambda v: self._settings.set("reencode_audio", bool(v)))
        h_a.addWidget(self._chk_audio)
        h_a.addWidget(QLabel("Re-encode PCM/unsupported to Opus", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_a)

        grp_cfg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        h_strip.addWidget(grp_cfg, 1)

        # 3. Options
        grp_opts = QGroupBox("Options")
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(8, 2, 8, 2); v_opts.setSpacing(0)

        _hint_s  = "font-size:7px; color:#444; margin-left:16px; margin-top:-1px;"
        _check_s = "font-size:8px; font-weight:700; color:#aaa; spacing:4px;"

        def _mk_opt(cb, hint):
            w = QWidget(); vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 1, 0, 1); vl.setSpacing(0)
            cb.setStyleSheet(_check_s); vl.addWidget(cb)
            hl = QLabel(hint); hl.setStyleSheet(_hint_s); vl.addWidget(hl)
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
        h_rej.setContentsMargins(0, 1, 0, 0); h_rej.setSpacing(4)
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

        # Delete
        w_del = QWidget(); h_del = QHBoxLayout(w_del)
        h_del.setContentsMargins(0, 1, 0, 0); h_del.setSpacing(4)
        self._chk_del1 = QCheckBox()
        self._chk_del1.setFixedWidth(14)
        self._chk_del1.setChecked(self._settings.get("delete_on_success"))
        self._chk_del1.stateChanged.connect(lambda v: self._settings.set("delete_on_success", bool(v)))
        h_del.addWidget(self._chk_del1)
        self._chk_del2 = QCheckBox("Delete Source on Success")
        self._chk_del2.setStyleSheet(_check_s)
        self._chk_del2.setChecked(self._settings.get("delete_on_success_confirm"))
        self._chk_del2.stateChanged.connect(lambda v: self._settings.set("delete_on_success_confirm", bool(v)))
        h_del.addWidget(self._chk_del2, 1)

        wrap_del = QWidget(); vd = QVBoxLayout(wrap_del)
        vd.setContentsMargins(0, 0, 0, 0); vd.setSpacing(0)
        vd.addWidget(w_del)
        vd.addWidget(QLabel("Both boxes must be checked to enable", styleSheet="font-size:7px; color:#5a1a1a; margin-left:16px; margin-top:-1px;"))
        v_opts.addWidget(wrap_del)

        grp_opts.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        h_strip.addWidget(grp_opts, 1)

        # 4. Metrics
        grp_tel = QGroupBox("Metrics")
        v_tel = QVBoxLayout(grp_tel)
        v_tel.setContentsMargins(8, 2, 8, 2); v_tel.setSpacing(0)

        self._lbl_cpu = QLabel("0%"); self._lbl_cpu.setObjectName("labelValue")
        self._lbl_gpu = QLabel("0%"); self._lbl_gpu.setObjectName("labelValue")
        self._lbl_ram = QLabel("-");  self._lbl_ram.setObjectName("labelValue")

        _mhint = "font-size:7px; color:#333; margin-top:-1px;"
        def _add_metric(abbr, hint, widget):
            h = QHBoxLayout(); h.setContentsMargins(0,0,0,0); h.setSpacing(2)
            la = QLabel(abbr); la.setFixedWidth(28)
            la.setStyleSheet("font-size:8px; color:#666; font-weight:700;")
            widget.setFixedWidth(45)
            widget.setStyleSheet("font-size:9px; color:#bbb; font-weight:600;")
            h.addWidget(la); h.addWidget(widget); h.addStretch()
            v_tel.addLayout(h)
            v_tel.addWidget(QLabel(hint, styleSheet=_mhint))

        _add_metric("CPU", "System processor utilization", self._lbl_cpu)
        _add_metric("GPU", "NVIDIA GPU encoder load",     self._lbl_gpu)
        _add_metric("RAM", "Memory in use / total",        self._lbl_ram)

        grp_tel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        h_strip.addWidget(grp_tel, 2)
        root.addLayout(h_strip)

        # ── WORK PROGRESS ─────────────────────────────────────────────────────
        grp_work = QGroupBox("Work Progress")
        v_work = QVBoxLayout(grp_work)
        v_work.setSpacing(1); v_work.setContentsMargins(8, 0, 8, 5)

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

        # Initialise slot visibility
        self._on_jobs_changed(self._combo_jobs.currentIndex())

    # ── settings helpers ──────────────────────────────────────────────────────

    def _on_quality_changed(self, val):
        self._lbl_qval.setText(str(val))
        self._settings.set("quality", val)

    def _on_preset_changed(self, idx):
        p_list = ["p7", "p6", "p5", "p4", "p3", "p2", "p1"]
        if idx < len(p_list):
            self._settings.set("preset", p_list[idx])

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

        self._add_log(f"Scanning {src} ...")
        scan_engine = AV1EncoderEngine()
        self._queue = list(scan_engine.scan_files(src))
        if not self._queue:
            self._add_log("No compatible files found.")
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
        self._batch_start    = 0.0
        self._is_encoding     = True
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
        self._add_log("Encoding stopped.")

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
                    self._sig.finished.emit(engine.job_id, True, input_path, "")
                    continue

            # Build output path
            fname = os.path.basename(input_path)
            if self._settings.get("maintain_structure") and src:
                rel   = os.path.relpath(input_path, src)
                tpath = os.path.join(dst, os.path.splitext(rel)[0] + "_av1.mkv")
                os.makedirs(os.path.dirname(tpath), exist_ok=True)
            else:
                tpath = os.path.join(dst, os.path.splitext(fname)[0] + "_av1.mkv")

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
                if self._chk_del1.isChecked() and self._chk_del2.isChecked():
                    try:
                        os.remove(in_p)
                        self._add_log(f"Deleted: {os.path.basename(in_p)}")
                    except Exception as e:
                        self._add_log(f"Delete error: {e}")
            except Exception:
                pass
        elif not success:
            self._add_log(f"FAILED: {os.path.basename(in_p) if in_p else '?'}")

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
            self._lbl_cpu.setText(f"{cpu}%")
            self._lbl_gpu.setText(self._gpu_cache)
            self._lbl_ram.setText(f"{ram}%")

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
            if platform.system() == "Windows":
                os.startfile(log_dir)
            else:
                subprocess.Popen(["xdg-open", log_dir])

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

    def _on_telemetry(self, data):
        pass  # handled by timer
