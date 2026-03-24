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
    return os.environ.get("CHRONOARCHIVER_VERSION", "3.7.4")


VERSION = _read_version()
GITHUB_RELEASES = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/tags/v{version}"


def _app_dir() -> Path:
    """Install root: %LOCALAPPDATA%\\ChronoArchiver (Windows) or ~/Library/Application Support/ChronoArchiver (macOS)."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(base) / "ChronoArchiver"
    return Path.home() / "Library" / "Application Support" / "ChronoArchiver"


def _version_file() -> Path:
    return _app_dir() / "version.txt"


def _is_installed() -> bool:
    """True if app is already installed and matches our version."""
    vf = _version_file()
    if not vf.exists():
        return False
    try:
        return vf.read_text().strip() == VERSION
    except Exception:
        return False


def _launcher_exists() -> bool:
    """True if chronoarchiver.pyw exists."""
    return (_app_dir() / "chronoarchiver.pyw").is_file()


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


def _parse_requirements(req_path: Path) -> list[str]:
    """Parse requirements.txt into list of package names (strip comments, -r, empty)."""
    if not req_path.exists():
        return []
    packages = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        pkg = line.split("==")[0].split("[")[0].strip()
        if pkg:
            packages.append(pkg)
    return packages


def _run_setup_bootstrap(app_root: Path, progress_cb) -> bool:
    """Create venv, install each package with progress, verify before returning."""
    import re
    venv = app_root / "venv"
    if platform.system() == "Windows":
        py_exe = venv / "Scripts" / "python.exe"
        pip_exe = venv / "Scripts" / "pip.exe"
    else:
        py_exe = venv / "bin" / "python"
        pip_exe = venv / "bin" / "pip"

    # Skip only if venv exists and passes import check
    if py_exe.exists():
        try:
            r = subprocess.run(
                [str(py_exe), "-c", "import PySide6; import numpy; import PIL; import requests"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass

    py_sys = shutil.which("python3") or shutil.which("python")
    if not py_sys:
        progress_cb("Python not found", 0, 0, 0)
        return False

    progress_cb("Creating virtual environment…", 0, 0, 0)
    try:
        subprocess.run([py_sys, "-m", "venv", str(venv)], capture_output=True, timeout=90, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        progress_cb("venv creation failed", 0, 0, 0)
        return False

    if not pip_exe.exists():
        progress_cb("pip not found in venv", 0, 0, 0)
        return False

    packages = _parse_requirements(app_root / "requirements.txt")
    if not packages:
        progress_cb("No packages in requirements.txt", 0, 0, 0)
        return False

    n = len(packages)
    for i, pkg in enumerate(packages):
        base_pct = 100.0 * i / n
        pkg_display = f"{pkg} ({i + 1}/{n})"

        def _update(detail: str = "", sub_pct: float = 0):
            pct = base_pct + (100.0 / n) * sub_pct / 100
            progress_cb(pkg_display, pct, 0, 0, detail)

        _update("Installing…", 0)
        proc = subprocess.Popen(
            [str(pip_exe), "install", pkg, "--disable-pip-version-check"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            cwd=str(app_root),
        )
        start = time.time()
        last_update = [0]
        for line in iter(proc.stdout.readline, "") if proc.stdout else []:
            line = (line or "").strip()
            if not line:
                continue
            # Parse "  Downloading X (Y MB)" or "     -------- 12.3/45.6 MB 1.2 MB/s"
            m = re.search(r"(\d+\.?\d*)\s*/\s*(\d+\.?\d*)\s*MB", line)
            if m:
                a, b = float(m.group(1)), float(m.group(2))
                sub_pct = (a / b * 100) if b > 0 else 0
                speed_m = re.search(r"(\d+\.?\d*)\s*MB/s", line)
                speed = float(speed_m.group(1)) if speed_m else 0
                now = time.time()
                if now - last_update[0] >= 0.3:
                    last_update[0] = now
                    progress_cb(pkg_display, base_pct + (100.0 / n) * sub_pct / 100, speed, a, line[:80])
            elif "Downloading" in line or "Collecting" in line:
                progress_cb(pkg_display, base_pct, 0, 0, line[:80])

        try:
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            progress_cb(f"Timeout: {pkg}", 0, 0, 0)
            return False
        if proc.returncode != 0:
            progress_cb(f"Failed: {pkg}", 0, 0, 0)
            return False
        progress_cb(pkg_display, base_pct + 100.0 / n, 0, 0, "OK")

    progress_cb("Verifying…", 98, 0, 0)
    try:
        r = subprocess.run(
            [str(py_exe), "-c", "import PySide6; import numpy; import PIL; import requests"],
            capture_output=True, timeout=15,
        )
        if r.returncode != 0:
            progress_cb("Verification failed", 0, 0, 0)
            return False
    except Exception:
        return False
    progress_cb("Done", 100, 0, 0)
    return True


def _create_windows_shortcuts(app_root: Path):
    """Create desktop shortcut, Start Menu shortcut, and uninstaller. Uses pythonw (no console)."""
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if not start_menu.exists():
        return
    folder = start_menu / "ChronoArchiver"
    folder.mkdir(exist_ok=True)

    app_root_str = str(app_root).replace("\\", "\\\\")
    venv_pyw = app_root / "venv" / "Scripts" / "pythonw.exe"
    launcher_pyw = app_root / "chronoarchiver.pyw"

    # Launcher VBS: runs pythonw with no console; uses venv if exists, else system
    launcher_vbs = app_root / "launcher.vbs"
    launcher_vbs.write_text(f'''Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
appRoot = "{app_root_str}"
venvPyw = appRoot & "\\venv\\Scripts\\pythonw.exe"
launcher = appRoot & "\\chronoarchiver.pyw"
If FSO.FileExists(venvPyw) Then
    WshShell.CurrentDirectory = appRoot
    WshShell.Run """" & venvPyw & """ """ & launcher & """", 0, False
