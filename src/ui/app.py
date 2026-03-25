"""
ChronoArchiver — App-private venv (all Python deps internalized).
Uses a QStackedWidget to manage distinct application panels.
"""

import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import re

import psutil

# Add app root and app-private venv to path (v3.0: all Python deps in venv)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.venv_manager import (
    add_venv_to_path, add_ffmpeg_to_path,
    check_opencv_in_venv, check_ffmpeg_in_venv, ensure_bundled_ffmpeg,
    get_pip_exe, _is_frozen,
)
add_venv_to_path()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QMessageBox, QProgressBar,
    QDialog, QTextEdit, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QCoreApplication
from PySide6.QtGui import QIcon, QFontDatabase

from version import __version__
from ui.panels.organizer_panel import MediaOrganizerPanel
from ui.panels.encoder_panel import AV1EncoderPanel
from ui.panels.scanner_panel import AIScannerPanel
from core.updater import ApplicationUpdater
from core.subprocess_tee import (
    set_subprocess_tee_callback,
    set_subprocess_channel,
    win_hide_kw,
)
from core.debug_logger import init_log, get_log_path, debug, UTILITY_APP
from core.app_paths import (
    APP_NAME,
    APP_AUTHOR,
    install_root,
    uses_install_layout,
    settings_dir as _app_settings_dir,
    remove_empty_windows_legacy_config_nest,
)
from core.logger import setup_logger

# Font stack: Inter if bundled, else Windows-native for readability
_FONT_SANS = "'Inter', 'Segoe UI', 'Lucida Grande', sans-serif" if platform.system() == "Windows" else "'Inter', 'Ubuntu', sans-serif"
_FONT_MONO = "'JetBrains Mono', 'Consolas', 'Cascadia Code', monospace" if platform.system() == "Windows" else "'JetBrains Mono', 'DejaVu Sans Mono', monospace"

# Global Stylesheet (Mass AV1 Encoder QSS)
# Use .format() to avoid f-string parsing CSS braces as Python expressions (NameError on Windows)
QSS = """
QMainWindow {{ background-color: #0c0c0c; }}
QWidget {{ color: #e5e7eb; font-family: {0}; }}

QGroupBox {{
    border: 1px solid #1a1a1a;
    border-radius: 4px;
    margin-top: 10px;
    font-size: 8px;
    font-weight: 800;
    color: #4b5563;
    text-transform: uppercase;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; }}

QLineEdit {{
    background-color: #121212;
    border: 1px solid #1a1a1a;
    border-radius: 3px;
    padding: 2px 6px;
    color: #fff;
    font-size: 11px;
}}
QLineEdit:focus {{ border: 1px solid #3b82f6; }}

QCheckBox {{
    font-size: 9px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 3px;
}}
QCheckBox::indicator:unchecked {{
    background-color: #1f2937;
    border: 1px solid #4b5563;
}}
QCheckBox::indicator:checked {{
    background-color: #0f766e;
    border: 1px solid #5eead4;
}}
QCheckBox::indicator:hover:unchecked {{
    border: 1px solid #6b7280;
}}
QCheckBox::indicator:hover:checked {{
    background-color: #0d9488;
    border: 1px solid #99f6e4;
}}

QPushButton {{
    background-color: #1a1a1a;
    border: 1px solid #262626;
    border-radius: 4px;
    color: #9ca3af;
    font-size: 9px;
    font-weight: 700;
    padding: 4px 8px;
}}
QPushButton:hover {{ background-color: #262626; color: #fff; }}
QPushButton:pressed {{ background-color: #121212; }}

QPushButton#btnStart {{
    background-color: #10b981;
    color: #064e3b;
    border: none;
    font-size: 10px;
    font-weight: 900;
}}
QPushButton#btnStart:hover {{ background-color: #34d399; }}
QPushButton#btnStart:disabled {{
    background-color: #1a1a1a;
    color: #6b7280;
    border: 1px solid #262626;
}}

QPushButton#btnStop {{
    background-color: #ef4444;
    color: #450a0a;
    border: none;
}}
QPushButton#btnStop:disabled {{
    background-color: #1a1a1a;
    color: #6b7280;
    border: 1px solid #262626;
}}

QProgressBar {{
    background-color: #121212;
    border: 1px solid #1a1a1a;
    border-radius: 2px;
    text-align: center;
    font-size: 8px;
    font-weight: 800;
    color: #fff;
}}
QProgressBar::chunk {{ background-color: #3b82f6; width: 1px; }}
QProgressBar#masterBar::chunk {{ background-color: #10b981; }}

QListWidget, QTextEdit {{
    background-color: #080808;
    border: 1px solid #141414;
    font-family: {1};
    font-size: 9px;
    color: #e5e7eb;
}}

QScrollBar:vertical {{
    border: none;
    background: #0c0c0c;
    width: 4px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{ background: #1f2937; min-height: 20px; border-radius: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

/* Custom Nav Buttons */
QPushButton#navBtn {{
    text-align: left;
    padding-left: 12px;
    height: 28px;
    font-size: 9px;
    border: none;
    border-radius: 0px;
    background: transparent;
    color: #6b7280;
}}
QPushButton#navBtn:hover {{ background: #111111; color: #fff; }}
QPushButton#navBtn[active="true"] {{
    background: #1a1a1a;
    color: #3b82f6;
    border-left: 2px solid #3b82f6;
}}
""".format(_FONT_SANS, _FONT_MONO)


