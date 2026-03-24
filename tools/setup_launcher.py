"""
ChronoArchiver Setup Launcher — Minimal bootstrap (~6MB) that downloads Python source on first run.
Installs as .pyw/pythonw (no native compile). Uses stdlib: tkinter, urllib, zipfile.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

# Version embedded at build time via version.txt in bundle
def _read_version() -> str:
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        for name in ("_setup_version.txt", "version.txt"):
            vpath = os.path.join(base, name)
            if os.path.isfile(vpath):
                return open(vpath, "r", encoding="utf-8").read().strip()
    except Exception:
        pass
    return os.environ.get("CHRONOARCHIVER_VERSION", "3.7.0")


VERSION = _read_version()
GITHUB_RELEASES = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/tags/v{version}"


def _app_dir() -> Path:
    """App installation directory (AppData on Windows, ~/Library on macOS)."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(base) / "ChronoArchiver" / "app"
    return Path.home() / "Library" / "Application Support" / "ChronoArchiver" / "app"


def _version_file() -> Path:
    return _app_dir().parent / "version.txt"


def _is_installed() -> bool:
    """True if app is already installed and matches our version."""
    vf = _version_file()
    if not vf.exists():
        return False
    try:
        return vf.read_text().strip() == VERSION
    except Exception:
        return False


def _app_root() -> Path:
    """Effective app root (may be app_dir/ChronoArchiver when zip has that structure)."""
    d = _app_dir()
    inner = d / "ChronoArchiver" / "chronoarchiver.pyw"
    return d / "ChronoArchiver" if inner.exists() else d


def _launcher_exists() -> bool:
    """True if chronoarchiver.pyw exists."""
    root = _app_root()
    return (root / "chronoarchiver.pyw").is_file()


def _download_url() -> str:
    """Get download URL for source zip from GitHub releases (same for win/mac)."""
    url = GITHUB_RELEASES.format(version=VERSION)
    expected_name = f"ChronoArchiver-{VERSION}-src.zip"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ChronoArchiver-Setup", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        for a in data.get("assets", []):
            if a.get("name") == expected_name:
                return a.get("browser_download_url", "")
    except Exception:
        pass
    return ""


