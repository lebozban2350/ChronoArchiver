"""
debug_logger.py — Single log file for ChronoArchiver per session.
One file created at startup: chronoarchiver_YYYY-MM-DD_HH-MM-SS.log
Both debug() and standard logging write to this file. Keeps last 5.

Also: uncaught exception hooks (main + threads), optional traceback logging API,
and mirroring of important panel lines into the legacy pipe format.
"""

from __future__ import annotations

import glob
import logging
import os
import sys
import threading
import traceback
from datetime import datetime

try:
    from .app_paths import logs_dir
except ImportError:
    from core.app_paths import logs_dir
LOG_PREFIX = "chronoarchiver"
LOG_SUFFIX = ".log"
MAX_LOG_FILES = 5

_log_dir = None
_log_path = None
_file = None

_hooks_installed = False
_prev_sys_excepthook = None
_prev_thread_excepthook = None

_uncaught = logging.getLogger("ChronoArchiver.uncaught")

UTILITY_APP = "ChronoArchiver"
UTILITY_MEDIA_ORGANIZER = "Media Organizer"
UTILITY_MASS_AV1_ENCODER = "Mass AV1 Encoder"
UTILITY_AI_MEDIA_SCANNER = "AI Media Scanner"
UTILITY_OPENCV_INSTALL = "OpenCV Install"
UTILITY_MODEL_SETUP = "Model Setup"
# Prerequisite / download popups (FFmpeg, OpenCV, models, PyTorch, updater) — mirror UI lines to master log.
UTILITY_INSTALLER_POPUP = "Installer popup"

# Internal app labels for log_installer_popup (session debug log).
INSTALLER_APP_MAIN = "ChronoArchiver"
INSTALLER_APP_AI_VIDEO_UPSCALER = "AI Video Upscaler"
INSTALLER_APP_AI_IMAGE_UPSCALER = "AI Image Upscaler"
INSTALLER_APP_AI_MEDIA_SCANNER = "AI Media Scanner"
INSTALLER_APP_MASS_AV1_ENCODER = "Mass AV1 Encoder"


def log_installer_popup(app: str, dialog: str, event: str, detail: str = "") -> None:
    """
    Log installer / prerequisite popup activity to the session debug log.

    Use for: show/hide, progress, cancel, completion. ``detail`` is truncated internally if very long.
    """
    try:
        d = (detail or "").strip()
        if len(d) > 2000:
            d = d[:1990] + "… [truncated]"
        msg = f"{app} | {dialog} | {event}"
        if d:
            msg += f" | {d}"
        debug(UTILITY_INSTALLER_POPUP, msg)
    except Exception:
        pass


def _ensure_init():
    global _log_dir, _log_path, _file
    if _log_path is not None:
        return
    _log_dir = str(logs_dir())
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _log_path = os.path.join(_log_dir, f"{LOG_PREFIX}_{ts}{LOG_SUFFIX}")
    _file = open(_log_path, "a", encoding="utf-8")
    _prune_old_logs()


def _prune_old_logs():
    """Keep only the last MAX_LOG_FILES instances (by mtime), including current file."""
    pattern = os.path.join(_log_dir, f"{LOG_PREFIX}_*{LOG_SUFFIX}")
    files = glob.glob(pattern)
    if len(files) <= MAX_LOG_FILES:
        return
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for p in files[MAX_LOG_FILES:]:
        try:
            if p != _log_path:
                os.remove(p)
        except OSError:
            pass


def debug(utility: str, message: str):
    """Append a log entry: timestamp | utility | message."""
    try:
        _ensure_init()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{ts} | {utility} | {message}\n"
        _file.write(line)
        _file.flush()
    except Exception:
        pass


def init_log():
    """Ensure log file is created at startup. Call early in app init."""
    _ensure_init()


def get_log_path() -> str:
    """Return the current debug log file path."""
    _ensure_init()
    return _log_path