def _load_bundled_fonts():
    """Register bundled Inter font for consistent rendering on all platforms."""
    _base = os.path.join(os.path.dirname(__file__), "assets", "fonts")
    for name in ("Inter-Regular.ttf",):
        path = os.path.join(_base, name)
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)


class DonateNavWidget(QWidget):
    """Header donate link: only the heart blinks red and is slightly larger than the label text."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._heart = QLabel("\u2665")
        self._heart.setStyleSheet(
            "font-size: 11px; color: #b91c1c; background: transparent; border: none; padding: 0;")
        self._heart.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._lbl = QLabel("Support Developer!")
        self._lbl.setStyleSheet(
            "font-size: 9px; color: #6b7280; background: transparent; border: none;")
        self._lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h.addWidget(self._heart, 0, Qt.AlignVCenter)
        h.addWidget(self._lbl, 0, Qt.AlignVCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Support development via PayPal ($5 USD)")
        self._beat_wait_ms = 5000
        self._beat_flash_ms = 180
        self._beat_gap_ms = 130  # dim gap between the two fast beats
        self._start_heartbeat_cycle()

    def _set_heart_color(self, bright: bool):
        c = "#ef4444" if bright else "#b91c1c"
        self._heart.setStyleSheet(
            f"font-size: 11px; color: {c}; background: transparent; border: none; padding: 0;")

    def _start_heartbeat_cycle(self):
        # Two fast beats.
        self._set_heart_color(True)
        QTimer.singleShot(self._beat_flash_ms, lambda: self._set_heart_color(False))
        QTimer.singleShot(self._beat_flash_ms + self._beat_gap_ms, self._second_beat)

    def _second_beat(self):
        self._set_heart_color(True)
        QTimer.singleShot(self._beat_flash_ms, lambda: self._set_heart_color(False))
        # Rest 5 seconds (from when the second beat starts).
        QTimer.singleShot(self._beat_flash_ms + self._beat_wait_ms, self._start_heartbeat_cycle)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PreReqDialog(QDialog):
    """Popup to download prerequisites (FFmpeg). User clicks Download to start."""
    download_complete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prerequisites")
        self.setModal(False)
        self.setFixedSize(420, 200)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl_intro = QLabel("Some components need to be downloaded before encoding/organizing.")
        self._lbl_intro.setStyleSheet("font-size: 10px; color: #9ca3af;")
        self._lbl_intro.setWordWrap(True)
        v.addWidget(self._lbl_intro)
        h_ffmpeg = QHBoxLayout()
        self._lbl_ffmpeg = QLabel("FFmpeg:")
        self._lbl_ffmpeg.setStyleSheet("font-size: 10px; font-weight: 600; color: #e5e7eb; min-width: 70px;")
        h_ffmpeg.addWidget(self._lbl_ffmpeg)
        self._lbl_ffmpeg_status = QLabel("Not installed")
        self._lbl_ffmpeg_status.setStyleSheet("font-size: 10px; color: #ef4444;")
        h_ffmpeg.addWidget(self._lbl_ffmpeg_status, 1)
        self._btn_download = QPushButton("Download")
        self._btn_download.setStyleSheet("font-size: 9px; font-weight: 700; padding: 4px 12px;")
        self._btn_download.clicked.connect(self._on_download)
        h_ffmpeg.addWidget(self._btn_download)
        v.addLayout(h_ffmpeg)
        self._lbl_phase = QLabel("")
        self._lbl_phase.setStyleSheet("font-size: 10px; font-weight: 600; color: #10b981;")
        v.addWidget(self._lbl_phase)
        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("font-size: 9px; color: #6b7280;")
        v.addWidget(self._lbl_detail)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(14)
        self._bar.setFormat("%p%")
        self._bar.hide()
        v.addWidget(self._bar)
        v.addStretch()
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self._downloading = False

    def _on_download(self):
        if self._downloading:
            return
        self._downloading = True
        self._btn_download.setEnabled(False)
        self._lbl_phase.setText("Preparing...")
        self._lbl_phase.show()
        self._lbl_detail.show()
        self._bar.show()
        self._bar.setValue(0)
        ffmpeg_queue = queue.Queue()
        _last_debug_t = [0.0]
        _last_phase = [None]
        _last_pct_bucket = [-1]

        def _on_progress(phase: str, pct: int, detail: str):
            try:
                ffmpeg_queue.put_nowait((phase, pct, detail))
            except queue.Full:
                pass

        def _poll():
            try:
                while True:
                    phase, pct, detail = ffmpeg_queue.get_nowait()
                    self._lbl_phase.setText(phase.replace("downloading", "Downloading").replace("extracting", "Extracting"))
                    self._bar.setValue(min(100, pct))
                    self._bar.setFormat("%p%")
                    self._lbl_detail.setText(detail[:120] if detail else "")

                    # Capture popup installer phases/progress into the main debug log.
                    now = time.monotonic()
                    pct_bucket = (pct // 10) if pct is not None else -1
                    should_log = (
                        phase != _last_phase[0]
                        or phase == "done"
                        or ("failed" in (phase or "").lower())
                        or (pct_bucket != _last_pct_bucket[0] and pct is not None)
                        or (now - _last_debug_t[0] >= 5.0)
                    )
                    if should_log:
                        _last_phase[0] = phase
                        _last_pct_bucket[0] = pct_bucket
                        _last_debug_t[0] = now
                        d_s = (detail or "").replace("\n", " ")[:140]
                        debug(UTILITY_APP, f"FFmpeg popup: phase={phase!r} pct={pct}% detail={d_s}")

                    if phase == "done":
                        timer.stop()
                        self._btn_download.setEnabled(True)
                        self._btn_download.hide()
                        self._lbl_ffmpeg_status.setText("Ready")
                        self._lbl_ffmpeg_status.setStyleSheet("font-size: 10px; color: #10b981;")
                        self._lbl_phase.hide()
                        self._lbl_detail.hide()
                        self._bar.hide()
                        self.download_complete.emit()
                        return
            except queue.Empty:
                pass

        def _worker():
            ok = ensure_bundled_ffmpeg(_on_progress)
            if not ok:
                self._lbl_ffmpeg_status.setText("Failed")
                self._lbl_phase.setText("Install failed. Check debug log.")
                self._btn_download.setEnabled(True)
            if not self._downloading:
                return
            _on_progress("done", 100, "")

        timer = QTimer(self)
        timer.timeout.connect(_poll)
        timer.start(80)
        threading.Thread(target=_worker, daemon=True).start()


class UpdateDownloadDialog(QDialog):
    """FFmpeg-style popup: download installer with file name, size, progress bar, MB/s."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updating ChronoArchiver")
        self.setModal(True)
        self.setFixedSize(460, 220)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(12, 12, 12, 12)
        self._lbl_intro = QLabel("Downloading update...")
        self._lbl_intro.setStyleSheet("font-size: 10px; color: #9ca3af;")
        self._lbl_intro.setWordWrap(True)
        v.addWidget(self._lbl_intro)
        self._lbl_file = QLabel("")
        self._lbl_file.setStyleSheet("font-size: 10px; font-weight: 600; color: #e5e7eb;")
        v.addWidget(self._lbl_file)
        self._lbl_size = QLabel("")
        self._lbl_size.setStyleSheet("font-size: 9px; color: #6b7280;")
        v.addWidget(self._lbl_size)
        self._lbl_speed = QLabel("")
        self._lbl_speed.setStyleSheet("font-size: 9px; color: #10b981;")
        v.addWidget(self._lbl_speed)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(14)
        self._bar.setFormat("%p%")
        v.addWidget(self._bar)
        v.addStretch()
        self.setStyleSheet("QDialog { background: #0d0d0d; }")
        self._progress_queue = queue.Queue()
        self._dest_path = None
        self._download_ok = False

    def run_download(self, updater, version: str, changelog_text: str) -> bool:
        """
        Fetch asset info, download with progress, then launch installer. Returns True if
        download succeeded and installer was launched (app should quit). False if failed.
        """
        info = updater.get_installer_asset_info(version)
        if not info:
            QMessageBox.warning(self, "Update", "Could not find installer for this platform.")
            return False
        url, size_bytes, filename = info
        size_mb = size_bytes / (1024 * 1024)
        self._lbl_intro.setText(f"Downloading ChronoArchiver v{version}")
        self._lbl_file.setText(f"File: {filename}")
        self._lbl_size.setText(f"Size: {size_mb:.1f} MB total")
        self._lbl_speed.setText("")
        self._bar.setValue(0)

        fd, dest = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
        try:
            os.close(fd)
        except OSError:
            pass
        self._dest_path = dest
        _last_debug_t = [0.0]
        _last_pct_bucket = [-1]

        def _on_progress(downloaded, total, pct, mbps):
            try:
                self._progress_queue.put_nowait((downloaded, total, pct, mbps))
            except queue.Full:
                pass

        def _poll():
            try:
                while True:
                    msg = self._progress_queue.get_nowait()
                    if msg[0] == "done":
                        self._download_ok = bool(msg[1])
                        self._poll_timer.stop()
                        debug(
                            UTILITY_APP,
                            f"Update popup: download_done ok={self._download_ok} version={version}",
                        )
                        if self._download_ok:
                            self.accept()
                        else:
                            QMessageBox.warning(self, "Update", "Download failed.")
                            self.reject()
                        return
                    downloaded, total, pct, mbps = msg
                    self._bar.setValue(min(100, int(pct)))
                    self._bar.setFormat("%p%")
                    self._lbl_speed.setText(f"{mbps:.2f} MB/s" if mbps and mbps > 0 else "")

                    now = time.monotonic()
                    pct_bucket = int(pct) // 10
                    if (
                        pct_bucket != _last_pct_bucket[0]
                        or now - _last_debug_t[0] >= 5.0
                        or int(pct) in (0, 100)
                    ):
                        _last_pct_bucket[0] = pct_bucket
                        _last_debug_t[0] = now
                        debug(
                            UTILITY_APP,
                            f"Update popup: downloaded={downloaded}B total={total}B pct={int(pct)}% speed={(mbps or 0):.2f}MB/s",
                        )
            except queue.Empty:
                pass

        def _worker():
            ok = updater.download_installer_with_progress(
                url, dest, size_bytes, _on_progress
            )
            try:
                self._progress_queue.put_nowait(("done", ok, None, None))
            except queue.Full:
                pass

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(_poll)
        self._poll_timer.start(80)
        threading.Thread(target=_worker, daemon=True).start()

        result = self.exec()
        self._poll_timer.stop()
        if result != QDialog.DialogCode.Accepted or not self._download_ok:
            try:
                if self._dest_path and os.path.isfile(self._dest_path):
                    os.unlink(self._dest_path)
            except OSError:
                pass
            return False
        return True


