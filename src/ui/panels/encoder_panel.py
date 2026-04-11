"""
encoder_panel.py — Mass AV1 Encoder panel for ChronoArchiver.
Visual style exactly matches Mass AV1 Encoder v12.
Uses src/core/av1_engine.py and src/core/av1_settings.py unchanged.
"""

import os
import platform
import posixpath
import queue
import shutil
import subprocess
import tempfile
import threading
import time

import psutil

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QCheckBox,
    QProgressBar,
    QComboBox,
    QSlider,
    QSizePolicy,
    QDialog,
    QPlainTextEdit,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent

import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.av1_engine import AV1EncoderEngine, EncodingProgress, verify_local_media_file_ready
from core.remote_encode import (
    RemoteEncodeError,
    RemoteFileRef,
    common_structure_root_posix,
    join_dst_local,
    password_for_remote_encode,
    posix_join_under,
    remote_file_exists,
    remote_mkdir_p,
    remote_scan_videos,
    remote_target_and_root,
    remote_unlink,
    remote_verify_python3,
    run_scp_from_remote,
    run_scp_to_remote,
)
from core.remote_ssh import is_remote_path
from core.fs_task_lock import release_fs_heavy, try_acquire_fs_heavy
from ui.panel_start_hint import apply_start_button_hint
from ui.console_style import PANEL_CONSOLE_TEXTEDIT_STYLE
from ui.panel_widgets import COMBO_BOX_PANEL_QSS, path_browse_btn_qss
from ui.local_remote_path_dialog import run_local_remote_path_dialog
from core.av1_settings import AV1Settings
from core.venv_manager import footer_nvidia_gpu_utilization_text
from core.debug_logger import (
    INSTALLER_APP_MASS_AV1_ENCODER,
    debug,
    log_exception,
    log_installer_popup,
    structured_event,
    UTILITY_MASS_AV1_ENCODER,
)
from version import APP_NAME

# mkstemp prefix so STOP / quit can sweep orphans; must match _sweep_chrono_encoder_tempdir.
_ENCODER_TMP_PREFIX = "chronoarchiver_av1_"
# Plain console lines only (no rich HTML): long runs used to crash Qt in QTextEdit::paintEvent.
_ENCODER_LOG_LINE_MAX = 4000


def _remote_pipeline_queue_cap(num_workers: int) -> int:
    """Max prepared remote downloads queued ahead of encode (backpressure for disk + network)."""
    return min(16, max(4, num_workers * 2 + 2))


def _finalize_encoder_temp_files(
    tmp_cleanup: list[str],
    *,
    success: bool,
    local_in: str,
    local_out: str,
) -> int | None:
    """
    Remove local scratch files (SCP download, remote-destination encode buffer) in the worker
    thread immediately after I/O, so temps are not left behind if the UI slot runs later or STOP
    is pressed. Returns bytes saved (in minus out) when both files exist and success is True.
    """
    saved: int | None = None
    if (
        success
        and local_in
        and local_out
        and os.path.isfile(local_in)
        and os.path.isfile(local_out)
    ):
        try:
            saved = max(0, os.path.getsize(local_in) - os.path.getsize(local_out))
        except OSError:
            saved = None
    for tmp in list(tmp_cleanup):
        try:
            if tmp and os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
    tmp_cleanup.clear()
    return saved


class _Signals(QObject):
    progress = Signal(int, object)  # job_id, EncodingProgress
    details = Signal(int, str, str)  # job_id, vid, aud
    finished = Signal(int, bool, str, str, object)
    log_msg = Signal(str)
    batch_complete = Signal()  # emitted when all workers finish, queue empty — auto-stop UI
    # total_bytes can exceed 2^31-1 (Qt C++ int); use object so Shiboken does not overflow.
    scan_progress = Signal(int, object)  # count, total_bytes (thread-safe for scan updates)
    scan_done = Signal(list, str)  # items, src — emitted from worker, handled in main thread
    scan_done_then_start = Signal(list, str, str)  # items, src, dst — for Start+empty queue