def append_multiline(utility: str, title: str, body: str, *, max_chars: int = 32000) -> None:
    """Write a multi-line block (e.g. subprocess output) to the session pipe log."""
    try:
        _ensure_init()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        b = (body or "").strip()
        if len(b) > max_chars:
            b = b[: max_chars - 40] + "\n… [truncated] …\n"
        block = f"{ts} | {utility} | {title}\n{b}\n"
        _file.write(block)
        _file.flush()
    except Exception:
        pass


def log_exception(
    exc: BaseException,
    context: str = "",
    *,
    utility: str = UTILITY_APP,
    extra: str | None = None,
) -> None:
    """Log a caught exception with full traceback to pipe file + standard logging."""
    try:
        _ensure_init()
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_str = "".join(tb)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        head = f"{ts} | {utility} | EXCEPTION"
        if context:
            head += f" [{context}]"
        _file.write(f"{head}\n{tb_str}")
        if extra:
            _file.write(f"Detail: {extra}\n")
        _file.flush()
    except Exception:
        pass
    try:
        _uncaught.error(
            "%s%s",
            f"{context}: " if context else "",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:
        pass


def _log_uncaught_tb(exc_type, exc_value, exc_tb, context: str) -> None:
    if exc_type is None or exc_value is None:
        return
    try:
        _ensure_init()
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        _file.write(f"{ts} | {UTILITY_APP} | UNCAUGHT [{context}]\n{tb_str}")
        _file.flush()
        _uncaught.error("UNCAUGHT [%s]\n%s", context, tb_str.strip())
    except Exception:
        pass


def _sys_excepthook(exc_type, exc_value, exc_tb):
    try:
        _log_uncaught_tb(exc_type, exc_value, exc_tb, "sys.excepthook")
    except Exception:
        pass
    hook = _prev_sys_excepthook or sys.__excepthook__
    try:
        hook(exc_type, exc_value, exc_tb)
    except Exception:
        pass


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    try:
        if args.exc_type is not None:
            _log_uncaught_tb(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                f"threading (name={getattr(args.thread, 'name', '?')})",
            )
    except Exception:
        pass
    if _prev_thread_excepthook is not None:
        try:
            _prev_thread_excepthook(args)
        except Exception:
            pass


def install_global_exception_hooks() -> None:
    """Install once: log uncaught exceptions from main thread and worker threads."""
    global _hooks_installed, _prev_sys_excepthook, _prev_thread_excepthook
    if _hooks_installed:
        return
    _ensure_init()
    if sys.excepthook is not _sys_excepthook:
        _prev_sys_excepthook = sys.excepthook
        sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        if threading.excepthook is not _thread_excepthook:
            _prev_thread_excepthook = threading.excepthook
            threading.excepthook = _thread_excepthook
    _hooks_installed = True


def mirror_panel_line(panel: str, msg: str, *, max_len: int = 8000) -> None:
    """Copy important panel console lines into the pipe log (ERROR/WARNING/ffmpeg failures)."""
    s = str(msg).strip()
    if not s or len(s) > max_len:
        s = s[:max_len]
    u = s.upper()
    if not (
        u.startswith("ERROR")
        or u.startswith("WARNING")
        or u.startswith("FAILED")
        or "FFMPEG" in u
        or "TRACEBACK" in u
    ):
        return
    try:
        debug(UTILITY_APP, f"{panel}: {s}")
    except Exception:
        pass


def install_qt_message_handler() -> None:
    """Route Qt fatal/critical/warning messages to the standard log (call after QApplication + setup_logger)."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    def _handler(mode, context, message: str) -> None:
        lg = logging.getLogger("ChronoArchiver.Qt")
        try:
            fn = getattr(context, "file", None) or ""
            line = getattr(context, "line", 0)
            loc = f"{fn}:{line} " if fn else ""
        except Exception:
            loc = ""
        text = f"{loc}{message}".strip()
        try:
            if mode == QtMsgType.QtFatalMsg:
                lg.critical(text)
            elif mode == QtMsgType.QtCriticalMsg:
                lg.error(text)
            elif mode == QtMsgType.QtWarningMsg:
                lg.warning(text)
            elif mode == QtMsgType.QtInfoMsg:
                lg.info(text)
            else:
                lg.debug(text)
        except Exception:
            pass

    qInstallMessageHandler(_handler)