class ChronoArchiverApp(QMainWindow):
    def __init__(self):
        super().__init__()
        init_log()
        self.setWindowTitle(f"ChronoArchiver v{__version__}")
        self.setFixedSize(940, 680)
        self.setStyleSheet(QSS)
        _icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
        if os.path.isfile(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        self.logger = setup_logger()
        self.updater = ApplicationUpdater()
        self._update_result_queue = queue.Queue()
        self._update_poll_timer = None
        self._component_sync_started = False
        self._metrics_gpu_cache = "  N/A"
        self._metrics_gpu_counter = 0
        self._metrics_gpu_last_err_t = 0.0
        self._metrics_gpu_last_err = ""

        # UI Components
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── NAVIGATION BAR ──
        self.nav_bar = QFrame()
        self.nav_bar.setFixedHeight(38)
        self.nav_bar.setStyleSheet("background: #080808; border-bottom: 1px solid #141414;")
        self.nav_layout = QHBoxLayout(self.nav_bar)
        self.nav_layout.setContentsMargins(10, 0, 10, 0)
        self.nav_layout.setSpacing(2)

        self.lbl_brand = QLabel("CHRONO ARCHIVER /")
        self.lbl_brand.setStyleSheet("font-weight: 900; font-size: 10px; color: #3b82f6; margin-right: 10px;")
        self.nav_layout.addWidget(self.lbl_brand)

        self.btn_org = self._create_nav_btn("MEDIA ORGANIZER", 0)
        self.btn_enc = self._create_nav_btn("MASS AV1 ENCODER", 1)
        self.btn_scn = self._create_nav_btn("AI MEDIA SCANNER", 2)
        
        self.nav_btns = [self.btn_org, self.btn_enc, self.btn_scn]
        
        self.nav_layout.addStretch()

        self.btn_update = QPushButton("CHECKING FOR UPDATES...")
        self.btn_update.setStyleSheet("font-size: 9px; color: #4b5563; border:none; background:transparent;")
        self.btn_update.clicked.connect(self._run_updater)
        self.nav_layout.addWidget(self.btn_update)
        self._update_pulse_timer = QTimer(self)
        self._update_pulse_timer.setInterval(550)
        self._update_pulse_timer.timeout.connect(self._pulse_update_button)
        self._update_pulse_phase = 0

        self._donate_nav = DonateNavWidget()
        self._donate_nav.clicked.connect(self._open_donate)
        self.nav_layout.addWidget(self._donate_nav)

        self.layout.addWidget(self.nav_bar)

        # ── STACKED PANELS ──
        self.stack = QStackedWidget()
        self.panel_org = MediaOrganizerPanel(log_callback=self._log, status_callback=self._set_activity)
        self.panel_enc = AV1EncoderPanel(log_callback=self._log, metrics_callback=self._on_encoder_metrics, status_callback=self._set_activity)
        self.panel_scn = AIScannerPanel(log_callback=self._log, status_callback=self._set_activity)

        self.stack.addWidget(self.panel_org)
        self.stack.addWidget(self.panel_enc)
        self.stack.addWidget(self.panel_scn)
        self.panel_scn._sig.prereqs_changed.connect(self._refresh_footer)

        def _tee_cb(channel: str, line: str):
            QTimer.singleShot(0, lambda: self._route_subprocess_line(channel, line))

        set_subprocess_tee_callback(_tee_cb)

        self.layout.addWidget(self.stack)

        # ── STATUS BAR ──
        # Layout: [Left: activity] [Center: pre-req] [Right: buttons, metrics]
        self.status_bar = QFrame()
        self.status_bar.setFixedHeight(28)
        self.status_bar.setStyleSheet("background: #080808; border-top: 1px solid #141414;")
        self.status_layout = QHBoxLayout(self.status_bar)
        self.status_layout.setContentsMargins(10, 2, 10, 2)

        self.lbl_status = QLabel("CHECKING…")
        self.lbl_status.setStyleSheet("font-size: 9px; color: #4b5563; text-transform: uppercase; min-width: 100px;")
        self.lbl_status.setToolTip("Current activity: Encoding, Organizing, Scanning, etc.")
        self._activity = "idle"
        self._activity_dot = 0
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(400)
        self._activity_timer.timeout.connect(self._animate_activity)
        self._precheck_done = False
        self.status_layout.addWidget(self.lbl_status, 0, Qt.AlignVCenter)
        self._bar_ffmpeg = QProgressBar()
        self._bar_ffmpeg.setFixedSize(72, 13)
        self._bar_ffmpeg.setRange(0, 100)
        self._bar_ffmpeg.setValue(0)
        self._bar_ffmpeg.setFormat("%p%")
        self._bar_ffmpeg.setStyleSheet("font-size: 8px; font-weight: 700;")
        self._bar_ffmpeg.hide()
        self.status_layout.addWidget(self._bar_ffmpeg, 0, Qt.AlignVCenter)
        self._lbl_ffmpeg_speed = QLabel("")
        self._lbl_ffmpeg_speed.setStyleSheet("font-size: 8px; color: #6b7280; min-width: 48px;")
        self._lbl_ffmpeg_speed.hide()
        self.status_layout.addWidget(self._lbl_ffmpeg_speed, 0, Qt.AlignVCenter)
        self.status_layout.addStretch()

        self.lbl_prereq = QLabel("CHECKING…")
        self.lbl_prereq.setStyleSheet("font-size: 8px; color: #6b7280;")
        self.lbl_prereq.setAlignment(Qt.AlignCenter)
        self.status_layout.addWidget(self.lbl_prereq, 0, Qt.AlignVCenter)
        self.status_layout.addStretch()

        self.btn_copy_console = QPushButton("COPY CONSOLE")
        self.btn_copy_console.setStyleSheet("font-size: 8px; color: #eab308; border:none; background:transparent;")
        self.btn_copy_console.setToolTip("Copy current panel console to clipboard")
        self.btn_copy_console.clicked.connect(self._copy_console)
        self.status_layout.addWidget(self.btn_copy_console, 0, Qt.AlignVCenter)

        self.btn_debug = QPushButton("DEBUG")
        self.btn_debug.setStyleSheet("font-size: 8px; color: #ef4444; border:none; background:transparent;")
        self.btn_debug.setToolTip(f"Open debug log folder\n{os.path.dirname(get_log_path())}")
        self.btn_debug.clicked.connect(self._open_debug_folder)
        self.status_layout.addWidget(self.btn_debug, 0, Qt.AlignVCenter)

        self.lbl_metrics = QLabel("CPU   0% · GPU   0% · RAM   0%")
        self.lbl_metrics.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_metrics.setStyleSheet(
            "font-size: 9px; color: #f59e0b; font-weight: 600; "
            "font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; "
            "min-width: 155px;")
        self.lbl_metrics.setTextFormat(Qt.RichText)
        self.status_layout.addWidget(self.lbl_metrics, 0, Qt.AlignVCenter)

        self.layout.addWidget(self.status_bar)

        # Init
        self._switch_panel(0)
        debug(UTILITY_APP, f"Application started v{__version__}")
        QTimer.singleShot(100, self._check_prereqs)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._poll_metrics)
        self._metrics_timer.start(2000)
        QTimer.singleShot(2000, self._run_updater)

    def _create_nav_btn(self, text, index):
        btn = QPushButton(text)
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self._switch_panel(index))
        self.nav_layout.addWidget(btn)
        return btn

    def _switch_panel(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_btns):
            btn.setProperty("active", i == index)
            btn.setChecked(i == index)
            btn.setStyle(btn.style())  # Refresh style
        self.lbl_metrics.setVisible(True)
        panels = ["Media Organizer", "Mass AV1 Encoder", "AI Media Scanner"]
        debug(UTILITY_APP, f"Panel switch: {panels[index]}")
        panel = self.stack.currentWidget()
        if hasattr(panel, "get_activity"):
            self._set_activity(panel.get_activity())

    def _set_activity(self, activity: str):
        """Activity: 'idle' | 'encoding' | 'organizing' | 'scanning'. Footer left reflects app state."""
        self._activity = activity or "idle"
        if self._activity in ("encoding", "organizing", "scanning"):
            self._activity_dot = 0
            self._activity_timer.start()
            self._animate_activity()
        elif self._precheck_done:
            self._activity_timer.stop()
            self.lbl_status.setText("IDLE")

    def _animate_activity(self):
        if self._activity == "idle":
            self._activity_timer.stop()
            self.lbl_status.setText("IDLE")
            return
        base = {"encoding": "ENCODING", "organizing": "ORGANIZING", "scanning": "SCANNING"}.get(self._activity, "IDLE")
        dots = "." * (self._activity_dot % 3 + 1)
        self.lbl_status.setText(f"{base}{dots}")
        self._activity_dot += 1

    def _log(self, msg):
        self.logger.info(msg)

    def _check_prereqs(self):
        """Run pre-req checks (order matches footer): PySide6, FFmpeg, OpenCV, AI models, then footer + idle."""
        def step_opencv():
            self.lbl_status.setText("CHECKING OPENCV…")
            QTimer.singleShot(400, step_models)

        def step_models():
            self.lbl_status.setText("CHECKING AI MODELS…")
            QTimer.singleShot(400, step_finalize)

        def step_finalize():
            self._refresh_footer()
            self.lbl_status.setText("PRE-CHECK COMPLETE")
            self._precheck_done = True
            if hasattr(self, "panel_scn") and hasattr(self.panel_scn, "_check_models"):
                self.panel_scn._check_models()  # Deferred from init — was blocking main thread during FFmpeg install
            QTimer.singleShot(3000, _go_idle)

        def _go_idle():
            if self._activity == "idle":
                self.lbl_status.setText("IDLE")
            self._activity_timer.stop()

        def step_ffmpeg():
            self.lbl_status.setText("CHECKING FFMPEG…")
            QTimer.singleShot(200, _do_ffmpeg_check)

        def step_after_pyside():
            step_ffmpeg()

        def _finish_ffmpeg(ok: bool):
            if ok and check_ffmpeg_in_venv():
                add_ffmpeg_to_path()
                debug(UTILITY_APP, "Pre-reqs: FFmpeg=ok (venv)" if not _is_frozen() else "Pre-reqs: FFmpeg=ok (bundled)")
                step_opencv()
                return
            if get_pip_exe().exists() or _is_frozen():
                step_opencv()
                self._prereq_dlg = PreReqDialog(self)
                self._prereq_dlg.download_complete.connect(lambda: (add_ffmpeg_to_path(), self._refresh_footer()))
                self._prereq_dlg.show()
                return
            ffmpeg_ok = bool(shutil.which("ffmpeg"))
            debug(UTILITY_APP, f"Pre-reqs: FFmpeg={'ok' if ffmpeg_ok else 'missing'} (no venv)")
            step_opencv()

        def _do_ffmpeg_check():
            pip = get_pip_exe()
            frozen = _is_frozen()
            if not (pip.exists() or frozen):
                ffmpeg_ok = bool(shutil.which("ffmpeg"))
                debug(UTILITY_APP, f"Pre-reqs: FFmpeg={'ok' if ffmpeg_ok else 'missing'} (no venv)")
                step_opencv()
                return
            ff_q = queue.Queue()

            def _footer_cb(phase: str, pct: int, detail: str):
                try:
                    ff_q.put_nowait(("progress", phase, pct, detail))
                except queue.Full:
                    pass

            def _poll_ff():
                try:
                    while True:
                        item = ff_q.get_nowait()
                        if item[0] == "done":
                            ok = item[1]
                            _ff_timer.stop()
                            _finish_ffmpeg(ok)
                            return
                        _, phase, pct, detail = item
                        self.lbl_status.setText(f"FFMPEG {phase.upper()} {pct}% {detail[:40]}".strip())
                except queue.Empty:
                    pass

            def _worker():
                try:
                    set_subprocess_channel("organizer")
                    ok = bool(ensure_bundled_ffmpeg(_footer_cb))
                except Exception:
                    ok = False
                try:
                    ff_q.put_nowait(("done", ok))
                except queue.Full:
                    pass

            _ff_timer = QTimer(self)
            _ff_timer.timeout.connect(_poll_ff)
            _ff_timer.start(80)
            threading.Thread(target=_worker, daemon=True).start()

        def step_pyside():
            self.lbl_status.setText("CHECKING PYSIDE6…")
            QTimer.singleShot(250, step_after_pyside)

        step_pyside()

    def _refresh_footer(self):
        """Update footer pre-req status: PySide6, FFmpeg, OpenCV, AI models, READY."""
        ok_sym = '<span style="color:#10b981">✓</span>'
        fail_sym = '<span style="color:#ef4444">✗</span>'
        skip_sym = '<span style="color:#eab308">—</span>'

        def _apply(opencv_ok: bool):
            ffmpeg_ok = bool(check_ffmpeg_in_venv() or shutil.which("ffmpeg"))
            models_ready = self.panel_scn._model_mgr.is_up_to_date()
            parts = [
                f"PYSIDE6 {ok_sym}",
                f"FFMPEG {ok_sym if ffmpeg_ok else fail_sym}",
                f"OPENCV {ok_sym if opencv_ok else skip_sym}",
                f"AI MODELS {ok_sym if models_ready else skip_sym}",
            ]
            debug(UTILITY_APP, f"Pre-reqs: FFmpeg={'ok' if ffmpeg_ok else 'missing'}, OpenCV={'ok' if opencv_ok else 'missing'}, AI Models={'ok' if models_ready else 'missing'}, PySide6=ok")
            status = "  ·  ".join(parts)
            if ffmpeg_ok:
                status += "  ·  <span style=\"color:#10b981\">READY</span>"
            self.lbl_prereq.setTextFormat(Qt.RichText)
            self.lbl_prereq.setText(status)

        if get_pip_exe().exists():
            footer_queue = queue.Queue()

            def _task():
                ov = check_opencv_in_venv()
                try:
                    footer_queue.put_nowait(ov)
                except queue.Full:
                    pass

            def _poll():
                try:
                    ov = footer_queue.get_nowait()
                    if getattr(self, "_footer_poll_timer", None):
                        self._footer_poll_timer.stop()
                        self._footer_poll_timer = None
                    _apply(ov)
                except queue.Empty:
                    pass

            self._footer_poll_timer = QTimer(self)
            self._footer_poll_timer.timeout.connect(_poll)
            self._footer_poll_timer.start(80)
            threading.Thread(target=_task, daemon=True).start()
        else:
            try:
                from core.scanner import OPENCV_AVAILABLE
                opencv_ok = bool(OPENCV_AVAILABLE)
            except Exception:
                opencv_ok = False
            _apply(opencv_ok)

    def _route_subprocess_line(self, channel: str, line: str):
        """Tee venv pip/ffmpeg lines to Organizer or Scanner console."""
        text = f"[{channel}] {line}" if channel else line
        if channel == "scanner":
            self.panel_scn.append_external_line(text)
        else:
            self.panel_org.append_external_line(text)

    def _copy_console(self):
        panel = self.stack.currentWidget()
        if hasattr(panel, "_log_edit"):
            text = panel._log_edit.toPlainText()
        elif hasattr(panel, "_log_list"):
            lines = [panel._log_list.item(i).text() for i in range(panel._log_list.count())]
            text = "\n".join(lines)
        else:
            text = ""
        QApplication.clipboard().setText(text)

    def _open_debug_folder(self):
        folder = os.path.dirname(get_log_path())
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        try:
            if platform.system() == "Windows":
                os.startfile(folder)
            elif platform.system() == "Darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception:
            pass

    def _poll_metrics(self):
        """App-level metrics for footer (CPU, GPU, RAM) — shown on all panels."""
        try:
            cpu_val = psutil.cpu_percent()
            ram_val = psutil.virtual_memory().percent
            self._metrics_gpu_counter += 1
            if self._metrics_gpu_counter >= 3:
                try:
                    smi = shutil.which("nvidia-smi")
                    if not smi:
                        raise FileNotFoundError("nvidia-smi not found in PATH")
                    proc = subprocess.run(
                        [smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        **win_hide_kw(),
                    )
                    out = (proc.stdout or "").strip()
                    err = (proc.stderr or "").strip()
                    if proc.returncode != 0:
                        raise RuntimeError(f"nvidia-smi rc={proc.returncode} stderr={err[:220]}")
                    # Some environments may output multiple lines (multiple GPUs). Take max.
                    vals = [int(x) for x in re.findall(r"\d+", out or "")]
                    if not vals:
                        raise ValueError(f"Unexpected nvidia-smi output: {out[:80]}")
                    g = max(vals)
                    self._metrics_gpu_cache = f"{min(999, g):3d}%"
                except Exception as e:
                    # If NVML/nvidia-smi can't provide utilization, try a Windows-wide
                    # vendor-agnostic performance counter fallback. Otherwise show N/A.
                    now = time.monotonic()
                    msg = str(e)[:140]
                    if (now - self._metrics_gpu_last_err_t) >= 20.0 or msg != self._metrics_gpu_last_err:
                        self._metrics_gpu_last_err_t = now
                        self._metrics_gpu_last_err = msg
                        debug(UTILITY_APP, f"GPU metrics: nvidia-smi query failed: {msg}")

                    g_win: int | None = None
                    if platform.system() == "Windows":
                        try:
                            ps_cmd = (
                                r"$c=Get-Counter '\GPU Engine(*)\Utilization Percentage'; "
                                r"$vals=$c.CounterSamples | ForEach-Object {$_.CookedValue}; "
                                r"$max=($vals | Measure-Object -Maximum).Maximum; "
                                r"if($max -ne $null){Write-Output $max}"
                            )
                            proc = subprocess.run(
                                ["powershell", "-NoProfile", "-Command", ps_cmd],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=2.5,
                                **win_hide_kw(),
                            )
                            stdout = (proc.stdout or "").strip()
                            vals = [int(x) for x in re.findall(r"\d+", stdout or "")]
                            if vals:
                                g_win = max(vals)
                        except Exception:
                            g_win = None

                    self._metrics_gpu_cache = f"{min(999, g_win):3d}%" if g_win is not None else "  N/A"
                self._metrics_gpu_counter = 0
            cpu_s = f"{min(999, int(round(cpu_val))):3d}%"
            ram_s = f"{min(999, int(round(ram_val))):3d}%"
            teal = "#94e2d5"
            orange_dot = "#f59e0b"
            white = "#f8f8f2"
            dot = f'<span style="color:{orange_dot}; font-weight:700;">·</span>'
            self.lbl_metrics.setText(
                f'<span style="color:{teal}; font-weight:700;">CPU</span> '
                f'<span style="color:{white}; font-weight:700;">{cpu_s}</span> {dot} '
                f'<span style="color:{teal}; font-weight:700;">GPU</span> '
                f'<span style="color:{white}; font-weight:700;">{self._metrics_gpu_cache}</span> {dot} '
                f'<span style="color:{teal}; font-weight:700;">RAM</span> '
                f'<span style="color:{white}; font-weight:700;">{ram_s}</span>'
            )
        except Exception:
            pass

    def _on_encoder_metrics(self, cpu, gpu, ram):
        """Encoder panel can override with its own (includes encoding Time)."""
        teal = "#94e2d5"
        orange_dot = "#f59e0b"
        white = "#f8f8f2"
        dot = f'<span style="color:{orange_dot}; font-weight:700;">·</span>'
        self.lbl_metrics.setText(
            f'<span style="color:{teal}; font-weight:700;">CPU</span> '
            f'<span style="color:{white}; font-weight:700;">{cpu}</span> {dot} '
            f'<span style="color:{teal}; font-weight:700;">GPU</span> '
            f'<span style="color:{white}; font-weight:700;">{gpu}</span> {dot} '
            f'<span style="color:{teal}; font-weight:700;">RAM</span> '
            f'<span style="color:{white}; font-weight:700;">{ram}</span>'
        )

    def _open_donate(self):
        try:
            url = "https://www.paypal.com/donate?business=jscheema%40gmail.com&amount=5&currency_code=USD&locale.x=en_US"
            webbrowser.open(url)
        except Exception:
            pass

    def _run_updater(self):
        # If update available and user clicks, perform update
        if self.updater.is_update_available():
            self._confirm_and_perform_update()
            return
        self._update_pulse_timer.stop()
        self.btn_update.setText("CHECKING...")
        self._update_result_queue = queue.Queue()
        self.updater.check_for_updates(self._update_result_queue)
        self._start_update_poll()

    def _start_update_poll(self):
        if self._update_poll_timer and self._update_poll_timer.isActive():
            return
        self._update_poll_timer = QTimer(self)
        self._update_poll_timer.timeout.connect(self._poll_update_result)
        self._update_poll_timer.start(150)

    def _poll_update_result(self):
        try:
            latest, changelog = self._update_result_queue.get_nowait()
        except queue.Empty:
            return
        self._update_poll_timer.stop()
        self._update_poll_timer = None
        if self.updater.is_update_available():
            self.btn_update.setText(f"UPDATE v{latest} AVAILABLE")
            self._update_pulse_phase = 0
            self._update_pulse_timer.start()
            self._pulse_update_button()
        elif latest is None:
            self._update_pulse_timer.stop()
            self.btn_update.setText("UPDATE CHECK UNAVAILABLE")
            self.btn_update.setStyleSheet("font-size: 9px; color: #4b5563; border:none; background:transparent;")
        else:
            self._update_pulse_timer.stop()
            self.btn_update.setText("CHRONOARCHIVER IS UP TO DATE")
            self.btn_update.setStyleSheet("font-size: 9px; color: #4b5563; border:none; background:transparent;")
        if latest is not None:
            self._maybe_sync_bundled_components_after_online_check()

    def _maybe_sync_bundled_components_after_online_check(self):
        """After GitHub is reachable, refresh bundled FFmpeg if docs/components_manifest.json revision increased."""
        if self._component_sync_started:
            return
        if not uses_install_layout():
            return
        if platform.system() not in ("Windows", "Darwin"):
            return
        self._component_sync_started = True

        def _bg():
            try:
                set_subprocess_channel("organizer")
                ensure_bundled_ffmpeg(None)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _pulse_update_button(self):
        """Flash green text when update available (like guide pulse)."""
        if not self.updater.is_update_available():
            self._update_pulse_timer.stop()
            return
        self._update_pulse_phase = 1 - self._update_pulse_phase
        base = "font-size: 9px; font-weight: bold; border:none; background:transparent;"
        if self._update_pulse_phase:
            self.btn_update.setStyleSheet(f"{base} color: #10b981;")
        else:
            self.btn_update.setStyleSheet(f"{base} color: #4b5563;")

    def _confirm_and_perform_update(self):
        latest = self.updater.get_latest_version()
        method = self.updater.get_install_method()
        if not method:
            r = QMessageBox.question(
                self,
                "Update Available",
                f"v{latest} is available. Cannot auto-update (unknown install). Open GitHub to download?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if r == QMessageBox.Yes:
                webbrowser.open("https://github.com/UnDadFeated/ChronoArchiver/releases")
            return

        changelog_text = self.updater.fetch_changelog_since(__version__)

        if method == "installer":
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Update Available — v{latest}")
            dlg.setMinimumSize(440, 320)
            v = QVBoxLayout(dlg)
            v.addWidget(QLabel(
                "The app will download the installer, close, run it, then restart. "
                "No need to visit the Releases page."
            ))
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(changelog_text)
            te.setStyleSheet("background:#121212; color:#e5e7eb; font-size:10px; font-family: monospace;")
            te.setMinimumHeight(140)
            te.setMaximumHeight(340)
            v.addWidget(te)
            btns = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
            btns.setCenterButtons(True)
            btns.button(QDialogButtonBox.Ok).setText("Download & Update")
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            v.addWidget(btns)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            self._update_pulse_timer.stop()
            self.btn_update.setText("DOWNLOADING...")
            download_dlg = UpdateDownloadDialog(self)
            if not download_dlg.run_download(self.updater, latest, changelog_text):
                self.btn_update.setText(f"UPDATE v{latest} AVAILABLE")
                self._update_pulse_timer.start()
                return

            self.btn_update.setText("UPDATING...")
            installer_path = download_dlg._dest_path
            debug(UTILITY_APP, f"Installer update: launching {installer_path} for v{latest}")

            def on_error(msg):
                QMessageBox.warning(self, "Update Failed", msg)

            if self.updater.perform_installer_update(latest, installer_path, on_error=on_error):
                debug(UTILITY_APP, "Installer spawn done, quitting app")
                QApplication.instance().quit()
            else:
                self.btn_update.setText(f"UPDATE v{latest} AVAILABLE")
                self._update_pulse_timer.start()
            return

        method_desc = "git pull" if method == "git" else "AUR (paru/yay)"
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Update Available — v{latest}")
        dlg.setMinimumSize(440, 320)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"The app will close, run {method_desc}, then restart."))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(changelog_text)
        te.setStyleSheet("background:#121212; color:#e5e7eb; font-size:10px; font-family: monospace;")
        te.setMinimumHeight(140)
        te.setMaximumHeight(340)
        v.addWidget(te)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        btns.setCenterButtons(True)
        btns.button(QDialogButtonBox.Ok).setText("Update")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        def on_error(msg):
            QMessageBox.warning(self, "Update Failed", msg)

        self._update_pulse_timer.stop()
        self.btn_update.setText("UPDATING...")
        debug(UTILITY_APP, f"Update initiated: closing app for {method_desc} to v{latest}")
        self.updater.perform_update_and_restart(on_error=on_error)
        debug(UTILITY_APP, "Update spawn done, quitting app")
        QApplication.instance().quit()

if __name__ == "__main__":
    from core.single_instance import ensure_single_instance, release_single_instance

    # Qt: org/app + QSettings path must be set before any QApplication (see QSettings.setPath docs).
    QCoreApplication.setOrganizationName(APP_AUTHOR)
    QCoreApplication.setApplicationName(APP_NAME)
    if install_root() is not None:
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(_app_settings_dir()),
        )
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)

    if not ensure_single_instance():
        app = QApplication(sys.argv)
        QMessageBox.warning(None, APP_NAME, "Another instance is already running.")
        sys.exit(1)
    remove_empty_windows_legacy_config_nest()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.aboutToQuit.connect(release_single_instance)
    _load_bundled_fonts()
    _icon = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.isfile(_icon):
        app.setWindowIcon(QIcon(_icon))
    window = ChronoArchiverApp()
    window.show()
    sys.exit(app.exec())
