"""
updater.py — Headless updater for ChronoArchiver.
Checks GitHub tags API for latest version, detects install method (git/AUR), and
performs update-and-restart: close app → run update → restart app.
"""

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request

# Resolve path for version import (works from src/core/ and from package root)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_script_dir)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
from version import __version__

# Use tags API — releases/latest 404s when no GitHub Releases exist (only tags are pushed)
TAGS_API_URL = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/tags?per_page=30"


def _parse_version(v: str) -> tuple:
    """Parse version string to tuple for comparison (e.g. '2.0.4' -> (2, 0, 4))."""
    parts = []
    for s in (v or "0").replace("v", "").split("."):
        try:
            parts.append(int(s))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _version_gt(a: str, b: str) -> bool:
    """Return True if version a > b."""
    va, vb = _parse_version(a), _parse_version(b)
    for i in range(max(len(va), len(vb))):
        pa = va[i] if i < len(va) else 0
        pb = vb[i] if i < len(vb) else 0
        if pa != pb:
            return pa > pb
    return False


def _find_repo_root(start: str) -> str | None:
    """Find git repo root containing start path."""
    path = os.path.abspath(start)
    while path and path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    return None


def _find_app_launch_cmd(install_method: str) -> list:
    """Return command to restart the app: [executable, app.py] for git, ['chronoarchiver'] for AUR."""
    if install_method == "aur":
        return ["chronoarchiver"]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    app_py = os.path.join(_script_dir, "..", "ui", "app.py")
    app_py = os.path.abspath(app_py)
    if os.path.isfile(app_py):
        return [sys.executable, app_py]
    return ["chronoarchiver"]


def _is_aur_install() -> bool:
    """True if running from AUR package (/usr/share/chronoarchiver)."""
    if platform.system() != "Linux":
        return False
    try:
        resolved = os.path.realpath(__file__)
        return "/usr/share/chronoarchiver" in resolved or "/usr/share/chronoarchiver/" in resolved
    except Exception:
        return False


def _is_git_install() -> bool:
    """True if running from a git clone (Windows or Linux)."""
    # app.py lives at src/ui/app.py, repo root is one level above src
    app_dir = os.path.dirname(os.path.abspath(__file__))
    root = _find_repo_root(os.path.join(app_dir, ".."))
    return root is not None


def _find_aur_helper() -> str | None:
    """Return paru, yay, or None (pacman requires terminal)."""
    for cmd in ("paru", "yay"):
        if shutil.which(cmd):
            return cmd
    return None


def _find_linux_terminal() -> str | None:
    """Find a terminal emulator for interactive AUR update."""
    for term in ("gnome-terminal", "konsole", "xterm", "xfce4-terminal", "kitty"):
        if shutil.which(term):
            return term
    return None


