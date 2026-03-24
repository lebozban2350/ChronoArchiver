"""
organizer_panel.py — Media Organizer panel for ChronoArchiver.
Visual style matches Mass AV1 Encoder v12.
Uses src/core/organizer.py unchanged.
"""

import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QCheckBox, QComboBox,
    QProgressBar, QFileDialog, QTextEdit, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QTextCursor

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.organizer import OrganizerEngine, PHOTO_EXTS, VIDEO_EXTS
from ui.console_style import message_to_html, PANEL_CONSOLE_TEXTEDIT_STYLE
from core.debug_logger import debug, UTILITY_MEDIA_ORGANIZER


class _Signals(QObject):
    log_msg  = Signal(str)
    progress = Signal(float)
    status   = Signal(str)
    finished = Signal()
    stats    = Signal(int, int, int)  # moved, skipped, duplicates


class MediaOrganizerPanel(QWidget):

    def __init__(self, log_callback=None, status_callback=None, parent=None):
        super().__init__(parent)
        self._log_cb = log_callback
        self._status_cb = status_callback
        self._sig    = _Signals()
        self._sig.log_msg.connect(self._add_log)
        self._sig.progress.connect(self._on_progress)
        self._sig.status.connect(self._on_status)
        self._sig.finished.connect(self._on_finished)
        self._sig.stats.connect(self._on_stats)

        self._engine = None  # Initialized in _run_job
        self._is_running = False
        self._last_stats = (0, 0, 0)

        _shint = "font-size: 7px; color: #444; margin-top: -1px;"
        _bar_h = 28
        _browse_w, _browse_h = 60, _bar_h
        _edit_ss = (
            f"color:#fff; font-size:11px; font-weight:500; background:#121212; border:1px solid #1a1a1a; "
            f"padding:2px 6px; min-height:{_bar_h}px; max-height:{_bar_h}px;"
        )
        _btn_ss = "font-size:9px; font-weight:700; color:#aaa; border:2px solid #262626;"

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 2)
        root.setSpacing(2)

        # ── COMMAND STRIP ─────────────────────────────────────────────────────
        h_strip = QHBoxLayout()
        h_strip.setSpacing(6)
        _box_height = 126

        # 1. Paths (Source, Target, Photos/Videos — merged)
        grp_paths = QGroupBox("Paths")
        grp_paths.setFixedHeight(_box_height)
        v_paths = QVBoxLayout(grp_paths)
        v_paths.setContentsMargins(6, 4, 6, 4)
        v_paths.setSpacing(8)

        # Source row
        h_src = QHBoxLayout()
        h_src.setSpacing(6)
        self._edit_path = QLineEdit()
        self._edit_path.setPlaceholderText("SOURCE — folder containing media...")
        self._edit_path.setStyleSheet(_edit_ss)
        self._edit_path.setFixedHeight(_bar_h)
        h_src.addWidget(self._edit_path, 1)
        self._btn_browse_src = QPushButton("Browse")
        self._btn_browse_src.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_src.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_browse_src.setStyleSheet(_btn_ss)
        self._btn_browse_src.clicked.connect(self._browse)
        h_src.addWidget(self._btn_browse_src)
        v_paths.addLayout(h_src)

        # Target row
        h_tgt = QHBoxLayout()
        h_tgt.setSpacing(6)
        self._edit_target = QLineEdit()
        self._edit_target.setPlaceholderText("TARGET (optional, blank = in-place)")
        self._edit_target.setStyleSheet(_edit_ss)
        self._edit_target.setFixedHeight(_bar_h)
        h_tgt.addWidget(self._edit_target, 1)
        self._btn_browse_target = QPushButton("Browse")
        self._btn_browse_target.setFixedSize(_browse_w, _browse_h)
        self._btn_browse_target.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_browse_target.setStyleSheet(_btn_ss)
        self._btn_browse_target.clicked.connect(self._browse_target)
        h_tgt.addWidget(self._btn_browse_target)
        v_paths.addLayout(h_tgt)

        # Row 3: Date hint (was row 4)
        v_paths.addWidget(QLabel("Date from EXIF/ffprobe. Blank target = in-place.", styleSheet=_shint))

        # Row 4: Organize + Photos/Videos — right aligned
        h_media = QHBoxLayout()
        h_media.addStretch(1)
        lbl_media = QLabel("Organize:", styleSheet=_shint)
        h_media.addWidget(lbl_media)
        self._chk_photos = QCheckBox("Photos")
        self._chk_photos.setChecked(True)
        self._chk_videos = QCheckBox("Videos")
        self._chk_videos.setChecked(True)
        for cb in [self._chk_photos, self._chk_videos]:
            cb.setStyleSheet("font-size:9px; font-weight:700; color:#aaa; border:none;")
            h_media.addWidget(cb)
        v_paths.addLayout(h_media)
        h_strip.addWidget(grp_paths, 1)

        # 2. Execution Mode — shrunk horizontally
        grp_mode = QGroupBox("Execution Mode")
        grp_mode.setFixedHeight(_box_height)
        grp_mode.setMaximumWidth(260)
        v_mode = QVBoxLayout(grp_mode)
        v_mode.setContentsMargins(6, 4, 6, 4)
        v_mode.setSpacing(2)
        self._chk_dry = QCheckBox("Dry Run (Simulation)")
        self._chk_dry.setChecked(True)
        self._chk_dry.setStyleSheet("font-size:9px; font-weight:700; color:#aaa;")
        v_mode.addWidget(self._chk_dry)
        lbl_struct = QLabel("Folder structure:")
        lbl_struct.setStyleSheet("font-size:8px; color:#888; margin-top:4px;")
        v_mode.addWidget(lbl_struct)
        self._combo_structure = QComboBox()
        self._combo_structure.addItems([
            "YYYY/YYYY-MM (nested)",
            "YYYY-MM (flat month)",
            "YYYY-MM-DD (flat day)",
            "YYYY/YYYY-MM/YYYY-MM-DD (nested day)",
        ])
        self._combo_structure.setStyleSheet("font-size:9px; min-height:21px;")
        v_mode.addWidget(self._combo_structure)
        h_mode = QHBoxLayout()
        self._combo_action = QComboBox()
        self._combo_action.addItems(["Move", "Copy", "Symlink"])
        self._combo_action.setToolTip("Move=relocate; Copy=duplicate; Symlink=create links")
        self._combo_action.setStyleSheet("font-size:8px; min-height:19px;")
        self._combo_dup = QComboBox()
        self._combo_dup.addItems([
            "Rename", "Skip", "Keep newer",
            "Overwrite if same name", "Overwrite if same name+size",
        ])
        self._combo_dup.setToolTip("Rename=add _1, _2… on collision; Skip=skip if exists; Keep newer=skip if target newer; Overwrite name=replace any; Overwrite name+size=replace only when size matches, else rename")
        self._combo_dup.setStyleSheet("font-size:8px; min-height:19px;")
        h_mode.addWidget(QLabel("Action:", styleSheet="font-size:8px; color:#888;"))
        h_mode.addWidget(self._combo_action, 1)
        h_mode.addWidget(QLabel("Dup:", styleSheet="font-size:8px; color:#888;"))
        h_mode.addWidget(self._combo_dup, 1)
        v_mode.addLayout(h_mode)
        h_strip.addWidget(grp_mode, 0)

        root.addLayout(h_strip)

        # ── EXECUTION ─────────────────────────────────────────────────────────
        grp_exec = QGroupBox("Organization Progress")
        v_exec   = QVBoxLayout(grp_exec)
        v_exec.setContentsMargins(8, 4, 8, 8); v_exec.setSpacing(1)

        self._bar = QProgressBar()
        self._bar.setObjectName("masterBar")
        self._bar.setFixedHeight(18)
        self._bar.setTextVisible(True)
        self._bar.setFormat("Ready")
        v_exec.addWidget(self._bar)

        self._lbl_status = QLabel("Ready to organize")
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setStyleSheet(
            "color:#10b981; font-size:10px; font-weight:800; margin-top:2px; "
            "padding:0; margin-left:0; margin-right:0; margin-bottom:0;"
        )
        v_exec.addWidget(self._lbl_status)

        h_ctrl = QHBoxLayout(); h_ctrl.setSpacing(8)
        self._btn_start = QPushButton("START ORGANIZATION")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setMinimumHeight(40)
        self._btn_start.clicked.connect(self._run_job)
        h_ctrl.addWidget(self._btn_start, 2)

        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setMinimumHeight(40)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_job)
        h_ctrl.addWidget(self._btn_stop, 1)

        v_exec.addLayout(h_ctrl)

        self._edit_path.textChanged.connect(self._update_start_enabled)
        self._edit_target.textChanged.connect(self._update_start_enabled)
        self._chk_photos.stateChanged.connect(self._update_start_enabled)
        self._chk_videos.stateChanged.connect(self._update_start_enabled)
        self._guide_pulse_timer = QTimer(self)
        self._guide_pulse_timer.setInterval(550)
        self._guide_pulse_timer.timeout.connect(self._pulse_guide)
        self._guide_glow_phase = 0
        self._guide_target = None
        self._update_start_enabled()
        grp_exec.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(grp_exec)

        # ── CONSOLE ───────────────────────────────────────────────────────────
        grp_log = QGroupBox("Console")
        v_log = QVBoxLayout(grp_log)
        v_log.setContentsMargins(6, 4, 6, 4); v_log.setSpacing(0)
        self._log_edit = QTextEdit()
        self._log_edit.setObjectName("panelConsole")
        self._log_edit.setStyleSheet(PANEL_CONSOLE_TEXTEDIT_STYLE)
        self._log_edit.setReadOnly(True)
        self._log_edit.setAcceptRichText(True)
        self._log_edit.document().setMaximumBlockCount(1000)
        v_log.addWidget(self._log_edit)
        root.addWidget(grp_log, 1)  # Stretch: console takes all remaining vertical space

    def _get_valid_exts(self):
        """Set of photo and/or video extensions based on checkboxes. Only these file types are processed."""
        exts = set()
        if self._chk_photos.isChecked():
            exts.update(PHOTO_EXTS)
        if self._chk_videos.isChecked():
            exts.update(VIDEO_EXTS)
        return exts

    def _can_start(self):
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            return False
        if not self._get_valid_exts():
            return False
        target = self._edit_target.text().strip()
        if target and not os.path.isdir(target):
            return False
        return True

    def _get_guide_target(self):
        """Returns the button/widget that needs user attention next (step by step)."""
        if self._is_running:
            return None
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            return self._btn_browse_src
        if not self._get_valid_exts():
            return self._chk_photos
        target = self._edit_target.text().strip()
        if target and not os.path.isdir(target):
            return self._btn_browse_target
        return self._btn_start

    def _update_start_enabled(self):
        can = not self._is_running and self._can_start()
        self._btn_start.setEnabled(can)
        self._guide_glow_phase = 0
        self._guide_pulse_timer.start()

    def _clear_guide_glow(self, w):
        if not w:
            return
        if w == self._btn_start:
            w.setStyleSheet("background-color:#10b981; color:#064e3b; border:2px solid #064e3b; font-size:10px; font-weight:900;")
        elif w in (self._btn_browse_src, self._btn_browse_target):
            w.setStyleSheet("font-size:9px; font-weight:700; color:#aaa; border:2px solid #262626;")
        elif w in (self._chk_photos, self._chk_videos):
            w.setStyleSheet("font-size:9px; font-weight:700; color:#aaa; border:none;")

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
            elif target in (self._btn_browse_src, self._btn_browse_target):
                target.setStyleSheet("font-size:9px; font-weight:700; color:#ef4444; border:2px solid #ef4444;")
            else:
                target.setStyleSheet("font-size:9px; font-weight:700; color:#ef4444; border:none;")
        else:
            self._clear_guide_glow(target)

    def _browse(self):
        f = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if f:
            self._edit_path.setText(f)

    def _browse_target(self):
        f = QFileDialog.getExistingDirectory(self, "Select Target Folder (optional)")
        if f:
            self._edit_target.setText(f)

    def _run_job(self):
        path = self._edit_path.text().strip()
        if not path or not os.path.isdir(path):
            self._add_log("ERROR: Invalid source directory.")
            debug(UTILITY_MEDIA_ORGANIZER, f"ERROR: Invalid source directory: {path or '(empty)'}")
            return

        exts = self._get_valid_exts()
        if not exts:
            self._add_log("ERROR: Select at least one media type (Photos and/or Videos).")
            debug(UTILITY_MEDIA_ORGANIZER, "ERROR: No media types selected")
            return

        target = self._edit_target.text().strip() or None
        if target and not os.path.isdir(target):
            self._add_log("ERROR: Target directory does not exist.")
            debug(UTILITY_MEDIA_ORGANIZER, f"ERROR: Target directory does not exist: {target}")
            return

        structure_keys = ("nested", "flat_month", "flat_day", "nested_day")
        folder_structure = structure_keys[self._combo_structure.currentIndex()]
        action_keys = ("move", "copy", "symlink")
        action = action_keys[self._combo_action.currentIndex()]
        dup_keys = ("rename", "skip", "keep_newer", "overwrite", "overwrite_same")
        duplicate_policy = dup_keys[self._combo_dup.currentIndex()]
        debug(UTILITY_MEDIA_ORGANIZER, f"Organization start: path={path}, action={action}, structure={folder_structure}, target={target or 'in-place'}")
        self._is_running = True
        if self._status_cb:
            self._status_cb("organizing")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

        def _log(msg):
            self._sig.log_msg.emit(msg)

        self._engine = OrganizerEngine(logger_callback=_log)

        def _prog(bytes_done, total_bytes, files_done, total_files, filename):
            pct = (bytes_done / total_bytes) if total_bytes > 0 else 0.0
            self._sig.progress.emit(pct)
            self._sig.status.emit(f"{files_done}/{total_files}  {filename}")

        def _stats(moved, skipped, duplicates):
            self._sig.stats.emit(moved, skipped, duplicates)

        def _run():
            try:
                self._engine.organize(path,
                    dry_run=self._chk_dry.isChecked(),
                    folder_structure=folder_structure,
                    valid_exts=exts,
                    target_dir=target,
                    action=action,
                    exclude_dirs=None,
                    duplicate_policy=duplicate_policy,
                    progress_callback=_prog,
                    stats_callback=_stats)
            except Exception as e:
                self._sig.log_msg.emit(f"ERROR: {e}")
                debug(UTILITY_MEDIA_ORGANIZER, f"Organizer thread exception: {e}")
            finally:
                self._sig.finished.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _stop_job(self):
        if self._engine:
            self._engine.cancel()
            debug(UTILITY_MEDIA_ORGANIZER, "Organization stopped by user")
        self._update_start_enabled()
        self._btn_stop.setEnabled(False)

    def _on_progress(self, val):
        self._bar.setValue(int(val * 100))

    def _on_status(self, msg):
        self._lbl_status.setText(msg)

    def _on_stats(self, moved, skipped, duplicates):
        self._last_stats = (moved, skipped, duplicates)

    def get_activity(self):
        return "organizing" if self._is_running else "idle"

    def _on_finished(self):
        self._is_running = False
        if self._status_cb:
            self._status_cb("idle")
        self._update_start_enabled()
        self._btn_stop.setEnabled(False)
        self._bar.setFormat("Complete")
        stats = getattr(self, "_last_stats", (0, 0, 0))
        moved, skipped, duplicates = stats
        self._lbl_status.setText(f"Moved: {moved} | Skipped: {skipped} | Duplicates: {duplicates}")
        self._add_log("Batch organization complete.")
        debug(UTILITY_MEDIA_ORGANIZER, f"Organization complete: moved={moved}, skipped={skipped}, duplicates={duplicates}")

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
