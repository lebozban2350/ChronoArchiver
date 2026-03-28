"""
Connectivity probe for install/update flows. Distinguishes offline (no route to GitHub)
from online-but-API-failed (rate limit, empty response, etc.).

Use :data:`NO_NETWORK_MESSAGE` and label styles everywhere the UI shows this state.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from core.debug_logger import UTILITY_APP, debug

NO_NETWORK_MESSAGE = "NO NETWORK!"

# Bright red (user-requested) for error emphasis.
NO_NETWORK_LABEL_STYLE = "font-size:8px; font-weight:700; color:#ff0000;"
NO_NETWORK_LABEL_STYLE_9 = "font-size:9px; font-weight:700; color:#ff0000;"

# Same host as ApplicationUpdater (GitHub API).
_CONNECTIVITY_CHECK_URL = (
    "https://api.github.com/repos/UnDadFeated/ChronoArchiver/tags?per_page=1"
)

_cache_ok: bool | None = None
_cache_ts: float = 0.0
_CACHE_TTL_SEC = 45.0


def is_network_reachable(*, timeout: float = 3.0, force_refresh: bool = False) -> bool:
    """Return True if HTTPS to GitHub API succeeds (short probe). Cached ~45s."""
    global _cache_ok, _cache_ts
    now = time.monotonic()
    if (
        not force_refresh
        and _cache_ok is not None
        and (now - _cache_ts) < _CACHE_TTL_SEC
    ):
        return _cache_ok
    ok = _probe_network(timeout=timeout)
    _cache_ok = ok
    _cache_ts = now
    return ok


def _probe_network(timeout: float) -> bool:
    try:
        req = urllib.request.Request(
            _CONNECTIVITY_CHECK_URL,
            headers={
                "User-Agent": "ChronoArchiver-Connectivity",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass
    return False


def log_network_status_to_debug() -> None:
    """Run from a background thread right after session log init."""
    ok = is_network_reachable(force_refresh=True)
    if ok:
        debug(
            UTILITY_APP,
            "Network: reachable — update checks and downloads can use the internet.",
        )
    else:
        debug(
            UTILITY_APP,
            "Network: NOT reachable — offline mode. Installs and downloads require "
            "internet; local features and already-installed engines/models still work.",
        )