class ApplicationUpdater:
    def __init__(self):
        self._latest_version = None
        self._changelog = None

    def get_install_method(self) -> str:
        """
        Returns: 'git' | 'aur' | None
        - git: Running from git clone (Windows or Linux) — use git pull
        - aur: Installed via AUR on Arch — use paru/yay/pacman
        - None: Unknown install, cannot auto-update
        """
        if _is_aur_install():
            return "aur"
        if _is_git_install():
            return "git"
        return None

    def is_update_available(self) -> bool:
        """True if latest known release is newer than current version."""
        if not self._latest_version:
            return False
        return _version_gt(self._latest_version, __version__)

    def check_for_updates(self, result_queue: queue.Queue):
        """
        Background check for updates.
        Puts (latest_version, changelog) into result_queue when done.
        Caller should poll the queue from the main thread (e.g. via QTimer).
        Uses a watchdog to ensure result is queued even if the request hangs.
        """
        def _put_result(latest, changelog):
            try:
                result_queue.put_nowait((latest, changelog))
            except queue.Full:
                pass

        def _task():
            try:
                req = urllib.request.Request(
                    TAGS_API_URL,
                    headers={
                        "User-Agent": "ChronoArchiver-Updater",
                        "Accept": "application/vnd.github+json",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                tags = data if isinstance(data, list) else []
                if not tags:
                    _put_result(None, None)
                    return
                # Find highest version among tags (tags API order is not guaranteed)
                best_version = "0"
                for t in tags:
                    name = t.get("name", "").replace("v", "").strip()
                    if name and _version_gt(name, best_version):
                        best_version = name
                self._latest_version = best_version
                self._changelog = f"Changelog: see CHANGELOG.md on GitHub for v{best_version}."
                _put_result(self._latest_version, self._changelog)
            except Exception as e:
                try:
                    from core.debug_logger import debug, UTILITY_APP
                    debug(UTILITY_APP, f"Update check failed: {e}")
                except Exception:
                    pass
                _put_result(None, None)

        _done = threading.Event()

        def _watchdog():
            if not _done.wait(timeout=15):
                _put_result(None, None)

        def _run():
            _task()
            _done.set()

        threading.Thread(target=_run, daemon=True).start()
        threading.Thread(target=_watchdog, daemon=True).start()

    def get_latest_version(self):
        return self._latest_version

    def get_changelog(self):
        return self._changelog

    def perform_update_and_restart(self, on_error=None):
        """
        Close app, run update, restart app.
        Spawns a detached helper process that waits for this process to exit,
        then runs the update command, then restarts the app.
        on_error(msg): optional callback if update cannot be performed (runs on main thread).
        """
        method = self.get_install_method()
        launch_cmd = _find_app_launch_cmd(method)

        if method == "git":
            repo_root = _find_repo_root(os.path.join(_script_dir, ".."))
            if not repo_root:
                if on_error:
                    on_error("Could not find git repository root.")
                return
            self._spawn_git_updater(repo_root, launch_cmd)
        elif method == "aur":
            helper = _find_aur_helper()
            term = _find_linux_terminal()
            if not helper and not term:
                if on_error:
                    on_error("No AUR helper (paru/yay) or terminal found. Run 'paru -Syu chronoarchiver' or 'yay -Syu chronoarchiver' manually.")
                return
            self._spawn_aur_updater(helper, term, launch_cmd)
        else:
            if on_error:
                on_error("Unknown install method. Download the latest release from GitHub.")
            return

        # Caller (app) should quit after this returns

    def _spawn_git_updater(self, repo_root: str, launch_cmd: list):
        """Spawn detached process: wait for app exit, git pull, restart."""
        if platform.system() == "Windows":
            script = f'''@echo off
ping -n 3 127.0.0.1 > nul
cd /d "{repo_root}"
git pull
start "" {" ".join('"%s"' % c for c in launch_cmd)}
'''
            fd, path = tempfile.mkstemp(suffix=".bat")
            try:
                os.write(fd, script.encode("utf-8"))
                os.close(fd)
                subprocess.Popen(
                    ["cmd", "/c", path],
                    creationflags=subprocess.CREATE_NEW_PROCESS | subprocess.DETACHED_PROCESS,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(path),
                )
            finally:
                try:
                    os.unlink(path)
                except Exception:
                    pass
        else:
            cmd_str = " ".join(repr(c) for c in launch_cmd)
            script = f'''#!/bin/sh
sleep 2
cd "{repo_root}" && git pull
exec {cmd_str}
'''
            fd, path = tempfile.mkstemp(suffix=".sh")
            try:
                os.write(fd, script.encode("utf-8"))
                os.close(fd)
                os.chmod(path, 0o755)
                subprocess.Popen(
                    [path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            finally:
                try:
                    os.unlink(path)
                except Exception:
                    pass

    def _spawn_aur_updater(self, helper: str | None, term: str | None, launch_cmd: list):
        """Spawn process that runs AUR update then restarts app."""
        if helper:
            update_cmd = f"{helper} -Syu chronoarchiver"
        else:
            update_cmd = "pkexec pacman -Syu chronoarchiver"
        launch_str = " ".join(repr(c) for c in launch_cmd)
        script_body = f"""#!/bin/bash
sleep 2
{update_cmd} && exec {launch_str}
"""
        fd, script_path = tempfile.mkstemp(suffix=".sh")
        try:
            os.write(fd, script_body.encode("utf-8"))
            os.close(fd)
            os.chmod(script_path, 0o755)
            if term:
                if "gnome-terminal" in term:
                    cmd = [term, "--", "bash", script_path]
                elif "konsole" in term:
                    cmd = [term, "-e", f"bash {script_path}"]
                else:
                    cmd = [term, "-e", f"bash {script_path}"]
            else:
                cmd = ["bash", script_path]
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            # Script file left in temp; OS will clean on reboot
        except Exception:
            try:
                os.unlink(script_path)
            except Exception:
                pass
