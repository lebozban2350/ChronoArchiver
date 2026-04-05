"""
Serialize heavy filesystem work (Media Organizer moves, Mass AV1 encode, video upscale)
so concurrent operations do not contend on the same volumes.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()


def try_acquire_fs_heavy() -> bool:
    """Non-blocking acquire. Returns True if this task holds the lock."""
    return _lock.acquire(blocking=False)


def acquire_fs_heavy_blocking() -> None:
    """Blocking acquire (reserved for callers that must wait; most code uses try_acquire_fs_heavy)."""
    _lock.acquire()


def release_fs_heavy() -> None:
    try:
        _lock.release()
    except RuntimeError:
        pass
