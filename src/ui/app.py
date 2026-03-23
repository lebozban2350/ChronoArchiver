"""
ChronoArchiver v3.0.0 — App-private venv (all Python deps internalized).
Replicates the high-density visual style of Mass AV1 Encoder v12.
Uses a QStackedWidget to manage distinct application panels.
"""

import sys
import os
import platform
import queue
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

import psutil

# Add app root and app-private venv to path (v3.0: all Python deps in venv)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.venv_manager import (
    add_venv_to_path, add_ffmpeg_to_path,
    check_opencv_in_venv, check_ffmpeg_in_venv, ensure_ffmpeg_in_venv_with_progress,
    get_pip_exe,
)
add_venv_to_path()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, QTimer

from version import __version__
from ui.panels.organizer_panel import MediaOrganizerPanel
from ui.panels.encoder_panel import AV1EncoderPanel
from ui.panels.scanner_panel import AIScannerPanel
from core.updater import ApplicationUpdater
from core.debug_logger import init_log, get_log_path, debug, UTILITY_APP
from core.logger import setup_logger

# Global Stylesheet (Mass AV1 Encoder QSS)
QSS = """
QMainWindow { background-color: #0c0c0c; }
QWidget { color: #e5e7eb; font-family: 'Inter', sans-serif; }

QGroupBox {
    border: 1px solid #1a1a1a;
    border-radius: 4px;
    margin-top: 10px;
    font-size: 8px;
    font-weight: 800;
    color: #4b5563;
    text-transform: uppercase;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }

QLineEdit {
    background-color: #121212;
    border: 1px solid #1a1a1a;
    border-radius: 3px;
    padding: 4px;
    color: #fff;
    font-size: 11px;
}
QLineEdit:focus { border: 1px solid #3b82f6; }

QPushButton {
    background-color: #1a1a1a;
    border: 1px solid #262626;
    border-radius: 4px;
    color: #9ca3af;
    font-size: 9px;
    font-weight: 700;
    padding: 4px 8px;
}
QPushButton:hover { background-color: #262626; color: #fff; }
QPushButton:pressed { background-color: #121212; }

QPushButton#btnStart {
    background-color: #10b981;
    color: #064e3b;
    border: none;
    font-size: 10px;
    font-weight: 900;
}
QPushButton#btnStart:hover { background-color: #34d399; }
QPushButton#btnStart:disabled {
    background-color: #1a1a1a;
    color: #6b7280;
    border: 1px solid #262626;
}

QPushButton#btnStop {
    background-color: #ef4444;
    color: #450a0a;
    border: none;
}
QPushButton#btnStop:disabled {
    background-color: #1a1a1a;
    color: #6b7280;
    border: 1px solid #262626;
}

QProgressBar {
    background-color: #121212;
    border: 1px solid #1a1a1a;
    border-radius: 2px;
    text-align: center;
    font-size: 8px;
    font-weight: 800;
    color: #fff;
}
QProgressBar::chunk { background-color: #3b82f6; width: 1px; }
QProgressBar#masterBar::chunk { background-color: #10b981; }

QListWidget {
    background-color: #080808;
    border: 1px solid #141414;
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    color: #6b7280;
}

QScrollBar:vertical {
    border: none;
    background: #0c0c0c;
    width: 4px;
    margin: 0px;
}
QScrollBar::handle:vertical { background: #1f2937; min-height: 20px; border-radius: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

/* Custom Nav Buttons */
QPushButton#navBtn {
    text-align: left;
    padding-left: 12px;
    height: 28px;
    font-size: 9px;
    border: none;
    border-radius: 0px;
    background: transparent;
    color: #6b7280;
}
QPushButton#navBtn:hover { background: #111111; color: #fff; }
QPushButton#navBtn[active="true"] {
    background: #1a1a1a;
    color: #3b82f6;
    border-left: 2px solid #3b82f6;
}
"""