Else
    WshShell.CurrentDirectory = appRoot
    WshShell.Run "pythonw """ & launcher & """", 0, False
End If
''', encoding="utf-8")

    icon_path = app_root / "src" / "ui" / "assets" / "icon.ico"
    icon_str = str(icon_path) if icon_path.exists() else ""

    def create_shortcut(target_path: Path, name: str):
        ps = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{target_path}\\{name}.lnk")
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = '"{launcher_vbs}"'
$Shortcut.WorkingDirectory = "{app_root}"
$Shortcut.Description = "ChronoArchiver"
''' + (f'$Shortcut.IconLocation = "{icon_str.replace(chr(92), chr(92)*2)}"\n' if icon_str else "") + '''
$Shortcut.Save()
'''.replace("{target_path}", str(target_path)).replace("{name}", name).replace("{launcher_vbs}", str(launcher_vbs)).replace("{app_root}", str(app_root))
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10)
        except Exception:
            pass

    create_shortcut(desktop, "ChronoArchiver")
    create_shortcut(folder, "ChronoArchiver")

    # Uninstaller VBS: removes install dir and all contents
    install_dir = str(_app_dir()).replace("\\", "\\\\")
    uninstall_vbs = folder / "Uninstall ChronoArchiver.vbs"
    uninstall_vbs.write_text(f'''result = MsgBox("Remove ChronoArchiver and all its data?", vbYesNo + vbQuestion, "Uninstall ChronoArchiver")
If result = vbYes Then
    Set FSO = CreateObject("Scripting.FileSystemObject")
    On Error Resume Next
    FSO.DeleteFolder "{install_dir}", True
    On Error Goto 0
    MsgBox "ChronoArchiver has been uninstalled.", vbInformation, "Uninstall Complete"
End If
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
elif command -v python3 >/dev/null 2>&1; then
    exec python3 chronoarchiver.pyw "$@"
else
    exec python chronoarchiver.pyw "$@"
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
    install_dir = str(_app_dir())
    uninstall = app_root / "Uninstall ChronoArchiver.command"
    uninstall.write_text(f'''#!/bin/bash
echo "Uninstalling ChronoArchiver..."
rm -rf "{install_dir}"
echo "Done."
''')
    uninstall.chmod(0o755)


def _run_app(app_root: Path):
    """Launch the installed Python app (no console window)."""
    if platform.system() == "Windows":
        launcher_vbs = app_root / "launcher.vbs"
        if launcher_vbs.exists():
            subprocess.Popen(
                ["wscript.exe", str(launcher_vbs)],
                cwd=str(app_root),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            pyw = app_root / "venv" / "Scripts" / "pythonw.exe"
            launcher = app_root / "chronoarchiver.pyw"
            cmd = [str(pyw), str(launcher)] if pyw.exists() else ["pythonw", str(launcher)]
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
        from tkinter import messagebox, ttk
    except ImportError:
        print("ChronoArchiver: tkinter required for setup UI.")
        return False

    url = _download_url()
    if not url:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ChronoArchiver", f"Could not find download for v{VERSION}. Check your connection.")
        root.destroy()
        return False

    root = tk.Tk()
    root.title("ChronoArchiver — Setup")
    root.geometry("520x380")
    root.resizable(False, False)
    root.configure(bg="#0d0d0d")
    root.option_add("*Font", "TkDefaultFont 9")

    lbl_title = tk.Label(root, text="Downloading ChronoArchiver…", fg="#e5e7eb", bg="#0d0d0d", font=("", 11, "bold"))
    lbl_title.pack(pady=(16, 6))
    lbl_component = tk.Label(root, text="ChronoArchiver (Python source)", fg="#9ca3af", bg="#0d0d0d", wraplength=480)
    lbl_component.pack(pady=2)
    lbl_detail = tk.Label(root, text="", fg="#6b7280", bg="#0d0d0d", font=("", 8), wraplength=480)
    lbl_detail.pack(pady=2)
    lbl_speed = tk.Label(root, text="", fg="#10b981", bg="#0d0d0d")
    lbl_speed.pack(pady=2)
    prog = ttk.Progressbar(root, length=460, mode="determinate")
    prog.pack(pady=8)
    lbl_pct = tk.Label(root, text="0%", fg="#6b7280", bg="#0d0d0d")
    lbl_pct.pack(pady=2)

    result = [False]
    done = [False]

    def progress_cb(component, pct, speed_mbps, size_mb, detail=""):
        def update():
            lbl_component.config(text=component)
            lbl_detail.config(text=detail[:100] if detail else "")
            prog["value"] = min(100, max(0, pct))
            lbl_pct.config(text=f"{pct:.1f}%")
            if speed_mbps >= 0.01:
                lbl_speed.config(text=f"{speed_mbps:.2f} MB/s  ·  {size_mb:.1f} MB")
            else:
                lbl_speed.config(text="")
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
            if not _run_setup_bootstrap(app_dir, progress_cb):
                result[0] = False
                done[0] = True
                return
            progress_cb("Creating shortcuts…", 98, 0, 0)
            if platform.system() == "Windows":
                _create_windows_shortcuts(app_dir)
            else:
                _create_macos_app_and_uninstaller(app_dir)
            _app_dir().mkdir(parents=True, exist_ok=True)
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
        messagebox.showerror("ChronoArchiver", "Setup failed. Check your internet connection and that Python 3.11+ is installed.")
        root2.destroy()
        return False
    return True


def main():
    if _is_installed() and _launcher_exists():
        _run_app(_app_dir())
        return
    if _do_setup_gui():
        _run_app(_app_dir())


if __name__ == "__main__":
    main()
