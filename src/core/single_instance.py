"""
single_instance.py — Ensure only one ChronoArchiver instance runs.
Uses filelock; second launch exits with message.
"""
from pathlib import Path

try:
    from .app_paths import runtime_dir
except ImportError:
    from core.app_paths import runtime_dir

_lock = None


def _lock_file_path() -> Path:
    return runtime_dir() / "chronoarchiver.lock"


def ensure_single_instance() -> bool:
    """
    Call at app startup. Returns True if this is the only instance.
    Returns False if another instance is running; caller should exit.
    """
    global _lock
    try:
        from filelock import FileLock
        _lock = FileLock(str(_lock_file_path()))
        _lock.acquire(timeout=0)
        return True
    except Exception:
        return False


def release_single_instance():
    """Call on app exit to release the lock."""
    global _lock
    if _lock:
        try:
            _lock.release()
        except Exception:
            pass
        _lock = None