class ChronoArchiverApp(QMainWindow):
    def __init__(self):
        super().__init__()
        init_log()
        self.setWindowTitle(f"ChronoArchiver v{__version__}")
        self.setMinimumSize(940, 680)
        self.setStyleSheet(QSS)

        self.logger = setup_logger()
        self.updater = ApplicationUpdater()
        self._update_result_queue = queue.Queue()
        self._update_poll_timer = None
        self._metrics_gpu_cache = "0%"
        self._metrics_gpu_counter = 0

        # UI Components
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── NAVIGATION BAR ──
        self.nav_bar = QFrame()
        self.nav_bar.setFixedHeight(34)
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
        self.btn_update.setStyleSheet("font-size: 8px; color: #4b5563; border:none; background:transparent;")
        self.btn_update.clicked.connect(self._run_updater)
        self.nav_layout.addWidget(self.btn_update)

        self.btn_donate = QPushButton("☕ Buy me a coffee")
        self.btn_donate.setStyleSheet("font-size: 8px; color: #6b7280; border:none; background:transparent;")
        self.btn_donate.setCursor(Qt.PointingHandCursor)
        self.btn_donate.setToolTip("Support development via PayPal ($5 USD)")
        self.btn_donate.clicked.connect(self._open_donate)
        self.nav_layout.addWidget(self.btn_donate)

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

        self.layout.addWidget(self.stack)

        # ── STATUS BAR ──
        # Layout: [Left: app activity] [Center: pre-req / boot] [Right: buttons + metrics]
        self.status_bar = QFrame()
        self.status_bar.setFixedHeight(22)
        self.status_bar.setStyleSheet("background: #080808; border-top: 1px solid #141414;")
        self.status_layout = QHBoxLayout(self.status_bar)
        self.status_layout.setContentsMargins(10, 0, 10, 0)

        self.lbl_status = QLabel("Checking…")
        self.lbl_status.setStyleSheet("font-size: 8px; color: #4b5563; text-transform: uppercase; min-width: 100px;")
        self.lbl_status.setToolTip("Current activity: Encoding, Organizing, Scanning, etc.")
        self._activity = "idle"
        self._activity_dot = 0
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(400)
        self._activity_timer.timeout.connect(self._animate_activity)
        self._precheck_done = False
        self.status_layout.addWidget(self.lbl_status)
        self._bar_ffmpeg = QProgressBar()
        self._bar_ffmpeg.setFixedSize(72, 12)
        self._bar_ffmpeg.setRange(0, 100)
        self._bar_ffmpeg.setValue(0)
        self._bar_ffmpeg.setFormat("%p%")
        self._bar_ffmpeg.setStyleSheet("font-size: 7px; font-weight: 700;")
        self._bar_ffmpeg.hide()
        self.status_layout.addWidget(self._bar_ffmpeg)
        self._lbl_ffmpeg_speed = QLabel("")
        self._lbl_ffmpeg_speed.setStyleSheet("font-size: 7px; color: #6b7280; min-width: 48px;")
        self._lbl_ffmpeg_speed.hide()
        self.status_layout.addWidget(self._lbl_ffmpeg_speed)
        self.status_layout.addStretch()

        self.lbl_prereq = QLabel("Checking…")
        self.lbl_prereq.setStyleSheet("font-size: 7px; color: #6b7280;")
        self.lbl_prereq.setAlignment(Qt.AlignCenter)
        self.status_layout.addWidget(self.lbl_prereq)
        self.status_layout.addStretch()

        self.btn_copy_console = QPushButton("COPY CONSOLE")
        self.btn_copy_console.setStyleSheet("font-size: 7px; color: #6b7280; border:none; background:transparent;")
        self.btn_copy_console.setToolTip("Copy current panel console to clipboard")
        self.btn_copy_console.clicked.connect(self._copy_console)
        self.status_layout.addWidget(self.btn_copy_console)

        self.btn_debug = QPushButton("DEBUG")
        self.btn_debug.setStyleSheet("font-size: 7px; color: #6b7280; border:none; background:transparent;")
        self.btn_debug.setToolTip("Open debug log folder")
        self.btn_debug.clicked.connect(self._open_debug_folder)
        self.status_layout.addWidget(self.btn_debug)

        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet("font-size: 8px; color: #6b7280; font-weight: 600;")
        self.status_layout.addWidget(self.lbl_metrics)
        
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
            self.lbl_status.setText("Idle")

    def _animate_activity(self):
        if self._activity == "idle":
            self._activity_timer.stop()
            self.lbl_status.setText("Idle")
            return
        base = {"encoding": "Encoding", "organizing": "Organizing", "scanning": "Scanning"}.get(self._activity, "Idle")
        dots = "." * (self._activity_dot % 3 + 1)
        self.lbl_status.setText(f"{base}{dots}")
        self._activity_dot += 1

    def _log(self, msg):
        self.logger.info(msg)

    def _check_prereqs(self):
        """Run pre-req checks, show updates on left footer, then Pre-check complete for 3s, then Idle."""
        def step2():
            self.lbl_status.setText("Checking OpenCV…")
            QTimer.singleShot(400, step3)

        def step3():
            self.lbl_status.setText("Checking AI Models…")
            QTimer.singleShot(400, step4)

        def step4():
            self.lbl_status.setText("Checking PySide6…")
            QTimer.singleShot(400, step5)

        def step5():
            self._refresh_footer()
            self.lbl_status.setText("Pre-check complete")
            self._precheck_done = True
            if hasattr(self, "panel_scn") and hasattr(self.panel_scn, "_check_models"):
                self.panel_scn._check_models()  # Deferred from init — was blocking main thread during FFmpeg install
            QTimer.singleShot(3000, _go_idle)

        def _go_idle():
            if self._activity == "idle":
                self.lbl_status.setText("Idle")
            self._activity_timer.stop()

        def step1():
            self.lbl_status.setText("Checking FFmpeg…")
            QTimer.singleShot(200, _do_ffmpeg_check)

        def _do_ffmpeg_check():
            pip = get_pip_exe()
            if pip.exists() and check_ffmpeg_in_venv():
                add_ffmpeg_to_path()
                debug(UTILITY_APP, "Pre-reqs: FFmpeg=ok (venv)")
                step2()
                return
            if pip.exists():
                _install_ffmpeg_async(step2)
                return
            ffmpeg_ok = bool(shutil.which("ffmpeg"))
            debug(UTILITY_APP, f"Pre-reqs: FFmpeg={'ok' if ffmpeg_ok else 'missing'} (no venv)")
            step2()

        def _install_ffmpeg_async(on_done):
            self.lbl_status.setText("Installing FFmpeg")
            self._bar_ffmpeg.setValue(0)
            self._bar_ffmpeg.show()
            self._lbl_ffmpeg_speed.setText("")
            self._lbl_ffmpeg_speed.show()
            self._ffmpeg_done = False
            self._ffmpeg_done_handled = False

            def _on_progress(phase: str, pct: int, detail: str):
                def _update():
                    self._bar_ffmpeg.setValue(min(100, pct))
                    self._lbl_ffmpeg_speed.setText(detail if detail else "")
                    if phase == "done":
                        self._ffmpeg_done = True
                        if not self._ffmpeg_done_handled:
                            self._ffmpeg_done_handled = True
                            self._bar_ffmpeg.setValue(100)
                            self._bar_ffmpeg.hide()
                            self._lbl_ffmpeg_speed.hide()
                            add_ffmpeg_to_path()
                            self._refresh_footer()
                            on_done()
                QTimer.singleShot(0, _update)

            def _worker():
                ok = ensure_ffmpeg_in_venv_with_progress(_on_progress)
                if not ok:
                    debug(UTILITY_APP, "Pre-reqs: FFmpeg install failed")
                if not self._ffmpeg_done_handled:
                    self._ffmpeg_done = True
                    QTimer.singleShot(0, lambda: _on_progress("done", 100, ""))

            threading.Thread(target=_worker, daemon=True).start()

        step1()

    def _refresh_footer(self):
        """Update footer pre-req status (OpenCV, AI Models) after install/uninstall. Runs check_opencv_in_venv off main thread."""
        ok_sym = '<span style="color:#10b981">✓</span>'
        fail_sym = '<span style="color:#ef4444">✗</span>'
        skip_sym = '<span style="color:#eab308">—</span>'
        ffmpeg_ok = bool(shutil.which("ffmpeg"))

        def _apply(opencv_ok: bool):
            parts = [f"FFmpeg {ok_sym if ffmpeg_ok else fail_sym}"]
            parts.append(f"OpenCV {ok_sym if opencv_ok else skip_sym}")
            models_ready = self.panel_scn._model_mgr.is_up_to_date()
            parts.append(f"AI Models {ok_sym if models_ready else skip_sym}")
            parts.append(f"PySide6 {ok_sym}")
            debug(UTILITY_APP, f"Pre-reqs: FFmpeg={'ok' if ffmpeg_ok else 'missing'}, OpenCV={'ok' if opencv_ok else 'missing'}, AI Models={'ok' if models_ready else 'missing'}, PySide6=ok")
            status = "  ·  ".join(parts)
            if ffmpeg_ok:
                status += "  ·  <span style=\"color:#10b981\">Ready</span>"
            self.lbl_prereq.setTextFormat(Qt.RichText)
            self.lbl_prereq.setText(status)

        if get_pip_exe().exists():
            def _task():
                ov = check_opencv_in_venv()
                QTimer.singleShot(0, lambda: _apply(ov))
            threading.Thread(target=_task, daemon=True).start()
        else:
            try:
                from core.scanner import OPENCV_AVAILABLE
                opencv_ok = bool(OPENCV_AVAILABLE)
            except Exception:
                opencv_ok = False
            _apply(opencv_ok)

    def _copy_console(self):
        panel = self.stack.currentWidget()
        if hasattr(panel, "_log_list"):
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
            cpu = f"{psutil.cpu_percent()}%"
            ram = f"{psutil.virtual_memory().percent}%"
            self._metrics_gpu_counter += 1
            if self._metrics_gpu_counter >= 3:
                try:
                    out = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=utilization.gpu",
                         "--format=csv,noheader,nounits"],
                        text=True, stderr=subprocess.DEVNULL).strip()
                    self._metrics_gpu_cache = f"{out}%"
                except Exception:
                    self._metrics_gpu_cache = "0%"
                self._metrics_gpu_counter = 0
            self.lbl_metrics.setText(f"  CPU {cpu}  ·  GPU {self._metrics_gpu_cache}  ·  RAM {ram}")
        except Exception:
            pass

    def _on_encoder_metrics(self, cpu, gpu, ram):
        """Encoder panel can override with its own (includes encoding Time)."""
        self.lbl_metrics.setText(f"  CPU {cpu}  ·  GPU {gpu}  ·  RAM {ram}")

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
            self.btn_update.setStyleSheet("font-size: 8px; color: #10b981; font-weight:bold;")
        elif latest is None:
            self.btn_update.setText("UPDATE CHECK UNAVAILABLE")
            self.btn_update.setStyleSheet("font-size: 8px; color: #4b5563;")
        else:
            self.btn_update.setText("CHRONOARCHIVER IS UP TO DATE")
            self.btn_update.setStyleSheet("font-size: 8px; color: #4b5563;")

    def _confirm_and_perform_update(self):
        latest = self.updater.get_latest_version()
        method = self.updater.get_install_method()
        if not method:
            QMessageBox.warning(
                self,
                "Update",
                "Cannot determine install method. Download the latest release from GitHub.",
            )
            return
        method_desc = "git pull" if method == "git" else "AUR (paru/yay)"
        r = QMessageBox.question(
            self,
            "Update ChronoArchiver",
            f"Update to v{latest}? The app will close, perform the update ({method_desc}), and restart.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if r != QMessageBox.Yes:
            return

        def on_error(msg):
            QMessageBox.warning(self, "Update Failed", msg)

        self.btn_update.setText("UPDATING...")
        self.updater.perform_update_and_restart(on_error=on_error)
        QApplication.instance().quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoArchiver")
    window = ChronoArchiverApp()
    window.show()
    sys.exit(app.exec())
