"""
updater.py — Headless updater for ChronoArchiver.
Checks GitHub tags API for latest version, detects install method (git/AUR), and
performs update-and-restart: close app → run update → restart app.
"""

import json
import os
import platform
import re
import time
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.error

# Resolve path for version import (works from src/core/ and from package root)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_script_dir)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
from version import __version__

# Use tags API — releases/latest 404s when no GitHub Releases exist (only tags are pushed)
TAGS_API_URL = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/tags?per_page=30"
RELEASES_BY_TAG_URL = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/tags/v{version}"
CHANGELOG_RAW_URL = "https://raw.githubusercontent.com/UnDadFeated/ChronoArchiver/main/CHANGELOG.md"


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


def _is_frozen() -> bool:
    """True when running as PyInstaller bundle (legacy; no longer used)."""
    return getattr(sys, "frozen", False)


def _is_installer_install() -> bool:
    """True when running from setup-installed Python app (Windows/macOS)."""
    if os.environ.get("CHRONOARCHIVER_INSTALL_ROOT") and platform.system() in ("Windows", "Darwin"):
        return True
    return bool(_is_frozen() and platform.system() in ("Windows", "Darwin"))


def _get_install_method() -> str | None:
    """Returns 'installer' | 'git' | 'aur' | None for use by restart/update logic."""
    if _is_installer_install():
        return "installer"
    if _is_aur_install():
        return "aur"
    if _is_git_install():
        return "git"
    return None


def _find_app_launch_cmd(install_method: str) -> list:
    """Return command to restart the app: [executable, app.py] for git, ['/usr/bin/chronoarchiver'] for AUR."""
    if install_method == "aur":
        return ["/usr/bin/chronoarchiver"]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    install_root = os.environ.get("CHRONOARCHIVER_INSTALL_ROOT")
    if install_method == "installer" and install_root:
        root = os.path.abspath(install_root)
        launcher = os.path.join(root, "chronoarchiver.pyw")
        if platform.system() == "Windows":
            venv_py = os.path.join(root, "venv", "Scripts", "pythonw.exe")
            if os.path.isfile(venv_py):
                return [venv_py, launcher]
        else:
            venv_py = os.path.join(root, "venv", "bin", "python")
            if os.path.isfile(venv_py):
                return [venv_py, launcher]
        return [sys.executable, launcher]
    app_py = os.path.join(_script_dir, "..", "ui", "app.py")
    app_py = os.path.abspath(app_py)
    if not os.path.isfile(app_py):
        app_py = os.path.join(_script_dir, "..", "..", "src", "ui", "app.py")
        app_py = os.path.abspath(app_py)
    if os.path.isfile(app_py):
        return [sys.executable, app_py]
    return ["chronoarchiver"]


