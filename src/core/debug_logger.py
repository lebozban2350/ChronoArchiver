"""
debug_logger.py — Centralized DEBUG logging for ChronoArchiver.
Single file per session, timestamps, utility name. Filenames include date/time;
keeps last 3 instances.
"""

import os
import glob
import platformdirs
from datetime import datetime

APP_NAME = "ChronoArchiver"
DEBUG_PREFIX = "chronoarchiver_debug"
DEBUG_SUFFIX = ".log"
MAX_DEBUG_FILES = 3

_log_dir = None
_log_path = None
_file = None

UTILITY_APP = "ChronoArchiver"
UTILITY_MEDIA_ORGANIZER = "Media Organizer"
UTILITY_MASS_AV1_ENCODER = "Mass AV1 Encoder"
UTILITY_AI_MEDIA_SCANNER = "AI Media Scanner"


def _ensure_init():
    global _log_dir, _log_path, _file
    if _log_path is not None:
        return
    _log_dir = platformdirs.user_log_dir(APP_NAME, "UnDadFeated")
    os.makedirs(_log_dir, exist_ok=True)
    _prune_old_logs()
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _log_path = os.path.join(_log_dir, f"{DEBUG_PREFIX}_{ts}{DEBUG_SUFFIX}")
    _file = open(_log_path, "a", encoding="utf-8")


def _prune_old_logs():
    """Keep only the last MAX_DEBUG_FILES instances (by mtime)."""
    pattern = os.path.join(_log_dir, f"{DEBUG_PREFIX}_*{DEBUG_SUFFIX}")
    files = glob.glob(pattern)
    if len(files) <= MAX_DEBUG_FILES:
        return
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for p in files[MAX_DEBUG_FILES:]:
        try:
            os.remove(p)
        except OSError:
            pass


def debug(utility: str, message: str):
    """Append a DEBUG entry: timestamp | utility | message."""
    try:
        _ensure_init()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{ts} | {utility} | {message}\n"
        _file.write(line)
        _file.flush()
    except Exception:
        pass


def get_log_path() -> str:
    """Return the current debug log file path."""
    _ensure_init()
    return _log_path


def get_log_content() -> str:
    """Return the full content of the current debug log."""
    try:
        path = get_log_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    except Exception:
        pass
    return ""