def _download_with_progress(url: str, dest_path: str, progress_cb) -> bool:
    """Stream download with progress. progress_cb(component, pct, speed_mbps, size_mb)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ChronoArchiver-Setup"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
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
                    speed = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    pct = (100.0 * downloaded / total) if total > 0 else 0
                    size_mb = downloaded / (1024 * 1024)
                    progress_cb("ChronoArchiver", min(100.0, pct), speed, size_mb)
        return True
    except Exception:
        return False


def _create_windows_shortcuts(app_root: Path):
    """Create Start Menu shortcut and uninstaller."""
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if not start_menu.exists():
        return
    folder = start_menu / "ChronoArchiver"
    folder.mkdir(exist_ok=True)

    app_dir_str = str(app_root).replace('"', '""')
    # Launcher batch
    bat = folder / "ChronoArchiver.bat"
    bat.write_text(f'''@echo off
cd /d "{app_dir_str}"
pythonw chronoarchiver.pyw 2>nul || py -3 chronoarchiver.pyw 2>nul || python chronoarchiver.pyw
if errorlevel 1 (
    echo ChronoArchiver requires Python 3.11+. Install from python.org
    pause
)
''', encoding="utf-8")

    # Uninstaller batch (remove whole ChronoArchiver install)
    parent = str(_app_dir().parent).replace('"', '""')
    uninstall_bat = folder / "Uninstall ChronoArchiver.bat"
    uninstall_bat.write_text(f'''@echo off
echo Uninstalling ChronoArchiver...
rmdir /s /q "{parent}" 2>nul
echo Done. You may close this window.
pause
''', encoding="utf-8")


def _create_macos_app_and_uninstaller(app_root: Path):
    """Create ChronoArchiver.app launcher and Uninstall script."""
    app_bundle = app_root / "ChronoArchiver.app"
    contents = app_bundle / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    launcher_script = macos / "ChronoArchiver"
    launcher_script.write_text(f'''#!/bin/bash
cd "{app_root}"
export CHRONOARCHIVER_INSTALL_ROOT="{app_root}"
if [ -x "venv/bin/python" ]; then
    exec venv/bin/python chronoarchiver.pyw "$@"
else
    exec python3 chronoarchiver.pyw "$@"
fi
''')
    launcher_script.chmod(0o755)

    (contents / "Info.plist").write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>ChronoArchiver</string>
<key>CFBundleIdentifier</key><string>com.undadfeated.chronoarchiver</string>
<key>CFBundleName</key><string>ChronoArchiver</string>
<key>CFBundleVersion</key><string>{VERSION}</string>
</dict></plist>
''')

    # Uninstall script (remove whole ChronoArchiver install)
    parent = str(_app_dir().parent)
    uninstall = app_root / "Uninstall ChronoArchiver.command"
    uninstall.write_text(f'''#!/bin/bash
echo "Uninstalling ChronoArchiver..."
rm -rf "{parent}"
echo "Done."
''')
    uninstall.chmod(0o755)


def _run_app(app_root: Path):
    """Launch the installed Python app."""
    if platform.system() == "Windows":
        pyw = app_root / "venv" / "Scripts" / "pythonw.exe"
        launcher = app_root / "chronoarchiver.pyw"
        if pyw.exists():
            cmd = [str(pyw), str(launcher)]
        else:
            bat = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ChronoArchiver" / "ChronoArchiver.bat"
            if bat.exists():
                cmd = ["cmd", "/c", "start", "", str(bat)]
            else:
                cmd = ["pythonw", str(launcher)] if shutil.which("pythonw") else ["python", str(launcher)]
        flags = getattr(subprocess, "CREATE_NEW_PROCESS", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(cmd, cwd=str(app_root), creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        app_bundle = app_root / "ChronoArchiver.app"
        if app_bundle.exists():
            subprocess.Popen(["open", "-a", str(app_bundle)])
        else:
            subprocess.Popen(["python3", str(app_root / "chronoarchiver.pyw")], cwd=str(app_root), start_new_session=True)


def _do_setup_gui():
    """Show progress window, download, extract, create shortcuts, launch."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("ChronoArchiver: tkinter required for setup UI.")
        return False

    url = _download_url()
    if not url:
        root = tk.Tk()
        root.withdraw()
        tk.messagebox.showerror("ChronoArchiver", f"Could not find download for v{VERSION}. Check your connection.")
        root.destroy()
        return False

    root = tk.Tk()
    root.title("ChronoArchiver — Setup")
    root.geometry("480x220")
    root.resizable(False, False)
    root.configure(bg="#0d0d0d")
    root.option_add("*Font", "TkDefaultFont 9")

    lbl_title = tk.Label(root, text="Downloading ChronoArchiver…", fg="#e5e7eb", bg="#0d0d0d", font=("", 11, "bold"))
    lbl_title.pack(pady=(20, 8))
    lbl_component = tk.Label(root, text="ChronoArchiver (Python source)", fg="#9ca3af", bg="#0d0d0d")
    lbl_component.pack(pady=2)
    lbl_speed = tk.Label(root, text="", fg="#10b981", bg="#0d0d0d")
    lbl_speed.pack(pady=2)
    prog = ttk.Progressbar(root, length=420, mode="determinate")
    prog.pack(pady=12)
    lbl_pct = tk.Label(root, text="0%", fg="#6b7280", bg="#0d0d0d")
    lbl_pct.pack(pady=2)

    result = [False]
    done = [False]

    def progress_cb(component, pct, speed_mbps, size_mb):
        def update():
            lbl_component.config(text=component)
            prog["value"] = min(100, pct)
            lbl_pct.config(text=f"{pct:.1f}%")
            if speed_mbps >= 0.01:
                lbl_speed.config(text=f"{speed_mbps:.2f} MB/s  ·  {size_mb:.1f} MB")
            root.update_idletasks()
        root.after(0, update)

    def task():
        try:
            app_dir = _app_dir()
            app_dir.mkdir(parents=True, exist_ok=True)
            fd, zip_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            if not _download_with_progress(url, zip_path, progress_cb):
                result[0] = False
                done[0] = True
                return
            progress_cb("Extracting…", 90, 0, 0)
            if app_dir.exists():
                shutil.rmtree(app_dir)
            app_dir.mkdir(parents=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                for m in zf.namelist():
                    rel = m[len("ChronoArchiver/"):] if m.startswith("ChronoArchiver/") and m != "ChronoArchiver/" else m
                    if not rel or rel.startswith(".") or "__MACOSX" in rel or rel.startswith("tools/"):
                        continue
                    dest = app_dir / rel
                    if m.endswith("/"):
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(m) as src, open(dest, "wb") as out:
                            out.write(src.read())
            try:
                os.remove(zip_path)
            except OSError:
                pass
            progress_cb("Creating shortcuts…", 95, 0, 0)
            app_root = app_dir / "ChronoArchiver" if (app_dir / "ChronoArchiver" / "chronoarchiver.pyw").exists() else app_dir
            if platform.system() == "Windows":
                _create_windows_shortcuts(app_root)
            else:
                _create_macos_app_and_uninstaller(app_root)
            _version_file().parent.mkdir(parents=True, exist_ok=True)
            _version_file().write_text(VERSION)
            result[0] = True
        except Exception:
            result[0] = False
        done[0] = True

    def poll():
        if done[0]:
            root.quit()
            return
        root.after(100, poll)

    threading.Thread(target=task, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    root.destroy()

    if not result[0]:
        root2 = tk.Tk()
        root2.withdraw()
        tk.messagebox.showerror("ChronoArchiver", "Download or extraction failed. Check your connection.")
        root2.destroy()
        return False
    return True


def main():
    if _is_installed() and _launcher_exists():
        _run_app(_app_root())
        return
    if _do_setup_gui():
        _run_app(_app_root())


if __name__ == "__main__":
    main()