def restart_app() -> bool:
    """
    Spawn a detached helper that waits for this process to exit, then relaunches the app.
    Call QApplication.quit() after this returns.
    Returns True if restart was scheduled, False otherwise (caller may still quit).
    """
    method = _get_install_method() or "git"  # fallback for dev
    launch_cmd = _find_app_launch_cmd(method)
    install_root = os.environ.get("CHRONOARCHIVER_INSTALL_ROOT")
    if install_root:
        src_dir = os.path.abspath(install_root)
    else:
        app_py = os.path.join(_script_dir, "..", "ui", "app.py")
        app_py = os.path.abspath(app_py)
        if not os.path.isfile(app_py):
            app_py = os.path.join(_script_dir, "..", "..", "src", "ui", "app.py")
            app_py = os.path.abspath(app_py)
        src_dir = os.path.dirname(os.path.dirname(app_py)) if os.path.isfile(app_py) else os.getcwd()
    # Avoid shell injection: reject paths containing quotes or newlines
    if '"' in src_dir or "'" in src_dir or "\n" in src_dir or "\r" in src_dir:
        src_dir = os.getcwd()

    if platform.system() == "Windows":
        script = f'''@echo off
ping -n 3 127.0.0.1 > nul
cd /d "{src_dir}"
start "" {" ".join('"%s"' % c for c in launch_cmd)}
'''
        fd, path = tempfile.mkstemp(suffix=".bat")
        try:
            try:
                os.write(fd, script.encode("utf-8"))
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
            subprocess.Popen(
                ["cmd", "/c", path],
                creationflags=subprocess.CREATE_NEW_PROCESS | subprocess.DETACHED_PROCESS,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=os.path.dirname(path),
            )
            return True
        except Exception:
            return False
    else:
        cmd_str = " ".join(repr(c) for c in launch_cmd)
        script = f'''#!/bin/sh
sleep 2
cd "{src_dir}" && exec {cmd_str}
'''
        fd, path = tempfile.mkstemp(suffix=".sh")
        try:
            try:
                os.write(fd, script.encode("utf-8"))
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
            os.chmod(path, 0o755)  # nosec B103 — temp script needs execute
            subprocess.Popen(
                [path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            return False


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

    def get_install_method(self) -> str | None:
        """
        Returns: 'git' | 'aur' | None
        - git: Running from git clone (Windows, Linux, macOS) — use git pull
        - aur: Installed via AUR on Arch Linux — use paru/yay/pacman
        - None: Unknown install (e.g. packaged app), cannot auto-update
        """
        return _get_install_method()

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
                last_err = None
                data = None
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — GitHub API
                            data = json.loads(resp.read().decode("utf-8"))
                        break
                    except urllib.error.HTTPError as e:
                        last_err = e
                        if e.code in (429, 503) and attempt < 2:
                            time.sleep(2 ** attempt)
                        else:
                            raise
                if data is None and last_err:
                    raise last_err
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

    def get_installer_asset_info(self, version: str) -> tuple[str, int, str] | None:
        """
        Fetch release by tag and return (download_url, size_bytes, filename) for the
        platform-specific installer, or None if not found.
        """
        version_clean = (version or "").replace("v", "").strip()
        if not version_clean:
            return None
        if platform.system() == "Windows":
            expected_name = f"ChronoArchiver-Setup-{version_clean}-win64.exe"
        else:
            expected_name = f"ChronoArchiver-Setup-{version_clean}-mac64.zip"
        try:
            url = RELEASES_BY_TAG_URL.format(version=version_clean)
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "ChronoArchiver-Updater",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                data = json.loads(resp.read().decode("utf-8"))
            assets = data.get("assets") or []
            for a in assets:
                name = a.get("name", "")
                if name == expected_name:
                    return (
                        a.get("browser_download_url", ""),
                        int(a.get("size", 0) or 0),
                        name,
                    )
        except Exception:
            pass
        return None

    def download_installer_with_progress(
        self,
        url: str,
        dest_path: str,
        total_bytes: int,
        progress_callback,
    ) -> bool:
        """
        Stream-download installer to dest_path. Calls progress_callback(downloaded, total, pct_0_to_100, mb_per_sec).
        Returns True on success, False on failure.
        """
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ChronoArchiver-Updater"})
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                total = total_bytes or int(resp.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                start = time.time()
                chunk_size = 256 * 1024
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        mbps = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        pct = (100.0 * downloaded / total) if total > 0 else 0
                        if progress_callback:
                            progress_callback(downloaded, total, min(100.0, pct), mbps)
            return True
        except Exception:
            return False

    def perform_installer_update(
        self,
        version: str,
        installer_path: str,
        on_error=None,
    ):
        """
        Spawn a helper that waits for this process to exit, runs the installer, then the
        installer launches the updated app. Call QApplication.quit() after this returns.
        """
        launch_cmd = _find_app_launch_cmd("installer")
        if platform.system() == "Windows":
            # Setup exe downloads full app on first run, then launches it; we just run setup
            inst_esc = str(installer_path).replace("\\", "\\\\").replace('"', '\\"')
            script = f'''@echo off
ping -n 3 127.0.0.1 > nul
start /wait "" "{inst_esc}"
'''
            ext = ".bat"
        else:
            # macOS: extract setup zip, run ChronoArchiver-Setup.app (it downloads full app)
            inst_esc = str(installer_path).replace("\\", "\\\\").replace('"', '\\"')
            script = f'''#!/bin/sh
sleep 2
ZIP="{inst_esc}"
TMP=$(mktemp -d)
unzip -q "$ZIP" -d "$TMP"
SETUP_APP=$(echo "$TMP"/*.app)
if [ -d "$SETUP_APP" ]; then
  open "$SETUP_APP"
fi
'''
            ext = ".sh"
        fd, path = tempfile.mkstemp(suffix=ext)
        try:
            os.write(fd, script.encode("utf-8"))
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        if platform.system() != "Windows":
            os.chmod(path, 0o755)  # nosec B103
        try:
            if platform.system() == "Windows":
                subprocess.Popen(
                    ["cmd", "/c", path],
                    creationflags=subprocess.CREATE_NEW_PROCESS | subprocess.DETACHED_PROCESS,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(path),
                )
            else:
                subprocess.Popen(
                    [path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except Exception as e:
            if on_error:
                on_error(f"Failed to run installer: {e}")

    def fetch_changelog_since(self, current_version: str) -> str:
        """Fetch CHANGELOG.md and return all sections from (current, latest], newest first. Falls back on single latest on failure."""
        current = (current_version or "").replace("v", "").strip()
        latest = (self._latest_version or "").replace("v", "").strip()
        if not latest or not _version_gt(latest, current):
            return "Changelog unavailable."
        try:
            req = urllib.request.Request(
                CHANGELOG_RAW_URL,
                headers={"User-Agent": "ChronoArchiver-Updater"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310 — GitHub raw
                text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return f"Changelog for v{latest} — see CHANGELOG.md on GitHub."
        sections = []
        for m in re.finditer(r"^## \[([^\]]+)\].*$", text, re.MULTILINE):
            v = m.group(1).strip()
            if not _version_gt(v, current) or _version_gt(v, latest):
                continue
            start = m.start()
            next_m = re.search(r"\n## \[", text[m.end() :])
            end = m.end() + next_m.start() if next_m else len(text)
            sections.append((v, text[start:end].strip()))
        sections.sort(key=lambda x: _parse_version(x[0]), reverse=True)
        result = "\n\n".join(s for _, s in sections) if sections else f"Changelog for v{latest} — see CHANGELOG.md on GitHub."
        return result

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
                    on_error("No AUR helper (paru/yay) or terminal found. Run 'paru -Sy chronoarchiver' or 'yay -Sy chronoarchiver' manually.")
                return
            self._spawn_aur_updater(helper, term, launch_cmd)
        else:
            if on_error:
                on_error("Unknown install method. Download the latest release from GitHub.")
            return

        # Caller (app) should quit after this returns

    def _spawn_git_updater(self, repo_root: str, launch_cmd: list):
        """Spawn detached process: wait for app exit, git pull (via GitPython), restart."""
        # Use venv Python (has GitPython) to run helper; no system git required
        helper_body = '''import os
import sys
import time
import subprocess

time.sleep(3 if os.name == "nt" else 2)
repo_root = sys.argv[1]
launch_cmd = sys.argv[2:]

try:
    import git
    repo = git.Repo(repo_root)
    repo.remotes.origin.pull()
except ImportError:
    try:
        subprocess.run(["git", "pull"], cwd=repo_root, capture_output=True, timeout=60)
    except Exception:
        pass
except Exception:
    pass  # Still restart app

if os.name == "nt":
    subprocess.Popen(
        launch_cmd,
        creationflags=subprocess.CREATE_NEW_PROCESS | subprocess.DETACHED_PROCESS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=repo_root,
    )
    sys.exit(0)
else:
    os.chdir(repo_root)
    os.execv(launch_cmd[0], launch_cmd)
'''
        fd, path = tempfile.mkstemp(suffix=".py")
        try:
            try:
                os.write(fd, helper_body.encode("utf-8"))
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
            py_exe = sys.executable
            cmd = [py_exe, path, repo_root] + launch_cmd
            if platform.system() == "Windows":
                subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_PROCESS | subprocess.DETACHED_PROCESS,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(path),
                )
            else:
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=os.path.dirname(path),
                )
        finally:
            pass  # Temp file left for child to read; OS cleans on reboot

    def _spawn_aur_updater(self, helper: str | None, term: str | None, launch_cmd: list):
        """Spawn process that runs AUR update then restarts app."""
        try:
            from core.debug_logger import debug, UTILITY_APP
            debug(UTILITY_APP, f"AUR updater: spawning terminal={term or 'none'}, helper={helper or 'pkexec pacman'}")
        except Exception:
            pass
        if helper:
            update_cmd = f"{helper} -Sy chronoarchiver"
        else:
            update_cmd = "pkexec pacman -Sy chronoarchiver"
        launch_str = " ".join(repr(c) for c in launch_cmd)
        script_body = f"""#!/bin/bash
sleep 2
if {update_cmd}; then
  setsid nohup {launch_str} </dev/null >/dev/null 2>&1 &
  disown -a 2>/dev/null || true
  sleep 3
  exit 0
else
  echo "Update failed. Press Enter to close."
  read -r
  exit 1
fi
"""
        fd, script_path = tempfile.mkstemp(suffix=".sh")
        try:
            try:
                os.write(fd, script_body.encode("utf-8"))
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
            os.chmod(script_path, 0o755)  # nosec B103 — update script needs execute
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
                os.close(fd)
            except (OSError, NameError):
                pass
            try:
                os.unlink(script_path)
            except Exception:
                pass