class ScanProgressDialog(QDialog):
    """Separate window showing file count and total size during source scan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scanning Source")
        self.setModal(False)
        self.setFixedSize(320, 120)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl_files = QLabel("Files: 0")
        self._lbl_files.setStyleSheet("font-size:12px; font-weight:600; color:#10b981;")
        v.addWidget(self._lbl_files)
        self._lbl_size = QLabel("Total size: 0 B")
        self._lbl_size.setStyleSheet("font-size:11px; color:#aaa;")
        v.addWidget(self._lbl_size)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(12)
        v.addWidget(self._bar)
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self._last_scan_log_ts = 0.0
        self._last_scan_count = 0

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        log_installer_popup(INSTALLER_APP_MASS_AV1_ENCODER, "ScanProgressDialog", "opened")

    def closeEvent(self, event: QCloseEvent) -> None:
        log_installer_popup(INSTALLER_APP_MASS_AV1_ENCODER, "ScanProgressDialog", "closed")
        super().closeEvent(event)

    def update_progress(self, count: int, total_bytes: object):
        self._lbl_files.setText(f"Files: {count}")
        try:
            tb = int(total_bytes)
        except (TypeError, ValueError):
            tb = 0
        total_bytes = max(0, tb)
        if total_bytes >= 1024**3:
            sz = f"{total_bytes / (1024**3):.2f} GB"
        elif total_bytes >= 1024**2:
            sz = f"{total_bytes / (1024**2):.1f} MB"
        elif total_bytes >= 1024:
            sz = f"{total_bytes / 1024:.1f} KB"
        else:
            sz = f"{total_bytes} B"
        self._lbl_size.setText(f"Total size: {sz}")
        now = time.monotonic()
        if count >= self._last_scan_count + 200 or (now - self._last_scan_log_ts) >= 3.0:
            self._last_scan_log_ts = now
            self._last_scan_count = count
            log_installer_popup(
                INSTALLER_APP_MASS_AV1_ENCODER,
                "ScanProgressDialog",
                "progress",
                f"files={count} total_bytes={total_bytes}",
            )


class AV1EncoderPanel(QWidget):
    def __init__(self, log_callback=None, metrics_callback=None, status_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb = log_callback
        self._metrics_cb = metrics_callback
        self._status_cb = status_callback
        self._sig = _Signals()
        # Workers emit from encoder threads; queue slots on the GUI thread so codec/progress labels update reliably.
        self._sig.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self._sig.details.connect(self._on_details, Qt.ConnectionType.QueuedConnection)
        self._sig.finished.connect(self._on_encode_finished)
        self._sig.log_msg.connect(self._add_log)
        self._sig.batch_complete.connect(self._on_batch_complete)
        self._sig.scan_done.connect(self._on_scan_done)
        self._sig.scan_done_then_start.connect(self._on_scan_done_then_start)

        self._settings = AV1Settings()

        self._is_encoding = False
        self._is_paused = False
        self._engine_pool = []
        self._queue = []
        self._queue_lock = threading.Lock()
        self._queue_sizes = {}
        self._total_q_bytes = 0.0
        self._done_bytes = 0.0
        self._total_count = 0
        self._done_count = 0
        self._active_jobs = 0
        self._active_lock = threading.Lock()
        self._job_progress = {}
        self._current_files = {}
        self._total_saved = 0
        self._batch_start = 0.0
        self._gpu_cache = "N/A"
        self._gpu_counter = 0
        self._source_scanned = False
        self._fs_heavy_held = False
        self._encode_pw: str | None = None
        self._remote_dst_remote = None
        self._remote_dst_root_posix: str | None = None
        self._remote_src_structure_root_posix: str | None = None
        self._encode_pipeline_q: queue.Queue | None = None
        self._pipeline_prefetch_thread: threading.Thread | None = None
        self._pipeline_prefetch_stop = threading.Event()

        _shint = "font-size: 7px; color: #444; margin-top: -1px;"
        _slbl = "font-size: 9px; font-weight: 700; color: #aaa;"
        _combo_style = COMBO_BOX_PANEL_QSS

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(1)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        # Layout: [Directories (top) | Options (right, full height)]
        #         [Configuration (bottom) |
        grid_strip = QGridLayout()
        grid_strip.setSpacing(6)

        # 1. Directories (top-left) — grid aligns both Browse buttons in one column with line edits
        _bar_h = 28
        _browse_w, _browse_h = 60, _bar_h
        self._path_bar_h = _bar_h
        self._browse_btn_w = _browse_w
        _dir_edit_ss = (
            f"color:#fff; font-size:11px; font-weight:500; min-height:{_bar_h}px; max-height:{_bar_h}px; "
            "padding:2px 6px; background:#121212; border:1px solid #1a1a1a;"
        )
        _dir_btn_ss = path_browse_btn_qss(_bar_h, _browse_w, "#262626", "#aaa")

        grp_dir = QGroupBox("Directories")
        v_dir = QVBoxLayout(grp_dir)
        v_dir.setContentsMargins(6, 4, 6, 2)
        v_dir.setSpacing(4)

        self._edit_src = QLineEdit()
        self._edit_src.setPlaceholderText("SOURCE PATH (local or smb://)")
        self._edit_src.setStyleSheet(_dir_edit_ss)
        self._edit_src.setFixedHeight(_bar_h)
        self._edit_src.setText("")

        self._edit_dst = QLineEdit()
        self._edit_dst.setPlaceholderText("TARGET PATH (local or smb://)")
        self._edit_dst.setStyleSheet(_dir_edit_ss)
        self._edit_dst.setFixedHeight(_bar_h)
        self._edit_dst.setText("")

        grid_paths = QGridLayout()
        grid_paths.setContentsMargins(0, 0, 0, 0)
        grid_paths.setHorizontalSpacing(6)
        grid_paths.setVerticalSpacing(4)
        grid_paths.setColumnStretch(0, 1)
        grid_paths.setColumnStretch(1, 0)
        grid_paths.setColumnMinimumWidth(1, _browse_w)
        _browse_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        self._btn_browse_src = QPushButton("Browse")
        self._btn_browse_src.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_src.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_browse_src.setStyleSheet(_dir_btn_ss)
        self._btn_browse_src.clicked.connect(self._browse_src)

        self._btn_browse_dst = QPushButton("Browse")
        self._btn_browse_dst.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_dst.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_browse_dst.setStyleSheet(_dir_btn_ss)
        self._btn_browse_dst.clicked.connect(self._browse_dst)

        grid_paths.addWidget(self._edit_src, 0, 0)
        grid_paths.addWidget(self._btn_browse_src, 0, 1, alignment=_browse_align)
        grid_paths.addWidget(
            QLabel("Source — local path or smb:// network share", styleSheet=_shint),
            1,
            0,
            1,
            2,
        )
        grid_paths.addWidget(self._edit_dst, 2, 0)
        grid_paths.addWidget(self._btn_browse_dst, 2, 1, alignment=_browse_align)
        grid_paths.addWidget(
            QLabel("Target — AV1 encoded output destination", styleSheet=_shint),
            3,
            0,
            1,
            2,
        )
        v_dir.addLayout(grid_paths)

        self._row_ssh = QWidget()
        h_ssh = QHBoxLayout(self._row_ssh)
        h_ssh.setContentsMargins(0, 4, 0, 0)
        h_ssh.setSpacing(8)
        h_ssh.addWidget(
            QLabel("Remote SSH password (session; empty = keys/agent):", styleSheet=_shint),
            0,
        )
        self._edit_ssh_pw = QLineEdit()
        self._edit_ssh_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_ssh_pw.setPlaceholderText("optional — sshpass for password; filled from Browse for remote paths")
        self._edit_ssh_pw.setStyleSheet(_dir_edit_ss)
        self._edit_ssh_pw.setFixedHeight(_bar_h)
        h_ssh.addWidget(self._edit_ssh_pw, 1)
        v_dir.addWidget(self._row_ssh)
        self._row_ssh.hide()

        self._scan_debounce = QTimer(self)
        self._scan_debounce.setSingleShot(True)
        self._scan_debounce.timeout.connect(self._auto_scan)
        self._edit_src.textChanged.connect(self._on_src_changed)
        self._edit_src.textChanged.connect(self._update_start_enabled)
        self._edit_src.textChanged.connect(self._update_ssh_row_visibility)
        self._edit_dst.textChanged.connect(self._update_start_enabled)
        self._edit_dst.textChanged.connect(self._update_ssh_row_visibility)
        self._edit_ssh_pw.textChanged.connect(self._update_start_enabled)

        grp_dir.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid_strip.addWidget(grp_dir, 0, 0)

        # 2. Configuration (bottom-left)
        grp_cfg = QGroupBox("Configuration")
        v_cfg = QVBoxLayout(grp_cfg)
        v_cfg.setContentsMargins(6, 0, 6, 0)
        v_cfg.setSpacing(0)

        # Quality
        h_q = QHBoxLayout()
        h_q.setSpacing(4)
        lbl_q = QLabel("Quality")
        lbl_q.setStyleSheet(_slbl)
        lbl_q.setFixedWidth(42)
        self._lbl_qval = QLabel(str(self._settings.get("quality")))
        self._lbl_qval.setFixedWidth(20)
        self._lbl_qval.setStyleSheet("font-size:10px; color:#10b981; font-weight:bold;")
        self._slider_q = QSlider(Qt.Horizontal)
        self._slider_q.setRange(0, 63)
        self._slider_q.setValue(self._settings.get("quality"))
        self._slider_q.valueChanged.connect(self._on_quality_changed)
        h_q.addWidget(lbl_q)
        h_q.addWidget(self._lbl_qval)
        h_q.addWidget(self._slider_q, 1)
        self._lbl_cq_hint = QLabel("CQ — lower = better quality", styleSheet="font-size:7px; color:#444;")
        h_q.addWidget(self._lbl_cq_hint)
        v_cfg.addLayout(h_q)

        # Preset
        h_p = QHBoxLayout()
        h_p.setSpacing(4)
        lbl_p = QLabel("Preset")
        lbl_p.setStyleSheet(_slbl)
        lbl_p.setFixedWidth(42)
        self._combo_preset = QComboBox()
        self._combo_preset.setStyleSheet(_combo_style)
        self._combo_preset.setFixedHeight(16)
        self._combo_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._combo_preset.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._combo_preset.addItems(
            [
                "P7: Deep Archival",
                "P6: High Quality",
                "P5: Balanced",
                "P4: Standard",
                "P3: Fast",
                "P2: Draft",
                "P1: Preview",
            ]
        )
        curr_p = self._settings.get("preset").upper()
        for i in range(self._combo_preset.count()):
            if self._combo_preset.itemText(i).startswith(curr_p):
                self._combo_preset.setCurrentIndex(i)
                break
        self._combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        self._combo_preset.currentIndexChanged.connect(self._update_cq_hint)
        h_p.addWidget(lbl_p)
        h_p.addWidget(self._combo_preset, 0)
        self._lbl_preset_hint = QLabel("Encode speed vs. efficiency tradeoff", styleSheet="font-size:7px; color:#444;")
        h_p.addWidget(self._lbl_preset_hint, 1)
        v_cfg.addLayout(h_p)

        # Threads
        h_t = QHBoxLayout()
        h_t.setSpacing(4)
        lbl_t = QLabel("Threads")
        lbl_t.setStyleSheet(_slbl)
        lbl_t.setFixedWidth(42)
        self._combo_jobs = QComboBox()
        self._combo_jobs.setStyleSheet(_combo_style)
        self._combo_jobs.setFixedHeight(16)
        self._combo_jobs.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._combo_jobs.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._combo_jobs.addItems(["1", "2", "4"])
        j = self._settings.get("concurrent_jobs")
        self._combo_jobs.setCurrentIndex(0 if j == 1 else (1 if j == 2 else 2))
        self._combo_jobs.currentIndexChanged.connect(self._on_jobs_changed)
        h_t.addWidget(lbl_t)
        h_t.addWidget(self._combo_jobs, 0)
        self._lbl_threads_hint = QLabel("Parallel encoding slots (1 / 2 / 4)", styleSheet="font-size:7px; color:#444;")
        h_t.addWidget(self._lbl_threads_hint, 1)
        v_cfg.addLayout(h_t)

        # Audio
        h_a = QHBoxLayout()
        h_a.setSpacing(4)
        self._chk_audio = QCheckBox("Optimize Audio")
        self._chk_audio.setStyleSheet("font-size:9px; font-weight:700; color:#aaa; spacing:4px;")
        self._chk_audio.setChecked(self._settings.get("reencode_audio"))
        self._chk_audio.stateChanged.connect(lambda v: self._settings.set("reencode_audio", bool(v)))
        h_a.addWidget(self._chk_audio)
        h_a.addWidget(QLabel("Re-encode PCM/unsupported to Opus", styleSheet="font-size:7px; color:#444;"))
        v_cfg.addLayout(h_a)

        v_cfg.addStretch()
        grp_cfg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        grid_strip.addWidget(grp_cfg, 1, 0)

        # 3. Options (right, same height as Directories + Configuration)
        grp_opts = QGroupBox("Options")
        v_opts = QVBoxLayout(grp_opts)
        v_opts.setContentsMargins(6, 1, 6, 1)
        v_opts.setSpacing(0)

        _hint_s = "font-size:8px; color:#444; margin-left:14px; margin-top:-2px;"
        _check_s = "font-size:9px; font-weight:700; color:#aaa; spacing:2px;"

        def _mk_opt(cb, hint):
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            cb.setStyleSheet(_check_s)
            vl.addWidget(cb)
            vl.addWidget(QLabel(hint, styleSheet=_hint_s))
            return w

        self._chk_struct = QCheckBox("Keep Subdirs")
        self._chk_struct.setChecked(self._settings.get("maintain_structure"))
        self._chk_struct.stateChanged.connect(lambda v: self._settings.set("maintain_structure", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_struct, "Mirror source folder tree in target"))

        # Existing output policy
        w_exist = QWidget()
        v_exist = QVBoxLayout(w_exist)
        v_exist.setContentsMargins(0, 0, 0, 0)
        v_exist.setSpacing(0)
        lbl_exist = QLabel("If output exists:", styleSheet=_check_s)
        v_exist.addWidget(lbl_exist)
        self._combo_exist = QComboBox()
        self._combo_exist.addItems(["Overwrite", "Skip", "Rename"])
        self._combo_exist.setCurrentText(
            {"overwrite": "Overwrite", "skip": "Skip", "rename": "Rename"}.get(
                self._settings.get("existing_output"), "Overwrite"
            )
        )
        self._combo_exist.setStyleSheet(
            COMBO_BOX_PANEL_QSS + "QComboBox { color: #aaa; }"
        )
        self._combo_exist.setFixedHeight(16)
        self._combo_exist.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._combo_exist.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._combo_exist.currentTextChanged.connect(lambda t: self._settings.set("existing_output", t.lower()))
        v_exist.addWidget(self._combo_exist, alignment=Qt.AlignmentFlag.AlignLeft)
        v_opts.addWidget(w_exist)

        self._chk_shutdown = QCheckBox("Shutdown When Done")
        self._chk_shutdown.setChecked(self._settings.get("shutdown_on_finish"))
        self._chk_shutdown.stateChanged.connect(lambda v: self._settings.set("shutdown_on_finish", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_shutdown, "Power off system after queue finishes"))

        self._chk_hw = QCheckBox("HW Accelerated Decode")
        self._chk_hw.setChecked(self._settings.get("hw_accel_decode"))
        self._chk_hw.stateChanged.connect(lambda v: self._settings.set("hw_accel_decode", bool(v)))
        v_opts.addWidget(_mk_opt(self._chk_hw, "Use GPU for demux / decode stage"))
        _probe_enc = AV1EncoderEngine()
        if not _probe_enc.has_hardware_av1_encoder:
            self._chk_hw.setChecked(False)
            self._settings.set("hw_accel_decode", False)
            self._chk_hw.setEnabled(False)
            self._chk_hw.setToolTip(
                "No AV1 hardware encoder in this FFmpeg build (av1_nvenc / av1_vaapi / av1_amf). "
                "Using software libsvtav1."
            )

        # Rejects
        w_rej = QWidget()
        h_rej = QHBoxLayout(w_rej)
        h_rej.setContentsMargins(0, 0, 0, 0)
        h_rej.setSpacing(2)
        self._chk_rej = QCheckBox("Skip Short Clips")
        self._chk_rej.setStyleSheet(_check_s)
        self._chk_rej.setChecked(self._settings.get("rejects_enabled"))
        self._chk_rej.stateChanged.connect(lambda v: self._settings.set("rejects_enabled", bool(v)))
        h_rej.addWidget(self._chk_rej, 0)
        h_rej.addSpacing(5)  # Nudge time entry slightly right
        self._edit_rej = QLineEdit()
        self._edit_rej.setInputMask("99:99:99")
        self._edit_rej.setFixedWidth(50)
        self._edit_rej.setStyleSheet(
            "font-size:9px; color:#aaa; background:#121212; border:1px solid #1a1a1a; padding:1px;"
        )
        h = self._settings.get("rejects_h")
        m = self._settings.get("rejects_m")
        s = self._settings.get("rejects_s")
        self._edit_rej.setText(f"{str(h).zfill(2)}:{str(m).zfill(2)}:{str(s).zfill(2)}")
        self._edit_rej.textChanged.connect(self._save_rej_time)
        h_rej.addWidget(self._edit_rej)

        lbl_rej_hint = QLabel("hh:mm:ss threshold", styleSheet=_hint_s)
        h_rej.addWidget(lbl_rej_hint, 1)
        v_opts.addWidget(w_rej)

        # Delete (dual verification — full-width labeled checkboxes; avoids edge overlap)
        lbl_del = QLabel("Delete source on success")
        lbl_del.setStyleSheet(_check_s)
        v_opts.addWidget(lbl_del)
        self._chk_del1 = QCheckBox("Confirm: delete source files after a successful encode")
        self._chk_del1.setStyleSheet(_check_s)
        self._chk_del1.setChecked(self._settings.get("delete_on_success"))
        self._chk_del1.stateChanged.connect(lambda v: self._settings.set("delete_on_success", bool(v)))
        v_opts.addWidget(self._chk_del1)
        self._chk_del2 = QCheckBox("Confirm: I understand this cannot be undone")
        self._chk_del2.setStyleSheet(_check_s)
        self._chk_del2.setChecked(self._settings.get("delete_on_success_confirm"))
        self._chk_del2.stateChanged.connect(lambda v: self._settings.set("delete_on_success_confirm", bool(v)))
        v_opts.addWidget(self._chk_del2)
        _lbl_del_hint = QLabel("Both checkboxes must be checked to enable deletion.")
        _lbl_del_hint.setWordWrap(True)
        _lbl_del_hint.setStyleSheet("font-size:8px; color:#5a1a1a; margin-left:0; margin-top:2px;")
        v_opts.addWidget(_lbl_del_hint)
        v_opts.addStretch()

        grp_opts.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        grid_strip.addWidget(grp_opts, 0, 1, 2, 1)  # Row 0-1, Col 1, span 2 rows
        grid_strip.setColumnStretch(0, 1)
        grid_strip.setRowStretch(0, 0)
        grid_strip.setRowStretch(1, 1)

        root.addLayout(grid_strip)

        # ── WORK PROGRESS ─────────────────────────────────────────────────────
        grp_work = QGroupBox("Work Progress")
        v_work = QVBoxLayout(grp_work)
        v_work.setSpacing(1)
        v_work.setContentsMargins(6, 2, 6, 4)

        # Telemetry strip
        h_tel = QHBoxLayout()
        h_tel.setSpacing(20)
        self._lbl_io = QLabel("I/O: 0.0 MB/s")
        self._lbl_saved = QLabel("Space Saved: 0 MB")
        self._lbl_time = QLabel("Time: --:--:--")
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
        self._h_jobs = QHBoxLayout()
        self._h_jobs.setSpacing(6)
        self._job_bars = []
        self._job_labels = []
        self._job_speeds = []
        self._job_vid = []
        self._job_aud = []
        self._job_widgets = []

        for i in range(4):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)

            lbl_name = QLabel(f"Thread {i + 1}")
            lbl_name.setStyleSheet("font-size:9px; font-weight:600; color:#777;")
            lbl_name.setFixedWidth(220)
            v.addWidget(lbl_name)

            bar = QProgressBar()
            bar.setFixedHeight(18)
            bar.setTextVisible(True)
            v.addWidget(bar)

            lbl_vid = QLabel("-")
            lbl_vid.setStyleSheet("font-size:8px; color:#666;")
            lbl_vid.setFixedWidth(220)
            lbl_aud = QLabel("-")
            lbl_aud.setStyleSheet("font-size:8px; color:#666;")
            lbl_aud.setFixedWidth(220)
            lbl_spd = QLabel("-")
            lbl_spd.setStyleSheet("font-size:9px; font-weight:700; color:#aaa;")
            v.addWidget(lbl_vid)
            v.addWidget(lbl_aud)
            v.addWidget(lbl_spd)

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

        self._lbl_eta = QLabel("ESTIMATED TIME REMAINING: --:--:--")
        self._lbl_eta.setAlignment(Qt.AlignCenter)
        self._lbl_eta.setStyleSheet("color:#10b981; font-size:10px; font-weight:800; margin-top:-2px;")
        v_work.addWidget(self._lbl_eta)

        # Buttons
        h_ctrl = QHBoxLayout()
        h_ctrl.setSpacing(8)
        self._btn_start = QPushButton("START ENCODING")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setMinimumHeight(35)
        self._btn_start.clicked.connect(self._toggle_encoding)
        h_ctrl.addWidget(self._btn_start, 3)

        self._btn_pause = QPushButton("PAUSE")
        self._btn_pause.setMinimumHeight(35)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_pause.setEnabled(False)
        h_ctrl.addWidget(self._btn_pause, 1)

        v_work.addLayout(h_ctrl)
        grp_work.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(grp_work)

        # ── CONSOLE ───────────────────────────────────────────────────────────
        grp_log = QGroupBox("Console")
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(6, 2, 6, 4)
        v_log.setSpacing(0)
        self._log_edit = QPlainTextEdit()
        self._log_edit.setObjectName("panelConsole")
        self._log_edit.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        self._log_edit.setReadOnly(True)
        self._log_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_edit.setMaximumBlockCount(800)
        v_log.addWidget(self._log_edit)
        root.addWidget(grp_log, 1)  # Stretch: console takes all remaining vertical space

        # Telemetry timer
        self._tel_timer = QTimer(self)
        self._tel_timer.setInterval(2000)
        self._tel_timer.timeout.connect(self._poll_telemetry)
        self._tel_timer.start()

        # Initialise slot visibility and CQ hint
        self._on_jobs_changed(self._combo_jobs.currentIndex())
        self._update_cq_hint()
        self._guide_pulse_timer = QTimer(self)
        self._guide_pulse_timer.setInterval(550)
        self._guide_pulse_timer.timeout.connect(self._pulse_guide)
        self._guide_glow_phase = 0
        self._guide_target = None
        self._update_ssh_row_visibility()
        self._update_start_enabled()

    # ── settings helpers ──────────────────────────────────────────────────────

    def _update_ssh_row_visibility(self) -> None:
        src = self._edit_src.text().strip()
        dst = self._edit_dst.text().strip()
        self._row_ssh.setVisible(bool(is_remote_path(src) or is_remote_path(dst)))

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
        idx = max(0, min(int(idx), 2))
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
        picked, dialog_pw = run_local_remote_path_dialog(
            self, self._edit_src.text().strip(), purpose="source"
        )
        if picked:
            self._edit_src.blockSignals(True)
            self._edit_src.setText(picked)
            self._edit_src.blockSignals(False)
            if is_remote_path(picked):
                self._edit_ssh_pw.setText(dialog_pw)
            self._auto_scan()

    def _on_src_changed(self):
        self._source_scanned = False
        self._scan_debounce.stop()
        self._scan_debounce.start(400)

    def _can_start(self):
        if self._is_encoding:
            return True
        src = self._edit_src.text().strip()
        dst = self._edit_dst.text().strip()
        if not src or not dst:
            return False
        r_src = is_remote_path(src)
        r_dst = is_remote_path(dst)
        if r_src or r_dst:
            if not shutil.which("ssh") or not shutil.which("scp"):
                return False
            try:
                password_for_remote_encode(self._edit_ssh_pw.text())
            except RemoteEncodeError:
                return False
        if r_src:
            if not self._source_scanned or len(self._queue) == 0:
                return False
        elif not os.path.isdir(src):
            return False
        if r_dst:
            return True
        return bool(os.path.isdir(dst))

    def _get_guide_target(self):
        if self._is_encoding or self._btn_start.text() == "ENCODING COMPLETE":
            return None
        src = self._edit_src.text().strip()
        if not src:
            return self._btn_browse_src
        if is_remote_path(src):
            dst = self._edit_dst.text().strip()
            if not self._source_scanned or len(self._queue) == 0:
                return self._btn_browse_src
            if not dst:
                return self._btn_browse_dst
            if not is_remote_path(dst) and not os.path.isdir(dst):
                return self._btn_browse_dst
            return self._btn_start
        if not os.path.isdir(src):
            return self._btn_browse_src
        if not self._source_scanned:
            return self._btn_browse_src
        dst = self._edit_dst.text().strip()
        if not dst:
            return self._btn_browse_dst
        if is_remote_path(dst):
            return self._btn_start
        if not os.path.isdir(dst):
            return self._btn_browse_dst
        return self._btn_start

    def _clear_guide_glow(self, w):
        if not w:
            return
        if w == self._btn_start:
            w.setStyleSheet(
                "background-color:#10b981; color:#064e3b; border:2px solid #064e3b; font-size:10px; font-weight:900;"
            )
        else:
            w.setStyleSheet(path_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#262626", "#aaa"))

    def _encoder_start_reasons(self) -> list[str]:
        if self._is_encoding:
            return []
        src = self._edit_src.text().strip()
        dst = self._edit_dst.text().strip()
        r = []
        r_src = is_remote_path(src)
        r_dst = is_remote_path(dst)
        if not src:
            r.append("choose a source folder")
        elif r_src:
            if not shutil.which("ssh") or not shutil.which("scp"):
                r.append("install OpenSSH client (ssh and scp) for remote encoding")
            else:
                try:
                    password_for_remote_encode(self._edit_ssh_pw.text())
                except RemoteEncodeError as e:
                    r.append(str(e))
                if not self._source_scanned:
                    r.append("wait for remote source scan to finish")
                elif len(self._queue) == 0:
                    r.append("no video files found under the remote source path")
        elif not os.path.isdir(src):
            r.append("choose a valid source folder")
        elif not self._source_scanned:
            r.append("wait for the source folder scan to finish")
        if not dst:
            r.append("choose a valid output folder")
        elif not r_dst and not os.path.isdir(dst):
            r.append("choose a valid output folder")
        return r

    def _update_start_enabled(self):
        if self._btn_start.text() == "ENCODING COMPLETE":
            return
        if self._is_encoding:
            self._btn_start.setEnabled(True)
            apply_start_button_hint(
                self._btn_start,
                enabled=True,
                reasons_when_disabled=[],
                enabled_tip="Stop encoding and cancel remaining jobs",
            )
            self._guide_pulse_timer.stop()
            self._clear_guide_glow(self._guide_target)
            self._guide_target = None
            self._guide_glow_phase = 0
            return
        can = self._can_start()
        self._btn_start.setEnabled(can)
        apply_start_button_hint(
            self._btn_start,
            enabled=can,
            reasons_when_disabled=self._encoder_start_reasons(),
            enabled_tip="Start AV1 encoding for the queued files",
        )
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _pulse_guide(self):
        if self._is_encoding:
            return
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
                target.setStyleSheet(
                    "background-color:#10b981; color:#064e3b; border:2px solid #ef4444; font-size:10px; font-weight:900;"
                )
            else:
                target.setStyleSheet(path_browse_btn_qss(self._path_bar_h, self._browse_btn_w, "#ef4444", "#ef4444"))
        else:
            self._clear_guide_glow(target)

    def _run_remote_scan_collect(self, src: str) -> list:
        _lg = logging.getLogger(APP_NAME)
        try:
            pw = password_for_remote_encode(self._edit_ssh_pw.text())
        except RemoteEncodeError as e:
            self._sig.log_msg.emit(str(e))
            debug(UTILITY_MASS_AV1_ENCODER, f"Remote video scan error (credentials): {e}")
            _lg.warning("Remote video scan (credentials): %s", e)
            return []
        try:
            rt, root = remote_target_and_root(src)
            remote_verify_python3(rt, pw)
            exts = (".mpg", ".mp4", ".ts", ".avi", ".3gp", ".mkv", ".mov", ".webm")
            refs, scan_hint = remote_scan_videos(rt, root, exts, pw)
            if scan_hint:
                self._sig.log_msg.emit(scan_hint)
            return [(r, r.size) for r in refs]
        except RemoteEncodeError as e:
            self._sig.log_msg.emit(f"Remote scan error: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Remote video scan error: {e}")
            _lg.warning("Remote video scan: %s", e)
            return []
        except Exception as e:
            self._sig.log_msg.emit(f"Remote scan error: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Remote video scan unexpected error: {e}")
            _lg.warning("Remote video scan (unexpected): %s", e)
            log_exception(e, context="remote video scan", utility=UTILITY_MASS_AV1_ENCODER)
            return []

    def _auto_scan(self):
        if self._is_encoding:
            return
        src = self._edit_src.text().strip()
        self._queue.clear()
        if not src:
            self._source_scanned = False
            self._update_start_enabled()
            return
        if is_remote_path(src):
            self._source_scanned = False
            self._add_log("Scanning remote source (SSH)...")
            self._update_start_enabled()
            debug(UTILITY_MASS_AV1_ENCODER, f"Auto-scan remote: {src[:200]}")

            scan_dialog = ScanProgressDialog(self)
            self._scan_dialog = scan_dialog
            self._sig.scan_progress.connect(scan_dialog.update_progress)
            scan_dialog.show()

            def _scan_remote():
                items = self._run_remote_scan_collect(src)
                total_b = sum(s for _, s in items)
                self._sig.scan_progress.emit(len(items), total_b)
                debug(
                    UTILITY_MASS_AV1_ENCODER,
                    f"Auto-scan remote complete: count={len(items)}, total_bytes={total_b}",
                )
                self._sig.scan_done.emit(items, src)

            threading.Thread(target=_scan_remote, daemon=True).start()
            return
        if not os.path.isdir(src):
            self._source_scanned = False
            self._update_start_enabled()
            return
        self._source_scanned = False
        self._add_log("Scanning source folder...")
        self._update_start_enabled()
        debug(UTILITY_MASS_AV1_ENCODER, f"Auto-scan start: src={src}")

        scan_dialog = ScanProgressDialog(self)
        self._scan_dialog = scan_dialog
        self._sig.scan_progress.connect(scan_dialog.update_progress)
        scan_dialog.show()

        def _scan():
            count = 0
            total_bytes = 0
            items = []
            last_emit = [0]
            try:
                for path, size in AV1EncoderEngine().scan_files(src):
                    items.append((path, max(0, size)))
                    count += 1
                    total_bytes = max(0, total_bytes + size)
                    now = time.time()
                    if count == 1 or count % 25 == 0 or (now - last_emit[0]) >= 0.15:
                        last_emit[0] = now
                        self._sig.scan_progress.emit(count, total_bytes)
                self._sig.scan_progress.emit(count, total_bytes)
            except Exception as e:
                self._sig.log_msg.emit(f"Scan error: {e}")
                debug(UTILITY_MASS_AV1_ENCODER, f"Scan error: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Auto-scan complete: count={count}, total_bytes={total_bytes}")
            self._sig.scan_done.emit(items, src)

        threading.Thread(target=_scan, daemon=True).start()

    def _on_scan_done(self, items, scanned_src):
        """Called in main thread when scan completes."""
        dlg = getattr(self, "_scan_dialog", None)
        if dlg:
            try:
                self._sig.scan_progress.disconnect(dlg.update_progress)
            except Exception:
                pass
            try:
                dlg.close()
            except Exception:
                pass
        self._scan_dialog = None
        self._apply_scan_result(items, scanned_src)

    def _on_scan_done_then_start(self, items, src, dst):
        """Called in main thread when scan completes (Start+empty queue path)."""
        dlg = getattr(self, "_scan_dialog", None)
        if dlg:
            try:
                self._sig.scan_progress.disconnect(dlg.update_progress)
            except Exception:
                pass
            try:
                dlg.close()
            except Exception:
                pass
        self._scan_dialog = None
        self._queue = items
        self._continue_start_encoding(src, dst)

    def _apply_scan_result(self, items, scanned_src):
        if self._edit_src.text().strip() != scanned_src:
            return
        self._source_scanned = True
        self._queue.clear()
        self._queue.extend(items)
        n = len(items)
        src = self._edit_src.text().strip()
        self._add_log(f"Scanned: {n} file{'s' if n != 1 else ''} ready.")
        total_b = sum(s for _, s in items)
        debug(UTILITY_MASS_AV1_ENCODER, f"Apply scan result: n={n}, total_bytes={total_b}, src={src}")
        if self._log_cb and n > 0:
            self._log_cb(f"AV1 Encoder: {n} files in queue.")
        self._update_start_enabled()

    def _browse_dst(self):
        picked, dialog_pw = run_local_remote_path_dialog(
            self, self._edit_dst.text().strip(), purpose="target"
        )
        if picked:
            self._edit_dst.blockSignals(True)
            self._edit_dst.setText(picked)
            self._edit_dst.blockSignals(False)
            if is_remote_path(picked):
                self._edit_ssh_pw.setText(dialog_pw)
            self._update_start_enabled()

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
        if is_remote_path(src) or is_remote_path(dst):
            if not shutil.which("ssh") or not shutil.which("scp"):
                self._add_log("ERROR: Remote encoding requires ssh and scp in PATH.")
                debug(UTILITY_MASS_AV1_ENCODER, "Start aborted: missing ssh/scp")
                return

        # FFmpeg check at startup
        if not shutil.which("ffmpeg"):
            self._add_log("ERROR: FFmpeg not found. Install ffmpeg and ensure it is in PATH.")
            debug(UTILITY_MASS_AV1_ENCODER, "Start aborted: FFmpeg not found")
            return

        if not self._queue:
            self._add_log("Scanning source...")
            debug(UTILITY_MASS_AV1_ENCODER, f"Start encoding: queue empty, scanning src={src}")
            scan_dialog = ScanProgressDialog(self)
            self._scan_dialog = scan_dialog
            self._sig.scan_progress.connect(scan_dialog.update_progress)
            scan_dialog.show()

            def _scan_then_start():
                if is_remote_path(src):
                    items = self._run_remote_scan_collect(src)
                    total_b = sum(s for _, s in items)
                    self._sig.scan_progress.emit(len(items), total_b)
                    self._sig.scan_done_then_start.emit(items, src, dst)
                    return
                count = 0
                total_bytes = 0
                items = []
                try:
                    for path, size in AV1EncoderEngine().scan_files(src):
                        items.append((path, size))
                        count += 1
                        total_bytes += size
                        self._sig.scan_progress.emit(count, total_bytes)
                except Exception as e:
                    self._sig.log_msg.emit(f"Scan error: {e}")
                    debug(UTILITY_MASS_AV1_ENCODER, f"Scan error: {e}")
                self._sig.scan_done_then_start.emit(items, src, dst)

            threading.Thread(target=_scan_then_start, daemon=True).start()
            return

        self._continue_start_encoding(src, dst)

    def _continue_start_encoding(self, src, dst):
        debug(UTILITY_MASS_AV1_ENCODER, f"_continue_start_encoding: queue_len={len(self._queue)}, src={src}, dst={dst}")
        if not self._queue:
            self._add_log("No compatible files found.")
            debug(UTILITY_MASS_AV1_ENCODER, f"No compatible files in {src}")
            return

        self._encode_pw = None
        self._remote_dst_remote = None
        self._remote_dst_root_posix = None
        self._remote_src_structure_root_posix = None
        r_dst = is_remote_path(dst)
        if r_dst:
            self._remote_dst_remote, self._remote_dst_root_posix = remote_target_and_root(dst)
        if is_remote_path(src) or r_dst:
            try:
                self._encode_pw = password_for_remote_encode(self._edit_ssh_pw.text())
            except RemoteEncodeError as e:
                self._add_log(f"ERROR: {e}")
                return

        # Long path warning (Windows MAX_PATH ~260)
        if platform.system() == "Windows":
            for p, _ in list(self._queue)[:3]:
                ps = p.abs_posix if isinstance(p, RemoteFileRef) else os.path.abspath(p)
                ds = dst if r_dst else os.path.abspath(dst)
                if len(ps) > 200 or len(ds) > 200:
                    self._add_log("WARNING: Paths exceed 200 chars; Windows may fail. Enable long paths in Registry.")
                    debug(UTILITY_MASS_AV1_ENCODER, "Long path detected")
                    break

        # Disk space check before starting (local target or temp space for remote target)
        total_bytes = sum(s for _, s in self._queue)
        disk_check_path = dst if not r_dst else tempfile.gettempdir()
        try:
            usage = shutil.disk_usage(disk_check_path)
            required = total_bytes * 1.1  # 10% buffer
            if usage.free < required:
                self._add_log(
                    f"WARNING: Low disk space ({disk_check_path}). Free: {usage.free / (1024**3):.1f} GB, "
                    f"need ~{required / (1024**3):.1f} GB. Proceeding anyway."
                )
                debug(UTILITY_MASS_AV1_ENCODER, f"Low disk: free={usage.free}, need~{required}")
        except OSError as e:
            self._add_log(f"WARNING: Could not check disk space: {e}. Proceeding anyway.")

        if not try_acquire_fs_heavy("Mass AV1 Encoder"):
            _busy = (
                "Another file-heavy task is running (Media Organizer, AI Media Scanner, AI Image Upscaler, "
                "or AI Video Upscaler). Wait for it to finish."
            )
            QMessageBox.warning(self, "Busy", _busy)
            self._add_log(f"ERROR: {_busy}")
            debug(UTILITY_MASS_AV1_ENCODER, "Start blocked: fs_task_lock busy")
            return
        self._fs_heavy_held = True

        self._queue_sizes = {}
        for p, s in self._queue:
            k = p.abs_posix if isinstance(p, RemoteFileRef) else p
            self._queue_sizes[k] = s
        self._total_q_bytes = sum(s for _, s in self._queue)
        self._done_bytes = 0.0
        self._total_count = len(self._queue)
        self._done_count = 0
        self._active_jobs = 0
        self._active_lock = threading.Lock()
        self._job_progress = {}
        self._current_files = {}
        self._total_saved = 0
        self._is_encoding = True
        self._is_paused = False
        self._batch_start = time.time()
        if self._status_cb:
            self._status_cb("encoding")

        self._bar_master.setRange(0, 100)
        self._bar_master.setValue(0)
        self._bar_master.setFormat(f"0/{self._total_count} Files")
        self._lbl_eta.setText("ESTIMATED TIME REMAINING: --:--:--")
        self._lbl_io.setText("I/O: 0.0 MB/s")

        self._btn_start.setStyleSheet("")
        self._btn_start.setText("STOP ENCODING")
        self._btn_start.setObjectName("btnStop")
        self._btn_start.setStyle(self.style())
        self._btn_pause.setEnabled(True)
        self._update_start_enabled()

        self._add_log(f"Starting encode — {self._total_count} files.")
        # Hint when both paths appear to be on network (NAS) — can cause failures; retry with software decode helps
        if any(x in src.lower() for x in ("/mnt/", "smb://", "//", "\\\\")) and any(
            x in dst.lower() for x in ("/mnt/", "smb://", "//", "\\\\")
        ):
            self._add_log(
                "TIP: Source and target on network — if some files fail, try fewer concurrent jobs or use local copy."
            )
        debug(UTILITY_MASS_AV1_ENCODER, f"Encode start: {self._total_count} files, src={src}, dst={dst}")
        structured_event(
            "encode_batch_start",
            file_count=self._total_count,
            src=src[:300],
            dst=dst[:300],
        )
        if self._log_cb:
            self._log_cb(f"AV1 Encoder: {self._total_count} files queued.")

        # Structure root: common parent of all queued files so we mirror only meaningful subdirs
        # (avoids recreating a top-level "Source" or similar wrapper folder in target)
        structure_root = None
        # Pipeline mode only when *every* item is remote; a mixed queue must use the legacy worker.
        use_remote_pipeline = len(self._queue) > 0 and all(
            isinstance(x[0], RemoteFileRef) for x in self._queue
        )
        if self._settings.get("maintain_structure") and self._queue:
            if use_remote_pipeline:
                self._remote_src_structure_root_posix = common_structure_root_posix(
                    [x[0] for x in self._queue]
                )
                debug(
                    UTILITY_MASS_AV1_ENCODER,
                    f"Remote structure root (mirror): {self._remote_src_structure_root_posix}",
                )
            else:
                all_dirs = [
                    os.path.dirname(p) for p, _ in self._queue if not isinstance(p, RemoteFileRef)
                ]
                if all_dirs:
                    try:
                        structure_root = os.path.commonpath(all_dirs)
                    except ValueError:
                        structure_root = src  # fallback if mixed drives (Windows) or inconsistent paths
                else:
                    structure_root = src
                debug(UTILITY_MASS_AV1_ENCODER, f"Structure root (mirror): {structure_root}")

        num_workers = self._settings.get("concurrent_jobs")
        try:
            num_workers = int(num_workers)
        except (TypeError, ValueError):
            num_workers = 2
        num_workers = max(1, min(8, num_workers))
        AV1EncoderEngine.reset_nvenc_cuda_hwaccel_for_new_batch()
        self._engine_pool = [AV1EncoderEngine(job_id=i) for i in range(num_workers)]
        if use_remote_pipeline:
            cap = _remote_pipeline_queue_cap(num_workers)
            self._encode_pipeline_q = queue.Queue(maxsize=cap)
            self._pipeline_prefetch_stop.clear()
            pl_work = list(self._queue)
            self._queue.clear()
            self._pipeline_prefetch_thread = threading.Thread(
                target=self._pipeline_prefetch_loop,
                args=(pl_work, src, dst, structure_root, num_workers),
                daemon=True,
                name="chronoarchiver-remote-prefetch",
            )
            self._pipeline_prefetch_thread.start()
            self._add_log(
                "Network pipeline: prefetching upcoming source file(s) while encoding runs "
                f"(buffer ≤ {cap} on local disk) — keeps the GPU busy."
            )
            debug(
                UTILITY_MASS_AV1_ENCODER,
                f"Remote prefetch pipeline: cap={cap} jobs={len(pl_work)} (all-remote queue)",
            )
        else:
            self._encode_pipeline_q = None
            self._pipeline_prefetch_thread = None

        for eng in self._engine_pool:
            eng.on_progress = lambda j, p: self._sig.progress.emit(j, p)
            eng.on_details = lambda j, v, a: self._sig.details.emit(j, v, a)
            threading.Thread(target=self._job_worker, args=(eng, src, dst, structure_root), daemon=True).start()

    def get_activity(self):
        return "encoding" if self._is_encoding else "idle"

    def _stop_encoding(self):
        self._is_encoding = False
        self._pipeline_prefetch_stop.set()
        self._encode_pw = None
        self._remote_dst_remote = None
        self._remote_dst_root_posix = None
        self._remote_src_structure_root_posix = None
        if self._status_cb:
            self._status_cb("idle")
        for eng in self._engine_pool:
            eng.cancel()
        if self._fs_heavy_held:
            release_fs_heavy()
            self._fs_heavy_held = False
        self._btn_start.setStyleSheet("")
        self._btn_start.setText("START ENCODING")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setStyle(self.style())
        self._btn_pause.setEnabled(False)
        self._update_start_enabled()
        self._add_log("Encoding stopped.")
        debug(UTILITY_MASS_AV1_ENCODER, "Encoding stopped by user.")
        self._encode_pipeline_q = None
        QTimer.singleShot(2500, self._sweep_chrono_encoder_tempdir)

    def _toggle_pause(self):
        paused = any(e._is_paused for e in self._engine_pool)
        for eng in self._engine_pool:
            if paused:
                eng.resume()
            else:
                eng.pause()
        self._btn_pause.setText("PAUSE" if paused else "RESUME")

    def _pipeline_plan_remote_item(
        self,
        item,
        size: int,
        src: str,
        dst: str,
        structure_root,
        *,
        dst_remote,
        dst_root_px: str,
        rem_struct: str | None,
    ):
        """
        Path planning for one remote source file (no download). Returns:
        ``("fin", meta_dict)`` for immediate finish (skip / invalid path), or
        ``("encode", ctx)`` with output path and remote_out_posix; input must be downloaded to ``ctx["tmp_in_slot"]``.
        """
        ref = item if isinstance(item, RemoteFileRef) else None
        if not ref:
            return (
                "fin",
                {
                    "logical_key": str(item),
                    "ok": False,
                    "remote_src_ref": None,
                    "tmp_cleanup": [],
                },
            )

        logical_key = ref.abs_posix
        remote_out_posix: str | None = None
        tpath_local: str | None = None

        if self._settings.get("maintain_structure"):
            if rem_struct:
                try:
                    rel_stem = posixpath.splitext(
                        posixpath.relpath(ref.abs_posix, rem_struct)
                    )[0].replace("\\", "/")
                except ValueError:
                    return ("fin", {"logical_key": logical_key, "ok": False, "remote_src_ref": ref, "tmp_cleanup": []})
            else:
                rel_stem = posixpath.splitext(ref.rel_posix.replace("\\", "/"))[0]
            if ".." in rel_stem.split("/"):
                return ("fin", {"logical_key": logical_key, "ok": False, "remote_src_ref": ref, "tmp_cleanup": []})
            if dst_remote:
                remote_out_posix = posix_join_under(dst_root_px, rel_stem)
            else:
                try:
                    tpath_local = join_dst_local(dst, rel_stem)
                except ValueError:
                    return ("fin", {"logical_key": logical_key, "ok": False, "remote_src_ref": ref, "tmp_cleanup": []})
                try:
                    real_tpath = os.path.realpath(tpath_local)
                    real_dst = os.path.realpath(dst)
                    if not (real_tpath == real_dst or real_tpath.startswith(real_dst + os.sep)):
                        return ("fin", {"logical_key": logical_key, "ok": False, "remote_src_ref": ref, "tmp_cleanup": []})
                except OSError:
                    return ("fin", {"logical_key": logical_key, "ok": False, "remote_src_ref": ref, "tmp_cleanup": []})
                out_dir = os.path.dirname(tpath_local)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
        else:
            flat_stem = posixpath.splitext(posixpath.basename(ref.rel_posix))[0]
            if dst_remote:
                remote_out_posix = posix_join_under(dst_root_px, flat_stem)
            else:
                tpath_local = os.path.join(dst, flat_stem + "_av1.mp4")

        policy = self._settings.get("existing_output")
        pw = self._encode_pw
        if dst_remote and remote_out_posix:
            exists = remote_file_exists(dst_remote, remote_out_posix, pw)
        else:
            exists = bool(tpath_local and os.path.exists(tpath_local))

        if exists:
            if policy == "skip":
                return (
                    "fin",
                    {
                        "logical_key": logical_key,
                        "ok": True,
                        "remote_src_ref": ref,
                        "tmp_cleanup": [],
                        "skip_msg": True,
                    },
                )
            if policy == "rename":
                if dst_remote and remote_out_posix:
                    rb, rx = posixpath.splitext(remote_out_posix)
                    n = 1
                    cand = f"{rb}_{n}{rx}"
                    while remote_file_exists(dst_remote, cand, pw):
                        n += 1
                        cand = f"{rb}_{n}{rx}"
                    remote_out_posix = cand
                elif tpath_local:
                    b, ext = os.path.splitext(tpath_local)
                    n = 1
                    cand = f"{b}_{n}{ext}"
                    while os.path.exists(cand):
                        n += 1
                        cand = f"{b}_{n}{ext}"
                    tpath_local = cand

        if dst_remote:
            tfd, tpath_local = tempfile.mkstemp(suffix=".mp4", prefix=_ENCODER_TMP_PREFIX)
            os.close(tfd)
        assert tpath_local is not None

        return (
            "encode",
            {
                "logical_key": logical_key,
                "ref": ref,
                "size": size,
                "remote_out_posix": remote_out_posix,
                "tpath_local": tpath_local,
                "dst_remote": bool(dst_remote),
            },
        )

    def _pipeline_prefetch_loop(
        self,
        work_list: list,
        src: str,
        dst: str,
        structure_root,
        num_workers: int,
    ):
        """Sequential prefetch: plan → download → bounded queue so encode overlaps network I/O."""
        pw = self._encode_pw
        dst_remote = self._remote_dst_remote
        dst_root_px = (self._remote_dst_root_posix or "").strip() or "/"
        rem_struct = self._remote_src_structure_root_posix
        pq = self._encode_pipeline_q
        if pq is None:
            return
        try:
            for item, size in work_list:
                if self._pipeline_prefetch_stop.is_set() or not self._is_encoding:
                    break
                kind, payload = self._pipeline_plan_remote_item(
                    item,
                    size,
                    src,
                    dst,
                    structure_root,
                    dst_remote=dst_remote,
                    dst_root_px=dst_root_px,
                    rem_struct=rem_struct,
                )
                if kind == "fin":
                    pq.put({"op": "fin", "payload": payload}, timeout=600)
                    continue
                # encode
                ctx = payload
                ref = ctx["ref"]
                tmp_cleanup: list[str] = []
                if ctx.get("dst_remote"):
                    tmp_cleanup.append(ctx["tpath_local"])
                fd, tmp_in = tempfile.mkstemp(
                    suffix=posixpath.splitext(ref.rel_posix)[1] or ".mkv",
                    prefix=_ENCODER_TMP_PREFIX,
                )
                os.close(fd)
                tmp_cleanup.append(tmp_in)
                try:
                    run_scp_from_remote(ref.target, ref.abs_posix, tmp_in, password_for_sshpass=pw)
                except RemoteEncodeError as e:
                    _finalize_encoder_temp_files(tmp_cleanup, success=False, local_in=tmp_in, local_out="")
                    pq.put(
                        {
                            "op": "fin",
                            "payload": {
                                "logical_key": ctx["logical_key"],
                                "ok": False,
                                "remote_src_ref": ref,
                                "tmp_cleanup": [],
                                "err": str(e),
                            },
                        },
                        timeout=120,
                    )
                    continue
                pq.put(
                    {
                        "op": "encode",
                        "ctx": ctx,
                        "tmp_in": tmp_in,
                        "tmp_cleanup": tmp_cleanup,
                    },
                    timeout=7200,
                )
        except Exception as e:
            if isinstance(e, queue.Full):
                debug(
                    UTILITY_MASS_AV1_ENCODER,
                    "Pipeline prefetch: bounded queue full (timeout on put); workers may be stalled",
                )
            debug(UTILITY_MASS_AV1_ENCODER, f"Pipeline prefetch fatal: {e}")
            log_exception(e, context="pipeline_prefetch", utility=UTILITY_MASS_AV1_ENCODER)
        finally:
            try:
                for _ in range(num_workers):
                    pq.put(None, timeout=60)
            except Exception:
                pass

    def _job_worker_pipeline(self, engine, src, dst, structure_root=None):
        """Consumer for prefetched remote files (overlap download + NVENC)."""
        pw = self._encode_pw
        dst_remote = self._remote_dst_remote
        pq = self._encode_pipeline_q

        with self._active_lock:
            self._active_jobs += 1

        def _fin(ok: bool, logical_key: str, local_out: str, meta: dict | None):
            self._sig.finished.emit(engine.job_id, ok, logical_key, local_out or "", meta)

        try:
            # Drain until each worker receives a None sentinel. Do not tie the loop to
            # _is_encoding: _finalize_batch_complete clears it when the last file finishes,
            # which would otherwise exit before sentinels are consumed and strand queue items.
            while True:
                try:
                    task = pq.get(timeout=0.5)
                except queue.Empty:
                    continue
                if task is None:
                    break
                if not isinstance(task, dict):
                    debug(
                        UTILITY_MASS_AV1_ENCODER,
                        f"Pipeline worker: ignored non-dict queue item: {type(task).__name__}",
                    )
                    continue
                if task.get("op") == "fin":
                    pl = task.get("payload") or {}
                    lk = pl.get("logical_key") or ""
                    ref = pl.get("remote_src_ref")
                    if pl.get("skip_msg"):
                        disp = posixpath.basename(ref.rel_posix) if ref else lk
                        self._sig.log_msg.emit(f"SKIP (exists): {disp}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Skipped existing (pipeline): {lk}")
                    if pl.get("err"):
                        self._sig.log_msg.emit(f"Remote I/O error: {pl['err']}")
                    _fin(
                        bool(pl.get("ok")),
                        lk,
                        "",
                        {
                            "logical_key": lk,
                            "local_in": "",
                            "local_out": "",
                            "remote_src_ref": ref,
                            "tmp_cleanup": [],
                        },
                    )
                    continue
                try:
                    ctx = task["ctx"]
                    tmp_in = task["tmp_in"]
                    tmp_cleanup = list(task.get("tmp_cleanup") or [])
                    logical_key = ctx["logical_key"]
                    ref = ctx["ref"]
                    tpath_local = ctx["tpath_local"]
                    remote_out_posix = ctx["remote_out_posix"]
                except (KeyError, TypeError) as e:
                    debug(UTILITY_MASS_AV1_ENCODER, f"Pipeline worker: bad encode task payload: {e}")
                    continue

                self._current_files[engine.job_id] = ref.abs_posix if ref else logical_key

                out_p: str | None = None
                try:
                    if not self._is_encoding:
                        # Batch ended or STOP: drop scratch files (tmp_cleanup lists tmp_in + remote encode buffer).
                        _finalize_encoder_temp_files(
                            tmp_cleanup, success=False, local_in=tmp_in, local_out=""
                        )
                        _fin(
                            False,
                            logical_key,
                            "",
                            {
                                "logical_key": logical_key,
                                "local_in": "",
                                "local_out": "",
                                "remote_src_ref": ref,
                                "tmp_cleanup": [],
                            },
                        )
                        continue

                    if self._settings.get("rejects_enabled"):
                        dur = engine._get_video_duration(tmp_in)
                        thr = (
                            self._settings.get("rejects_h") * 3600
                            + self._settings.get("rejects_m") * 60
                            + self._settings.get("rejects_s")
                        )
                        if dur <= thr:
                            bn = posixpath.basename(ref.rel_posix) if ref else os.path.basename(tmp_in)
                            self._add_log(f"REJECTED: {bn} ({dur:.1f}s)")
                            debug(UTILITY_MASS_AV1_ENCODER, f"Rejected (short): {logical_key} ({dur:.1f}s)")
                            _finalize_encoder_temp_files(tmp_cleanup, success=True, local_in=tmp_in, local_out="")
                            _fin(
                                True,
                                logical_key,
                                "",
                                {
                                    "logical_key": logical_key,
                                    "local_in": tmp_in,
                                    "local_out": "",
                                    "remote_src_ref": ref,
                                    "tmp_cleanup": [],
                                },
                            )
                            continue

                    ok_ready, ready_err = verify_local_media_file_ready(tmp_in)
                    if not ok_ready:
                        self._sig.log_msg.emit(f"Source not ready: {ready_err}")
                        debug(
                            UTILITY_MASS_AV1_ENCODER,
                            f"Pipeline worker: source not ready {tmp_in!r}: {ready_err}",
                        )
                        _finalize_encoder_temp_files(tmp_cleanup, success=False, local_in=tmp_in, local_out="")
                        _fin(
                            False,
                            logical_key,
                            "",
                            {
                                "logical_key": logical_key,
                                "local_in": "",
                                "local_out": "",
                                "remote_src_ref": ref,
                                "tmp_cleanup": [],
                            },
                        )
                        continue

                    if engine.try_passthrough_existing_av1(tmp_in, tpath_local):
                        disp = posixpath.basename(ref.rel_posix)
                        self._sig.log_msg.emit(f"Already AV1 (passthrough): {disp}")
                        ok, in_p, out_p = True, tmp_in, tpath_local
                    else:
                        ok, in_p, out_p = engine.encode_file(
                            tmp_in,
                            tpath_local,
                            self._settings.get("quality"),
                            self._settings.get("preset"),
                            self._settings.get("reencode_audio"),
                            hw_accel_decode=self._settings.get("hw_accel_decode"),
                        )

                    if ok and dst_remote and remote_out_posix:
                        try:
                            parent = posixpath.dirname(remote_out_posix)
                            if parent:
                                remote_mkdir_p(dst_remote, parent, pw)
                            run_scp_to_remote(
                                out_p, dst_remote, remote_out_posix, password_for_sshpass=pw
                            )
                        except RemoteEncodeError as e:
                            self._sig.log_msg.emit(f"Remote upload error: {e}")
                            debug(UTILITY_MASS_AV1_ENCODER, f"scp push failed: {e}")
                            ok = False
                            if out_p and os.path.isfile(out_p):
                                tmp_cleanup.append(out_p)

                    if ok and dst_remote:
                        tmp_cleanup.append(out_p)

                    saved_hint = _finalize_encoder_temp_files(
                        tmp_cleanup,
                        success=ok,
                        local_in=tmp_in,
                        local_out=out_p or "",
                    )
                    meta = {
                        "logical_key": logical_key,
                        "local_in": tmp_in,
                        "local_out": out_p,
                        "remote_src_ref": ref,
                        "tmp_cleanup": [],
                    }
                    if saved_hint is not None:
                        meta["saved_bytes"] = saved_hint
                    _fin(ok, logical_key, out_p if ok else out_p, meta)
                except Exception as job_e:
                    self._sig.log_msg.emit(f"ERROR: {job_e}")
                    debug(UTILITY_MASS_AV1_ENCODER, f"Encoder pipeline job: {job_e}")
                    log_exception(job_e, context="encoder_pipeline_job", utility=UTILITY_MASS_AV1_ENCODER)
                    try:
                        _finalize_encoder_temp_files(
                            tmp_cleanup, success=False, local_in=tmp_in, local_out=out_p or ""
                        )
                    except Exception:
                        pass
                    _fin(
                        False,
                        logical_key,
                        "",
                        {
                            "logical_key": logical_key,
                            "local_in": "",
                            "local_out": "",
                            "remote_src_ref": ref,
                            "tmp_cleanup": [],
                        },
                    )

        except Exception as e:
            self._sig.log_msg.emit(f"ERROR: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encoder pipeline worker: {e}")
            log_exception(e, context="encoder_pipeline_worker", utility=UTILITY_MASS_AV1_ENCODER)
        finally:
            with self._active_lock:
                self._active_jobs -= 1
            if self._active_jobs == 0:
                self._sig.log_msg.emit("Encoding batch complete.")
                self._sig.batch_complete.emit()
                debug(UTILITY_MASS_AV1_ENCODER, "Encoding batch complete.")

    def _job_worker(self, engine, src, dst, structure_root=None):
        if self._encode_pipeline_q is not None:
            self._job_worker_pipeline(engine, src, dst, structure_root)
            return

        pw = self._encode_pw
        dst_remote = self._remote_dst_remote
        dst_root_px = (self._remote_dst_root_posix or "").strip() or "/"
        rem_struct = self._remote_src_structure_root_posix

        with self._active_lock:
            self._active_jobs += 1
        q_lock = self._queue_lock

        def _fin(ok: bool, logical_key: str, local_out: str, meta: dict | None):
            self._sig.finished.emit(engine.job_id, ok, logical_key, local_out or "", meta)

        try:
            while self._is_encoding:
                item = None
                size = 0
                with q_lock:
                    if self._queue:
                        item, size = self._queue.pop(0)
                        ref0 = item if isinstance(item, RemoteFileRef) else None
                        self._current_files[engine.job_id] = ref0.abs_posix if ref0 else item

                if item is None:
                    break

                ref = item if isinstance(item, RemoteFileRef) else None
                logical_key = ref.abs_posix if ref else item
                tmp_cleanup: list[str] = []

                try:
                    remote_out_posix: str | None = None
                    tpath_local: str | None = None

                    if self._settings.get("maintain_structure"):
                        if ref and rem_struct:
                            try:
                                rel_stem = posixpath.splitext(
                                    posixpath.relpath(ref.abs_posix, rem_struct)
                                )[0].replace("\\", "/")
                            except ValueError:
                                self._add_log(f"SKIP (invalid path): {posixpath.basename(ref.rel_posix)}")
                                _fin(False, logical_key, "", None)
                                continue
                        elif ref:
                            rel_stem = posixpath.splitext(ref.rel_posix.replace("\\", "/"))[0]
                        else:
                            base = structure_root if structure_root else src
                            rel = os.path.relpath(item, base)
                            rel_stem = os.path.splitext(rel)[0].replace(os.sep, "/")
                        if ".." in rel_stem.split("/"):
                            self._add_log(
                                f"SKIP (invalid path): {posixpath.basename(ref.rel_posix) if ref else os.path.basename(item)}"
                            )
                            _fin(False, logical_key, "", None)
                            continue
                        if dst_remote:
                            remote_out_posix = posix_join_under(dst_root_px, rel_stem)
                        else:
                            try:
                                tpath_local = join_dst_local(dst, rel_stem)
                            except ValueError:
                                self._add_log(
                                    f"SKIP (invalid path): {posixpath.basename(ref.rel_posix) if ref else os.path.basename(item)}"
                                )
                                _fin(False, logical_key, "", None)
                                continue
                            try:
                                real_tpath = os.path.realpath(tpath_local)
                                real_dst = os.path.realpath(dst)
                                if not (real_tpath == real_dst or real_tpath.startswith(real_dst + os.sep)):
                                    self._add_log(
                                        f"SKIP (path outside target): {posixpath.basename(ref.rel_posix) if ref else os.path.basename(item)}"
                                    )
                                    _fin(False, logical_key, "", None)
                                    continue
                            except OSError:
                                _fin(False, logical_key, "", None)
                                continue
                            out_dir = os.path.dirname(tpath_local)
                            if out_dir:
                                os.makedirs(out_dir, exist_ok=True)
                    else:
                        if ref:
                            flat_stem = posixpath.splitext(posixpath.basename(ref.rel_posix))[0]
                        else:
                            flat_stem = os.path.splitext(os.path.basename(item))[0]
                        if dst_remote:
                            remote_out_posix = posix_join_under(dst_root_px, flat_stem)
                        else:
                            tpath_local = os.path.join(dst, flat_stem + "_av1.mp4")

                    policy = self._settings.get("existing_output")
                    if dst_remote and remote_out_posix:
                        exists = remote_file_exists(dst_remote, remote_out_posix, pw)
                    else:
                        exists = bool(tpath_local and os.path.exists(tpath_local))

                    if exists:
                        if policy == "skip":
                            disp = posixpath.basename(remote_out_posix) if remote_out_posix else os.path.basename(tpath_local or "")
                            self._add_log(f"SKIP (exists): {disp}")
                            debug(UTILITY_MASS_AV1_ENCODER, f"Skipped existing: {remote_out_posix or tpath_local}")
                            _fin(True, logical_key, "", None)
                            continue
                        if policy == "rename":
                            if dst_remote and remote_out_posix:
                                rb, rx = posixpath.splitext(remote_out_posix)
                                n = 1
                                cand = f"{rb}_{n}{rx}"
                                while remote_file_exists(dst_remote, cand, pw):
                                    n += 1
                                    cand = f"{rb}_{n}{rx}"
                                remote_out_posix = cand
                            elif tpath_local:
                                b, ext = os.path.splitext(tpath_local)
                                n = 1
                                cand = f"{b}_{n}{ext}"
                                while os.path.exists(cand):
                                    n += 1
                                    cand = f"{b}_{n}{ext}"
                                tpath_local = cand

                    if dst_remote:
                        tfd, tpath_local = tempfile.mkstemp(suffix=".mp4", prefix=_ENCODER_TMP_PREFIX)
                        os.close(tfd)
                        tmp_cleanup.append(tpath_local)

                    assert tpath_local is not None

                    if ref:
                        fd, tmp_in = tempfile.mkstemp(
                            suffix=posixpath.splitext(ref.rel_posix)[1] or ".mkv",
                            prefix=_ENCODER_TMP_PREFIX,
                        )
                        os.close(fd)
                        tmp_cleanup.append(tmp_in)
                        run_scp_from_remote(ref.target, ref.abs_posix, tmp_in, password_for_sshpass=pw)
                        input_path = tmp_in
                    else:
                        input_path = item

                    if not self._is_encoding:
                        _finalize_encoder_temp_files(
                            tmp_cleanup, success=False, local_in=input_path, local_out=""
                        )
                        _fin(
                            False,
                            logical_key,
                            "",
                            {
                                "logical_key": logical_key,
                                "local_in": "",
                                "local_out": "",
                                "remote_src_ref": ref,
                                "tmp_cleanup": [],
                            },
                        )
                        continue

                    if self._settings.get("rejects_enabled"):
                        dur = engine._get_video_duration(input_path)
                        thr = (
                            self._settings.get("rejects_h") * 3600
                            + self._settings.get("rejects_m") * 60
                            + self._settings.get("rejects_s")
                        )
                        if dur <= thr:
                            bn = posixpath.basename(ref.rel_posix) if ref else os.path.basename(input_path)
                            self._add_log(f"REJECTED: {bn} ({dur:.1f}s)")
                            debug(UTILITY_MASS_AV1_ENCODER, f"Rejected (short): {logical_key} ({dur:.1f}s)")
                            _finalize_encoder_temp_files(
                                tmp_cleanup, success=True, local_in=input_path, local_out=""
                            )
                            _fin(
                                True,
                                logical_key,
                                "",
                                {
                                    "logical_key": logical_key,
                                    "local_in": input_path,
                                    "local_out": "",
                                    "remote_src_ref": ref,
                                    "tmp_cleanup": [],
                                },
                            )
                            continue

                    ok_ready, ready_err = verify_local_media_file_ready(input_path)
                    if not ok_ready:
                        self._sig.log_msg.emit(f"Source not ready: {ready_err}")
                        debug(
                            UTILITY_MASS_AV1_ENCODER,
                            f"Legacy worker: source not ready {input_path!r}: {ready_err}",
                        )
                        _finalize_encoder_temp_files(
                            tmp_cleanup, success=False, local_in=input_path, local_out=""
                        )
                        _fin(
                            False,
                            logical_key,
                            "",
                            {
                                "logical_key": logical_key,
                                "local_in": "",
                                "local_out": "",
                                "remote_src_ref": ref,
                                "tmp_cleanup": [],
                            },
                        )
                        continue

                    disp_bn = (
                        posixpath.basename(ref.rel_posix) if ref else os.path.basename(input_path)
                    )
                    if engine.try_passthrough_existing_av1(input_path, tpath_local):
                        self._sig.log_msg.emit(f"Already AV1 (passthrough): {disp_bn}")
                        ok, in_p, out_p = True, input_path, tpath_local
                    else:
                        ok, in_p, out_p = engine.encode_file(
                            input_path,
                            tpath_local,
                            self._settings.get("quality"),
                            self._settings.get("preset"),
                            self._settings.get("reencode_audio"),
                            hw_accel_decode=self._settings.get("hw_accel_decode"),
                        )

                    if ok and dst_remote and remote_out_posix:
                        try:
                            parent = posixpath.dirname(remote_out_posix)
                            if parent:
                                remote_mkdir_p(dst_remote, parent, pw)
                            run_scp_to_remote(
                                out_p, dst_remote, remote_out_posix, password_for_sshpass=pw
                            )
                        except RemoteEncodeError as e:
                            self._sig.log_msg.emit(f"Remote upload error: {e}")
                            debug(UTILITY_MASS_AV1_ENCODER, f"scp push failed: {e}")
                            ok = False
                            if out_p and os.path.isfile(out_p):
                                tmp_cleanup.append(out_p)

                    if ok and dst_remote:
                        tmp_cleanup.append(out_p)

                    saved_hint = _finalize_encoder_temp_files(
                        tmp_cleanup,
                        success=ok,
                        local_in=input_path,
                        local_out=out_p or "",
                    )
                    meta = {
                        "logical_key": logical_key,
                        "local_in": input_path,
                        "local_out": out_p,
                        "remote_src_ref": ref,
                        "tmp_cleanup": [],
                    }
                    if saved_hint is not None:
                        meta["saved_bytes"] = saved_hint
                    _fin(ok, logical_key, out_p if ok else out_p, meta)

                except RemoteEncodeError as e:
                    self._sig.log_msg.emit(f"Remote I/O error: {e}")
                    debug(UTILITY_MASS_AV1_ENCODER, f"Remote encode error: {e}")
                    _finalize_encoder_temp_files(
                        tmp_cleanup, success=False, local_in="", local_out=""
                    )
                    _fin(
                        False,
                        logical_key,
                        "",
                        {
                            "logical_key": logical_key,
                            "local_in": "",
                            "local_out": "",
                            "remote_src_ref": ref,
                            "tmp_cleanup": [],
                        },
                    )
                except Exception as e:
                    self._sig.log_msg.emit(f"ERROR: {e}")
                    debug(UTILITY_MASS_AV1_ENCODER, f"Encoder job error: {e}")
                    _finalize_encoder_temp_files(
                        tmp_cleanup, success=False, local_in="", local_out=""
                    )
                    _fin(
                        False,
                        logical_key,
                        "",
                        {
                            "logical_key": logical_key,
                            "local_in": "",
                            "local_out": "",
                            "remote_src_ref": ref,
                            "tmp_cleanup": [],
                        },
                    )

        except Exception as e:
            self._sig.log_msg.emit(f"ERROR: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encoder worker exception: {e}")
        finally:
            with self._active_lock:
                self._active_jobs -= 1
            if self._active_jobs == 0 and not self._queue:
                self._sig.log_msg.emit("Encoding batch complete.")
                self._sig.batch_complete.emit()
                debug(UTILITY_MASS_AV1_ENCODER, "Encoding batch complete.")

    # ── signal handlers ───────────────────────────────────────────────────────

    def _on_progress(self, job_id, p: EncodingProgress):
        if (
            not self._is_encoding
            or job_id < 0
            or job_id >= len(self._job_bars)
            or job_id >= len(self._job_labels)
            or job_id >= len(self._job_speeds)
        ):
            return
        fname = p.file_name
        if len(fname) > 28:
            fname = fname[:12] + "..." + fname[-13:]
        self._job_labels[job_id].setText(f"{job_id + 1}: {fname}")
        self._job_bars[job_id].setValue(int(p.percent))
        self._job_speeds[job_id].setText(f"{p.fps:.1f} fps / {p.speed:.2f}x")
        self._job_progress[job_id] = p.percent

        # I/O throughput
        active_bytes = 0.0
        for jid, pct in self._job_progress.items():
            if jid in self._current_files:
                fsize = self._queue_sizes.get(self._current_files[jid], 0.0)
                active_bytes += (pct / 100) * fsize
        total_written = self._done_bytes + active_bytes
        elapsed = time.time() - self._batch_start
        if elapsed > 0.5:
            rate_mbs = (total_written / (1024 * 1024)) / elapsed
            self._lbl_io.setText(f"I/O: {rate_mbs:.1f} MB/s")

        # Master bar + ETA
        if self._total_q_bytes > 0:
            done = self._done_bytes + active_bytes
            pct_total = min(100.0, done / self._total_q_bytes * 100)
            self._bar_master.setValue(int(pct_total))
            self._bar_master.setFormat(f"{self._done_count}/{self._total_count} Files — {pct_total:.1f}%")
            remaining_bytes = self._total_q_bytes - done
            if remaining_bytes > 0 and elapsed > 2 and total_written > 0:
                rate = total_written / elapsed
                eta_sec = remaining_bytes / rate
                eh = int(eta_sec // 3600)
                em = int((eta_sec % 3600) // 60)
                es = int(eta_sec % 60)
                self._lbl_eta.setText(f"ESTIMATED TIME REMAINING: {eh:02}:{em:02}:{es:02}")
            elif pct_total >= 99.9:
                self._lbl_eta.setText("ESTIMATED TIME REMAINING: 00:00:00")

    def _on_details(self, job_id, vid, aud):
        if job_id < 0 or job_id >= len(self._job_vid):
            return
        self._job_vid[job_id].setText(vid)
        self._job_aud[job_id].setText(aud)

    def _on_encode_finished(self, job_id, success, logical_key, local_out_disp, meta=None):
        meta = meta if isinstance(meta, dict) else None
        if meta:
            lk = meta.get("logical_key") or logical_key
            local_in = meta.get("local_in") or ""
            local_out = meta.get("local_out") or ""
            remote_ref = meta.get("remote_src_ref")
            tmp_cleanup = list(meta.get("tmp_cleanup") or [])
        else:
            lk = logical_key
            local_in = logical_key
            local_out = local_out_disp
            remote_ref = None
            tmp_cleanup = []

        self._job_progress[job_id] = 0.0
        self._current_files.pop(job_id, None)

        disp_src = posixpath.basename((lk or "").replace("\\", "/")) or (
            os.path.basename(local_in) if local_in else "?"
        )

        saved_override = meta.get("saved_bytes") if meta else None
        if success:
            if saved_override is not None:
                try:
                    saved = int(saved_override)
                    if saved > 0:
                        self._total_saved += saved
                    mb = self._total_saved / (1024 * 1024)
                    self._lbl_saved.setText(
                        f"Space Saved: {mb / 1024:.2f} GB" if mb > 1024 else f"Space Saved: {mb:.1f} MB"
                    )
                    self._add_log(f"DONE: {disp_src} | Saved {max(0, saved) // (1024 * 1024)} MB")
                    debug(
                        UTILITY_MASS_AV1_ENCODER,
                        f"Done: {disp_src} -> {os.path.basename(local_out or '?')}, saved {max(0, saved) // (1024 * 1024)} MB",
                    )
                except (TypeError, ValueError, OSError):
                    pass
            elif local_in and local_out and os.path.exists(local_out):
                try:
                    in_sz = os.path.getsize(local_in) if os.path.isfile(local_in) else 0
                    saved = in_sz - os.path.getsize(local_out)
                    if saved > 0:
                        self._total_saved += saved
                    mb = self._total_saved / (1024 * 1024)
                    self._lbl_saved.setText(
                        f"Space Saved: {mb / 1024:.2f} GB" if mb > 1024 else f"Space Saved: {mb:.1f} MB"
                    )
                    self._add_log(f"DONE: {disp_src} | Saved {saved // (1024 * 1024)} MB")
                    debug(
                        UTILITY_MASS_AV1_ENCODER,
                        f"Done: {disp_src} -> {os.path.basename(local_out)}, saved {saved // (1024 * 1024)} MB",
                    )
                except Exception:
                    pass
            if self._chk_del1.isChecked() and self._chk_del2.isChecked():
                if remote_ref:
                    try:
                        remote_unlink(remote_ref.target, remote_ref.abs_posix, self._encode_pw)
                        self._add_log(f"Deleted remote: {posixpath.basename(remote_ref.rel_posix)}")
                        debug(
                            UTILITY_MASS_AV1_ENCODER,
                            f"Deleted remote source: {remote_ref.abs_posix}",
                        )
                    except Exception as e:
                        self._add_log(f"Remote delete error: {e}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Remote delete error: {e}")
                elif local_in and os.path.isfile(local_in):
                    try:
                        os.remove(local_in)
                        self._add_log(f"Deleted: {os.path.basename(local_in)}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Deleted source: {local_in}")
                    except Exception as e:
                        self._add_log(f"Delete error: {e}")
                        debug(UTILITY_MASS_AV1_ENCODER, f"Delete error: {local_in} — {e}")
        elif not success:
            self._add_log(f"FAILED: {disp_src}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encode FAILED: {lk or local_in or '?'}")

        for tmp in tmp_cleanup:
            try:
                if tmp and os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass

        f_size = self._queue_sizes.get(lk, 0.0)
        self._done_bytes += f_size
        self._done_count += 1

        # Update master bar + ETA on every file completion (progress may never fire for short encodes)
        if self._total_q_bytes > 0 and self._is_encoding:
            pct_total = min(100.0, self._done_bytes / self._total_q_bytes * 100)
            self._bar_master.setValue(int(pct_total))
            self._bar_master.setFormat(f"{self._done_count}/{self._total_count} Files — {pct_total:.1f}%")
            elapsed = time.time() - self._batch_start
            remaining_bytes = self._total_q_bytes - self._done_bytes
            if remaining_bytes > 0 and elapsed > 0.5 and self._done_bytes > 0:
                rate = self._done_bytes / elapsed
                eta_sec = remaining_bytes / rate
                eh = int(eta_sec // 3600)
                em = int((eta_sec % 3600) // 60)
                es = int(eta_sec % 60)
                self._lbl_eta.setText(f"ESTIMATED TIME REMAINING: {eh:02}:{em:02}:{es:02}")
            elif pct_total >= 99.9:
                self._lbl_eta.setText("ESTIMATED TIME REMAINING: 00:00:00")

        if job_id < len(self._job_bars):
            self._job_bars[job_id].setValue(0)
            self._job_speeds[job_id].setText("-")
            self._job_labels[job_id].setText(f"Thread {job_id + 1}")
            self._job_vid[job_id].setText("-")
            self._job_aud[job_id].setText("-")

        if self._done_count >= self._total_count and self._is_encoding:
            self._finalize_batch_complete()

    def _on_batch_complete(self):
        """Called when last worker exits and queue is empty; ensures UI transitions even if finished-signal order lags."""
        if self._is_encoding:
            self._finalize_batch_complete()

    def _finalize_batch_complete(self):
        """Transition UI to encoding-complete state (idempotent)."""
        if not self._is_encoding:
            return
        self._is_encoding = False
        self._encode_pw = None
        self._remote_dst_remote = None
        self._remote_dst_root_posix = None
        self._remote_src_structure_root_posix = None
        self._encode_pipeline_q = None
        self._pipeline_prefetch_thread = None
        if self._fs_heavy_held:
            release_fs_heavy()
            self._fs_heavy_held = False
        if self._status_cb:
            self._status_cb("idle")
        self._bar_master.setRange(0, 1)
        self._bar_master.setValue(0)
        self._bar_master.setFormat("0/0 Files")
        self._lbl_eta.setText("ESTIMATED TIME REMAINING: --:--:--")
        self._lbl_io.setText("I/O: 0.0 MB/s")
        self._btn_start.setStyleSheet("")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setText("ENCODING COMPLETE")
        self._btn_start.setEnabled(False)
        self._btn_pause.setEnabled(False)
        debug(UTILITY_MASS_AV1_ENCODER, f"Encoding batch complete: done={self._done_count}, total={self._total_count}")
        structured_event(
            "encode_batch_complete",
            done=self._done_count,
            total=self._total_count,
        )
        if self._settings.get("shutdown_on_finish"):
            try:
                if platform.system() == "Windows":
                    subprocess.run(["shutdown", "/s", "/t", "0"], check=False, timeout=5)
                else:
                    subprocess.run(["shutdown", "-h", "now"], check=False, timeout=5)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                debug(UTILITY_MASS_AV1_ENCODER, f"Shutdown failed: {e}")

    # ── telemetry ─────────────────────────────────────────────────────────────

    def _sweep_chrono_encoder_tempdir(self) -> None:
        """Remove leftover ``chronoarchiver_av1_*`` files under the system temp dir (STOP / safety net)."""
        td = tempfile.gettempdir()
        n = 0
        try:
            for name in os.listdir(td):
                if not name.startswith(_ENCODER_TMP_PREFIX):
                    continue
                p = os.path.join(td, name)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                        n += 1
                    except OSError:
                        pass
        except OSError:
            pass
        if n:
            debug(UTILITY_MASS_AV1_ENCODER, f"Swept {n} chronoarchiver_av1_* temp file(s) under {td!r}")

    def shutdown_ffmpeg_on_quit(self):
        """Terminate encoder subprocess trees on application exit (avoid orphan FFmpeg)."""
        try:
            self._is_encoding = False
            for eng in getattr(self, "_engine_pool", None) or []:
                eng.cancel()
            self._sweep_chrono_encoder_tempdir()
        finally:
            if self._fs_heavy_held:
                release_fs_heavy()
                self._fs_heavy_held = False

    def _poll_telemetry(self):
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            self._gpu_counter += 1
            if self._gpu_counter >= 3:
                self._gpu_cache = self._get_gpu()
                self._gpu_counter = 0
            if self._metrics_cb:
                cpu_s = f"{min(999, int(round(cpu))):3d}%"
                ram_s = f"{min(999, int(round(ram))):3d}%"
                self._metrics_cb(cpu_s, self._gpu_cache, ram_s)

            if self._is_encoding and self._batch_start > 0:
                dt = time.time() - self._batch_start
                h = int(dt // 3600)
                m = int((dt % 3600) // 60)
                s = int(dt % 60)
                self._lbl_time.setText(f"Time: {h:02}:{m:02}:{s:02}")
                # Keep I/O throughput updated (progress callbacks may be sparse)
                active_bytes = sum(
                    (self._job_progress.get(jid, 0) / 100) * self._queue_sizes.get(self._current_files.get(jid), 0)
                    for jid in self._current_files
                )
                total_written = self._done_bytes + active_bytes
                if dt > 0.5 and total_written > 0:
                    rate_mbs = (total_written / (1024 * 1024)) / dt
                    self._lbl_io.setText(f"I/O: {rate_mbs:.1f} MB/s")
        except Exception:
            pass

    def _get_gpu(self) -> str:
        try:
            return footer_nvidia_gpu_utilization_text()
        except Exception:
            return "  N/A"

    def _add_log(self, msg):
        if not isinstance(msg, str):
            msg = str(msg)
        if len(msg) > _ENCODER_LOG_LINE_MAX:
            msg = msg[: _ENCODER_LOG_LINE_MAX - 3] + "..."
        sb = self._log_edit.verticalScrollBar()
        at_bot = sb.value() >= sb.maximum() - 4
        self._log_edit.appendPlainText(msg)
        if at_bot:
            sb.setValue(sb.maximum())
        if self._log_cb:
            self._log_cb(msg)
