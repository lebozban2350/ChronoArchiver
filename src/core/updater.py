"""
updater.py — Headless updater for ChronoArchiver.
Optimized for PySide6 integration using callbacks.
"""

import json
import urllib.request
import threading
from version import __version__

GIT_API_URL = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/latest"

class ApplicationUpdater:
    def __init__(self):
        self._latest_version = None
        self._changelog = None

    def check_for_updates(self, callback):
        """
        Background check for updates.
        Calls callback(latest_version, changelog) when done.
        """
        def _task():
            try:
                # Use a custom User-Agent to avoid blocks
                req = urllib.request.Request(
                    GIT_API_URL, 
                    headers={'User-Agent': 'ChronoArchiver-Updater'}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
                    self._latest_version = data.get("tag_name", "").replace("v", "")
                    self._changelog = data.get("body", "No changelog provided.")
                    callback(self._latest_version, self._changelog)
            except Exception as e:
                print(f"Update check failed: {e}")
                callback(None, None)

        threading.Thread(target=_task, daemon=True).start()

    def get_latest_version(self):
        return self._latest_version

    def get_changelog(self):
        return self._changelog
