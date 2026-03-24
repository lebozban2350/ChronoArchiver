"""
ChronoArchiver Setup Launcher — Minimal bootstrap (~6MB) that downloads Python source on first run.
Installs as .pyw/pythonw (no native compile). Uses stdlib: tkinter, urllib, zipfile.

Updates: merge-extract into the install dir (preserves venv), skip re-downloading the source zip when
installed src/version.py already matches this setup's version, and run pip install -r on existing
venvs so new requirements are applied without wiping site-packages. Merge skips only byte-identical
files (MD5), not same-size-only — avoids stale src/version.py when patch digits change without size change.
Welcome screen with logo; optional ChronoArchiver_installer.log beside the setup exe (appends sessions).
"""
import hashlib
import json
import os
import platform
import re
import traceback
from datetime import datetime
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
    return os.environ.get("CHRONOARCHIVER_VERSION", "3.7.11")


VERSION = _read_version()
GITHUB_RELEASES = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/tags/v{version}"

# Optional file log (ChronoArchiver_installer.log next to setup exe when enabled from welcome screen)
_INSTALL_LOG_FILE: Path | None = None


def _installer_asset_path(name: str) -> Path | None:
    """
    Bundled setup assets (icon.png / icon.ico) live next to the frozen exe (PyInstaller MEIPASS)
    or under src/ui/assets when running from source.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            p = Path(base) / name
            if p.is_file():
                return p
        return None
    # tools/setup_launcher.py -> repo root -> src/ui/assets
    here = Path(__file__).resolve()
    p = here.parent.parent / "src" / "ui" / "assets" / name
    return p if p.is_file() else None


def _welcome_logo_photo(master) -> object | None:
    """
    Load PNG for welcome header at ~56px width (~half README inline size), aspect ratio preserved.
    Returns tk.PhotoImage or None; caller must keep a reference on the window to avoid GC.
    """
    path = _installer_asset_path("icon.png")
    if not path:
        return None
    try:
        import tkinter as tk
    except ImportError:
        return None
    try:
        img = tk.PhotoImage(master=master, file=str(path))
    except tk.TclError:
        return None
    # Target max width; subsample divides W/H equally — no stretching.
    tw = 56
    w = img.width()
    if w > tw:
        factor = max(1, (w + tw - 1) // tw)
        img = img.subsample(factor, factor)
    return img


def _installer_log_dir() -> Path:
    """Directory containing the setup executable (frozen) or this script (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _setup_install_logging(enabled: bool) -> None:
    global _INSTALL_LOG_FILE
    if not enabled:
        _INSTALL_LOG_FILE = None
        return
    p = _installer_log_dir() / "ChronoArchiver_installer.log"
    try:
        # ASCII in header avoids mojibake in some Windows viewers; BOM on first create helps Notepad UTF-8.
        header = (
            f"ChronoArchiver installer log - v{VERSION}\n"
            f"Started {datetime.now().isoformat(timespec='seconds')}\n"
            f"frozen={getattr(sys, 'frozen', False)} executable={sys.executable!r}\n"
            f"platform={platform.system()} {platform.release()} python={sys.version.split()[0]}\n\n"
        )
        if p.is_file():
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n\n")
                f.write("=" * 72 + "\n")
                f.write(f"--- session start v{VERSION} ---\n")
                f.write(header)
        else:
            p.write_text("\ufeff" + header, encoding="utf-8")
        _INSTALL_LOG_FILE = p
    except OSError:
        _INSTALL_LOG_FILE = None


def _install_log(msg: str) -> None:
    if _INSTALL_LOG_FILE is None:
        return
    try:
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}\n"
        with open(_INSTALL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _install_log_chunk(title: str, text: str, max_chars: int = 12000) -> None:
    """Append a multi-line block (e.g. pip output); each line prefixed for grep-friendly logs."""
    if _INSTALL_LOG_FILE is None:
        return
    body = (text or "")[-max_chars:] if len(text or "") > max_chars else (text or "")
    _install_log(f"--- {title} ({len(body)} chars) ---")
    for ln in body.splitlines():
        _install_log(f"  | {ln}")
    _install_log(f"--- end {title} ---")


def _install_log_footer(ok: bool, detail: str = "") -> None:
    """Final SUCCESS/FAILURE banner for tail-scanning log files."""
    if _INSTALL_LOG_FILE is None:
        return
    ts = datetime.now().isoformat(timespec="seconds")
    status = "SUCCESS" if ok else "FAILURE"
    line = f"INSTALLER RESULT: {status}"
    if detail:
        line += f" ({detail})"
    try:
        with open(_INSTALL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write("=" * 72 + "\n")
            f.write(line + "\n")
            f.write(f"Logged at {ts}\n")
            f.write("=" * 72 + "\n")
    except OSError:
        pass


def _md5_digest_stream(fobj) -> bytes:
    h = hashlib.md5()
    while True:
        b = fobj.read(65536)
        if not b:
            break
        h.update(b)
    return h.digest()


def _dest_matches_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> bool:
    """True if on-disk file is byte-identical to zip member (not just same size)."""
    if not dest.is_file():
        return False
    if dest.stat().st_size != info.file_size:
        return False
    if info.file_size > 32 * 1024 * 1024:
        return True
    try:
        with open(dest, "rb") as df:
            d = _md5_digest_stream(df)
        with zf.open(info) as zr:
            z = _md5_digest_stream(zr)
        return d == z
    except Exception:
        return False


def _purge_src_pycache(app_dir: Path) -> None:
    """Remove stale bytecode so a bumped src/version.py cannot load old __pycache__."""
    src = app_dir / "src"
    if not src.is_dir():
        return
    removed = 0
    for p in list(src.rglob("__pycache__")):
        if p.is_dir():
            try:
                shutil.rmtree(p)
                removed += 1
            except OSError:
                pass
    if removed:
        _install_log(f"purge __pycache__: removed {removed} dir(s) under src/")


def _app_dir() -> Path:
    """Install root: %LOCALAPPDATA%\\ChronoArchiver (Windows) or ~/Library/Application Support/ChronoArchiver (macOS)."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(base) / "ChronoArchiver"
    return Path.home() / "Library" / "Application Support" / "ChronoArchiver"


def _version_file() -> Path:
    return _app_dir() / "version.txt"


def _can_launch_without_setup(app_dir: Path | None = None) -> bool:
    """
    True only when the install tree already contains this setup's source (src/version.py).
    Do not use version.txt alone — it can get ahead of a failed/partial upgrade and would
    skip downloading/extracting while leaving an older app (e.g. 3.7.7 UI with 3.7.11 stamp).
    """
    root = app_dir if app_dir is not None else _app_dir()
    return _should_skip_source_zip(root)


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
    _install_log(f"download: GET {url}")
    _install_log(f"download: dest_path={dest_path!r}")
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
        _install_log("download: completed OK")
        return True
    except Exception as e:
        _install_log(f"download: EXCEPTION {type(e).__name__}: {e!r}")
        _install_log_chunk("download traceback", traceback.format_exc(), 6000)
        return False


def _read_source_version(app_root: Path) -> str | None:
    """Parse __version__ from installed src/version.py (if present)."""
    vp = app_root / "src" / "version.py"
    if not vp.is_file():
        return None
    try:
        txt = vp.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', txt, re.MULTILINE)
    return m.group(1).strip() if m else None


def _should_skip_source_zip(app_root: Path) -> bool:
    """True when install tree already contains this release's source — skip GitHub zip download."""
    if not (app_root / "chronoarchiver.pyw").is_file():
        return False
    if not (app_root / "requirements.txt").is_file():
        return False
    return _read_source_version(app_root) == VERSION


def _zip_relative_dest(member: str) -> str | None:
    """Map zip entry to path under install root, or None to skip."""
    if member.startswith("ChronoArchiver/") and len(member) > len("ChronoArchiver/"):
        rel = member[len("ChronoArchiver/") :].rstrip("/")
    else:
        rel = member.rstrip("/")
    if not rel or rel.startswith(".") or "__MACOSX" in rel:
        return None
    if rel.startswith("tools/"):
        return None
    if rel == "venv" or rel.startswith("venv/"):
        return None
    return rel


def _extract_source_zip_merged(zip_path: str, app_dir: Path, progress_cb) -> None:
    """Unpack source zip over existing install without deleting venv; skip only byte-identical files."""
    app_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = [zi for zi in zf.infolist() if _zip_relative_dest(zi.filename) is not None]
        n = max(1, len(infos))
        for i, info in enumerate(infos):
            rel = _zip_relative_dest(info.filename)
            if rel is None:
                continue
            dest = app_dir / rel
            pct = 100.0 * (i + 1) / n
            if info.is_dir() or info.filename.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                progress_cb("Extracting…", pct, 0, 0, rel[:72])
                continue
            if _dest_matches_zip_member(zf, info, dest):
                skipped += 1
                _install_log(f"extract skip identical: {rel} ({info.file_size} B)")
                progress_cb("Extracting…", pct, 0, 0, f"skip {rel[:48]}")
                continue
            written += 1
            _install_log(f"extract write: {rel} ({info.file_size} B)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out_f:
                shutil.copyfileobj(src, out_f)
            progress_cb("Extracting…", pct, 0, 0, rel[:72])
    _install_log(f"extract summary: wrote {written}, skipped_identical {skipped}")
    _purge_src_pycache(app_dir)


def _venv_import_ok(py_exe: Path) -> bool:
    try:
        r = subprocess.run(
            [str(py_exe), "-c", "import PySide6; import numpy; import PIL; import requests"],
            capture_output=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _pip_sync_requirements(app_root: Path, pip_exe: Path, progress_cb) -> tuple[bool, str]:
    """pip install -r requirements.txt — idempotent; picks up new deps on upgrade."""
    req = app_root / "requirements.txt"
    if not req.exists():
        return False, "requirements.txt missing"
    proc = subprocess.Popen(
        [str(pip_exe), "install", "-r", str(req), "--disable-pip-version-check"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(app_root),
    )
    pip_capture: list[str] = []
    last_update = [0.0]
    prev_bytes = [0.0]
    prev_time = [time.time()]
    for line in iter(proc.stdout.readline, "") if proc.stdout else []:
        pip_capture.append((line or "").rstrip("\n"))
        line = (line or "").strip()
        if not line:
            continue
        m = re.search(r"(\d+\.?\d*)\s*/\s*(\d+\.?\d*)\s*MB", line)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            sub_pct = (a / b * 100) if b > 0 else 50
            speed_m = re.search(r"(\d+\.?\d*)\s*MB/s", line)
            speed = float(speed_m.group(1)) if speed_m else 0.0
            if speed < 0.01:
                now = time.time()
                dt = max(0.001, now - prev_time[0])
                speed = max(0.0, (a - prev_bytes[0]) / dt)
                prev_time[0] = now
                prev_bytes[0] = a
            now = time.time()
            if now - last_update[0] >= 0.25:
                last_update[0] = now
                progress_cb("requirements.txt", min(99.0, sub_pct), speed, a, line[:100])
        elif "Downloading" in line or "Collecting" in line or "Installing" in line:
            progress_cb("requirements.txt", 5, 0, 0, line[:100])
    try:
        proc.wait(timeout=1200)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        _install_log("pip install -r: timed out")
        _install_log_chunk("pip install -r output (full)", "\n".join(pip_capture), 12000)
        return False, "pip install -r timed out."
    if proc.returncode != 0:
        _install_log(f"pip install -r: exit code {proc.returncode}")
        _install_log_chunk("pip install -r output (tail)", "\n".join(pip_capture), 12000)
        return False, "pip install -r failed (see log)."
    progress_cb("requirements.txt", 100, 0, 0, "OK")
    return True, ""


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


def _find_system_python() -> list[str] | None:
    """Return command prefix for a usable Python 3.11+ interpreter."""
    candidates: list[list[str]] = []
    if platform.system() == "Windows":
        candidates.extend([["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], ["python"], ["python3"]])
    else:
        candidates.extend([["python3"], ["python"]])
    for cmd in candidates:
        try:
            r = subprocess.run(cmd + ["-c", "import sys; print(sys.version_info[:2])"], capture_output=True, timeout=8)
            if r.returncode == 0:
                return cmd
        except Exception:
            continue
    return None


def _run_setup_bootstrap(app_root: Path, progress_cb) -> tuple[bool, str]:
    """Ensure venv exists and requirements are satisfied; reuse healthy venv and sync via pip -r."""
    _install_log(f"bootstrap: app_root={app_root}")
    venv = app_root / "venv"
    win = platform.system() == "Windows"
    if win:
        py_exe = venv / "Scripts" / "python.exe"
        pip_exe = venv / "Scripts" / "pip.exe"
    else:
        py_exe = venv / "bin" / "python"
        pip_exe = venv / "bin" / "pip"

    if py_exe.exists() and pip_exe.exists() and _venv_import_ok(py_exe):
        progress_cb("Syncing dependencies…", 0, 0, 0, "pip install -r requirements.txt")
        ok, err = _pip_sync_requirements(app_root, pip_exe, progress_cb)
        if ok and _venv_import_ok(py_exe):
            progress_cb("Done", 100, 0, 0)
            return True, ""
        if ok:
            err = "Dependency verification failed after pip sync."
            _install_log("bootstrap: pip sync OK but _venv_import_ok failed after sync")
        progress_cb("Replacing virtual environment…", 0, 0, 0, (err or "")[:100])
        try:
            shutil.rmtree(venv)
        except OSError:
            pass
    elif venv.exists():
        progress_cb("Removing incomplete virtual environment…", 0, 0, 0)
        try:
            shutil.rmtree(venv)
        except OSError:
            pass

    py_cmd = _find_system_python()
    if not py_cmd:
        progress_cb("Python not found", 0, 0, 0, "Install Python 3.11+ from python.org")
        return False, "Python 3.11+ not found on PATH (or via py launcher)."

    progress_cb("Creating virtual environment…", 0, 0, 0)
    try:
        subprocess.run(py_cmd + ["-m", "venv", str(venv)], capture_output=True, timeout=120, check=True)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or "venv failed").decode("utf-8", errors="ignore") if isinstance((e.stderr or e.stdout), bytes) else (e.stderr or e.stdout or "venv failed")
        progress_cb("venv creation failed", 0, 0, 0, str(msg)[:120])
        _install_log(f"venv creation: exit {e.returncode} cmd={py_cmd + ['-m', 'venv', str(venv)]!r}")
        _install_log_chunk("venv creation stderr/stdout", str(msg), 8000)
        return False, f"venv creation failed: {str(msg)[:500]}"
    except subprocess.TimeoutExpired:
        progress_cb("venv creation failed", 0, 0, 0)
        return False, "venv creation timed out."

    if not pip_exe.exists():
        progress_cb("pip not found in venv", 0, 0, 0)
        return False, "pip not found in created virtual environment."

    packages = _parse_requirements(app_root / "requirements.txt")
    if not packages:
        progress_cb("No packages in requirements.txt", 0, 0, 0)
        return False, "requirements.txt is empty or unreadable."

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
        pkg_lines: list[str] = []
        last_update = [0.0]
        prev_bytes = [0.0]
        prev_time = [time.time()]
        for line in iter(proc.stdout.readline, "") if proc.stdout else []:
            pkg_lines.append((line or "").rstrip("\n"))
            line = (line or "").strip()
            if not line:
                continue
            # Parse "  Downloading X (Y MB)" or "     -------- 12.3/45.6 MB 1.2 MB/s"
            m = re.search(r"(\d+\.?\d*)\s*/\s*(\d+\.?\d*)\s*MB", line)
            if m:
                a, b = float(m.group(1)), float(m.group(2))
                sub_pct = (a / b * 100) if b > 0 else 0
                speed_m = re.search(r"(\d+\.?\d*)\s*MB/s", line)
                if speed_m:
                    speed = float(speed_m.group(1))
                else:
                    now = time.time()
                    dt = max(0.001, now - prev_time[0])
                    speed = max(0.0, (a - prev_bytes[0]) / dt)
                    prev_time[0] = now
                    prev_bytes[0] = a
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
            _install_log_chunk(f"pip install timeout package={pkg}", "\n".join(pkg_lines), 8000)
            return False, f"pip install timed out for {pkg}."
        if proc.returncode != 0:
            progress_cb(f"Failed: {pkg}", 0, 0, 0)
            _install_log(f"pip install package={pkg!r} exit code {proc.returncode}")
            _install_log_chunk(f"pip install output package={pkg}", "\n".join(pkg_lines), 12000)
            return False, f"pip install failed for {pkg}."
        progress_cb(pkg_display, base_pct + 100.0 / n, 0, 0, "OK")

    progress_cb("Verifying…", 98, 0, 0)
    try:
        r = subprocess.run(
            [str(py_exe), "-c", "import PySide6; import numpy; import PIL; import requests"],
            capture_output=True,
            timeout=15,
        )
        if r.returncode != 0:
            progress_cb("Verification failed", 0, 0, 0)
            err_out = (r.stderr or b"").decode("utf-8", errors="replace") + (r.stdout or b"").decode(
                "utf-8", errors="replace"
            )
            _install_log_chunk("bootstrap verify imports stderr+stdout", err_out, 4000)
            return False, "Dependency verification failed after install."
    except Exception as e:
        _install_log(f"bootstrap verify: EXCEPTION {type(e).__name__}: {e!r}")
        return False, f"Verification exception: {e}"
    progress_cb("Done", 100, 0, 0)
    return True, ""


def _reg_sz_quoted_path(p: str) -> str:
    """REG_SZ value for paths that may contain spaces (e.g. Start Menu, user name)."""
    p = p.strip()
    if not p:
        return p
    return p if (p.startswith('"') and p.endswith('"')) else f'"{p}"'


def _windows_uninstall_registry_command(uninstall_bat: Path) -> str:
    """
    Full command line for UninstallString so Settings → Apps works when paths contain spaces.
    Using cmd.exe /c ensures the .bat runs reliably when invoked from the shell.
    """
    comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
    return f'{_reg_sz_quoted_path(comspec)} /c {_reg_sz_quoted_path(str(uninstall_bat))}'


def _create_windows_shortcuts(app_root: Path):
    """Create desktop/start-menu shortcuts and uninstaller without VBS."""
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if not start_menu.exists():
        return
    folder = start_menu / "ChronoArchiver"
    folder.mkdir(exist_ok=True)

    venv_pyw = app_root / "venv" / "Scripts" / "pythonw.exe"
    launcher_pyw = app_root / "chronoarchiver.pyw"

    # Remove legacy VBS launcher if present
    try:
        old_launcher_vbs = app_root / "launcher.vbs"
        if old_launcher_vbs.exists():
            old_launcher_vbs.unlink()
    except OSError:
        pass

    icon_path = app_root / "src" / "ui" / "assets" / "icon.ico"
    icon_str = str(icon_path) if icon_path.exists() else ""

    def create_shortcut(target_path: Path, name: str):
        target_exe = str(venv_pyw) if venv_pyw.exists() else "pythonw.exe"
        ps = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{target_path}\\{name}.lnk")
$Shortcut.TargetPath = "{target_exe}"
$Shortcut.Arguments = '"{launcher_pyw}"'
$Shortcut.WorkingDirectory = "{app_root}"
$Shortcut.Description = "ChronoArchiver"
''' + (f'$Shortcut.IconLocation = "{icon_str.replace(chr(92), chr(92)*2)}"\n' if icon_str else "") + '''
$Shortcut.Save()
'''.replace("{target_path}", str(target_path)).replace("{name}", name).replace("{launcher_pyw}", str(launcher_pyw)).replace("{app_root}", str(app_root))
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10)
        except Exception:
            pass

    create_shortcut(desktop, "ChronoArchiver")
    create_shortcut(folder, "ChronoArchiver")

    # Remove legacy VBS uninstaller shortcut if present
    try:
        old_uninstall_vbs = folder / "Uninstall ChronoArchiver.vbs"
        if old_uninstall_vbs.exists():
            old_uninstall_vbs.unlink()
    except OSError:
        pass

    # Uninstaller CMD: lives under Start Menu (outside install dir so we can delete that tree first).
    # PowerShell confirm — works from Settings → Apps (no console; plain "choice" does not).
    install_dir = str(app_root.resolve())
    sm_ps = str(folder).replace("'", "''")
    desk_ps = str(desktop / "ChronoArchiver.lnk").replace("'", "''")
    uninstall_key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ChronoArchiver"
    uninstall_cmd = folder / "Uninstall ChronoArchiver.cmd"
    uninstall_cmd.write_text(
        f'''@echo off
setlocal
set "TARGET={install_dir}"
set "UNKEY={uninstall_key}"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $r=[System.Windows.Forms.MessageBox]::Show('Remove ChronoArchiver and all data from this PC?','ChronoArchiver Uninstall','YesNo','Question'); if ($r -ne [System.Windows.Forms.DialogResult]::Yes) {{ exit 1 }}"
if errorlevel 1 exit /b 0
if exist "%TARGET%" rmdir /S /Q "%TARGET%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '{desk_ps}') {{ Remove-Item -LiteralPath '{desk_ps}' -Force }}"
start "" /MIN powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; if (Test-Path -LiteralPath '{sm_ps}') {{ Remove-Item -LiteralPath '{sm_ps}' -Recurse -Force }}"
reg delete "%UNKEY%" /f >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('ChronoArchiver has been uninstalled.','ChronoArchiver','OK','Information')" 2>nul
exit /b 0
''',
        encoding="utf-8",
    )

    # Register in Windows Installed Apps (no admin required, HKCU)
    try:
        display_icon = str(icon_path) if icon_path.exists() else str(launcher_pyw)
        reg = uninstall_key
        uninstall_reg_cmd = _windows_uninstall_registry_command(uninstall_cmd)
        subprocess.run(["reg", "add", reg, "/v", "DisplayName", "/t", "REG_SZ", "/d", "ChronoArchiver", "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "DisplayVersion", "/t", "REG_SZ", "/d", VERSION, "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "Publisher", "/t", "REG_SZ", "/d", "ChronoArchiver", "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "InstallLocation", "/t", "REG_SZ", "/d", str(app_root), "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "DisplayIcon", "/t", "REG_SZ", "/d", display_icon, "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "UninstallString", "/t", "REG_SZ", "/d", uninstall_reg_cmd, "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "NoModify", "/t", "REG_DWORD", "/d", "1", "/f"], capture_output=True, timeout=8)
        subprocess.run(["reg", "add", reg, "/v", "NoRepair", "/t", "REG_DWORD", "/d", "1", "/f"], capture_output=True, timeout=8)
        subprocess.run(
            ["reg", "add", reg, "/v", "InstallDate", "/t", "REG_SZ", "/d", datetime.now().strftime("%Y%m%d"), "/f"],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass


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

    # Also create an app-style uninstaller entry
    uninstall_app = app_root / "Uninstall ChronoArchiver.app"
    u_contents = uninstall_app / "Contents"
    u_macos = u_contents / "MacOS"
    u_macos.mkdir(parents=True, exist_ok=True)
    u_exec = u_macos / "Uninstall ChronoArchiver"
    u_exec.write_text(f'''#!/bin/bash
osascript -e 'display dialog "Remove ChronoArchiver and all data?" buttons {{"Cancel","Remove"}} default button "Remove"'
if [ $? -ne 0 ]; then
  exit 0
fi
rm -rf "{install_dir}"
osascript -e 'display dialog "ChronoArchiver has been uninstalled." buttons {{"OK"}} default button "OK"'
''')
    u_exec.chmod(0o755)
    (u_contents / "Info.plist").write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Uninstall ChronoArchiver</string>
<key>CFBundleIdentifier</key><string>com.undadfeated.chronoarchiver.uninstall</string>
<key>CFBundleName</key><string>Uninstall ChronoArchiver</string>
<key>CFBundleVersion</key><string>{VERSION}</string>
</dict></plist>
''')


def _run_app(app_root: Path):
    """Launch the installed Python app (no console window)."""
    if platform.system() == "Windows":
        pyw = app_root / "venv" / "Scripts" / "pythonw.exe"
        launcher = app_root / "chronoarchiver.pyw"
        cmd = [str(pyw), str(launcher)] if pyw.exists() else ["pythonw", str(launcher)]
        _install_log(f"launch: cmd={cmd!r} cwd={app_root}")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(cmd, cwd=str(app_root), creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        app_bundle = app_root / "ChronoArchiver.app"
        if app_bundle.exists():
            _install_log(f"launch: open -a {app_bundle}")
            subprocess.Popen(["open", "-a", str(app_bundle)])
        else:
            cmd = ["python3", str(app_root / "chronoarchiver.pyw")]
            _install_log(f"launch: cmd={cmd!r} cwd={app_root}")
            subprocess.Popen(cmd, cwd=str(app_root), start_new_session=True)


def _apply_setup_window_icon(root) -> None:
    """Taskbar / title bar icon when icon.ico or icon.png is bundled."""
    try:
        import tkinter as tk
    except ImportError:
        return
    ico = _installer_asset_path("icon.ico")
    if platform.system() == "Windows" and ico:
        try:
            root.iconbitmap(default=str(ico))
            return
        except tk.TclError:
            pass
    png = _installer_asset_path("icon.png")
    if png:
        try:
            img = tk.PhotoImage(master=root, file=str(png))
            root.iconphoto(True, img)
            setattr(root, "_wm_iconphoto_ref", img)
        except tk.TclError:
            pass


def _show_welcome_and_log_choice() -> tuple[bool, bool]:
    """Welcome screen. Returns (proceed_with_install, enable_install_log). Checkbox default off."""
    try:
        import tkinter as tk
    except ImportError:
        return True, False
    out = {"proceed": False, "log": False}
    root = tk.Tk()
    root.title("ChronoArchiver — Welcome")
    root.geometry("500x360")
    root.resizable(False, False)
    root.configure(bg="#0d0d0d")
    root.option_add("*Font", "TkDefaultFont 9")
    _apply_setup_window_icon(root)

    logo = _welcome_logo_photo(root)
    if logo is not None:
        lbl_logo = tk.Label(root, image=logo, bg="#0d0d0d")
        lbl_logo.pack(pady=(18, 4))
        setattr(root, "_welcome_logo_ref", logo)

    tk.Label(
        root,
        text="Welcome to ChronoArchiver",
        fg="#e5e7eb",
        bg="#0d0d0d",
        font=("", 13, "bold"),
    ).pack(pady=(4, 6))
    blurb = (
        f"This installer sets up or updates ChronoArchiver v{VERSION}.\n\n"
        "Your data folder is kept; application files and the Python environment "
        "are refreshed from the official release when needed."
    )
    tk.Label(root, text=blurb, fg="#9ca3af", bg="#0d0d0d", wraplength=440, justify=tk.LEFT).pack(pady=6, padx=22)
    log_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        root,
        text="Append detailed install log (ChronoArchiver_installer.log next to this installer)",
        variable=log_var,
        fg="#e5e7eb",
        bg="#0d0d0d",
        selectcolor="#1f1f1f",
        activebackground="#0d0d0d",
        activeforeground="#e5e7eb",
        font=("", 9),
        anchor="w",
    ).pack(pady=(14, 4), padx=22, fill=tk.X)
    tk.Label(
        root,
        text="Leave off unless troubleshooting. Each run adds a session; the file keeps full history.",
        fg="#6b7280",
        bg="#0d0d0d",
        font=("", 8),
        wraplength=440,
        justify=tk.LEFT,
    ).pack(padx=22, anchor="w")
    btn_fr = tk.Frame(root, bg="#0d0d0d")
    btn_fr.pack(pady=22)

    def on_exit():
        out["proceed"] = False
        root.destroy()

    def on_install():
        out["proceed"] = True
        out["log"] = bool(log_var.get())
        root.destroy()

    tk.Button(btn_fr, text="Exit", command=on_exit, width=11, padx=8, pady=4).pack(side=tk.LEFT, padx=6)
    tk.Button(btn_fr, text="Install / Update", command=on_install, width=16, padx=8, pady=4).pack(side=tk.LEFT, padx=6)
    root.mainloop()
    return out["proceed"], out["log"]


def _do_setup_gui(download_url: str) -> bool:
    """Show progress window, download, extract, create shortcuts. Caller supplies release asset URL."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("ChronoArchiver: tkinter required for setup UI.")
        return False

    url = download_url
    if not url:
        _install_log("setup GUI: empty download_url (internal check)")
        _install_log_footer(False, "missing_download_url")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ChronoArchiver", f"Could not find download for v{VERSION}. Check your connection.")
        root.destroy()
        return False

    _install_log(f"setup GUI: download URL={url}")

    root = tk.Tk()
    root.title("ChronoArchiver — Setup")
    root.geometry("560x460")
    root.resizable(False, False)
    root.configure(bg="#0d0d0d")
    root.option_add("*Font", "TkDefaultFont 9")
    _apply_setup_window_icon(root)

    lbl_title = tk.Label(root, text="Installing ChronoArchiver…", fg="#e5e7eb", bg="#0d0d0d", font=("", 11, "bold"))
    lbl_title.pack(pady=(16, 6))
    lbl_component = tk.Label(root, text="Preparing…", fg="#9ca3af", bg="#0d0d0d", wraplength=520)
    lbl_component.pack(pady=2)
    lbl_detail = tk.Label(root, text="", fg="#6b7280", bg="#0d0d0d", font=("", 8), wraplength=480)
    lbl_detail.pack(pady=2)
    lbl_speed = tk.Label(root, text="", fg="#10b981", bg="#0d0d0d")
    lbl_speed.pack(pady=2)
    tk.Label(root, text="Current Component", fg="#9ca3af", bg="#0d0d0d", font=("", 8, "bold")).pack(pady=(8, 0))
    prog_step = ttk.Progressbar(root, length=500, mode="determinate")
    prog_step.pack(pady=4)
    lbl_pct_step = tk.Label(root, text="0%", fg="#6b7280", bg="#0d0d0d")
    lbl_pct_step.pack(pady=2)
    tk.Label(root, text="Overall Progress", fg="#9ca3af", bg="#0d0d0d", font=("", 8, "bold")).pack(pady=(8, 0))
    prog_overall = ttk.Progressbar(root, length=500, mode="determinate")
    prog_overall.pack(pady=4)
    lbl_pct_overall = tk.Label(root, text="0%", fg="#6b7280", bg="#0d0d0d")
    lbl_pct_overall.pack(pady=2)
    checklist = [
        tk.Label(root, text=f"  [ ] {name}", fg="#6b7280", bg="#0d0d0d", anchor="w")
        for name in ("Download source", "Extract files", "Create environment", "Install dependencies", "Verify install", "Create shortcuts")
    ]
    for lbl in checklist:
        lbl.pack(fill="x", padx=26)

    result = [False]
    result_error = [""]
    done = [False]

    stage = {"index": 0, "base": 0.0, "span": 100.0}
    stage_plan = [
        (0, 35.0),   # Download
        (35.0, 5.0), # Extract
        (40.0, 10.0),# Create environment
        (50.0, 40.0),# Install dependencies
        (90.0, 5.0), # Verify
        (95.0, 5.0), # Shortcuts/finalize
    ]

    def _set_stage(idx: int, title: str):
        stage["index"] = idx
        stage["base"], stage["span"] = stage_plan[idx]
        lbl_component.config(text=title)
        for i, lbl in enumerate(checklist):
            if i < idx:
                lbl.config(text=lbl.cget("text").replace("[ ]", "[x]"), fg="#22c55e")
            elif i == idx:
                lbl.config(text=lbl.cget("text").replace("[x]", "[ ]"), fg="#e5e7eb")
            else:
                lbl.config(text=lbl.cget("text").replace("[x]", "[ ]"), fg="#6b7280")

    def progress_cb(component, pct, speed_mbps, size_mb, detail=""):
        def update():
            lbl_component.config(text=component)
            lbl_detail.config(text=detail[:100] if detail else "")
            step_pct = min(100, max(0, pct))
            prog_step["value"] = step_pct
            lbl_pct_step.config(text=f"{step_pct:.1f}%")
            overall_pct = min(100.0, stage["base"] + stage["span"] * step_pct / 100.0)
            prog_overall["value"] = overall_pct
            lbl_pct_overall.config(text=f"{overall_pct:.1f}%")
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
            _install_log(f"task: app_dir={app_dir}")
            _install_log(f"task: installed __version__ from src/version.py = {_read_source_version(app_dir)!r}")
            _install_log(f"task: setup VERSION = {VERSION!r} skip_zip={_should_skip_source_zip(app_dir)}")
            zip_path: str | None = None
            try:
                if _should_skip_source_zip(app_dir):
                    _install_log("task: skipping source zip (tree already matches VERSION)")
                    _set_stage(0, "Source already matches this version — skipping download")
                    progress_cb("Using installed source", 100, 0, 0, f"v{VERSION} (src/version.py)")
                    _set_stage(1, "Application files — already up to date")
                    progress_cb("Extracting…", 100, 0, 0, "skipped")
                else:
                    fd, zip_path = tempfile.mkstemp(suffix=".zip")
                    os.close(fd)
                    _install_log(f"task: temp zip {zip_path}")
                    _set_stage(0, "Downloading ChronoArchiver source…")
                    if not _download_with_progress(url, zip_path, progress_cb):
                        _install_log("task: ERROR download failed")
                        _install_log_footer(False, "download")
                        result[0] = False
                        result_error[0] = "Failed while downloading source package."
                        done[0] = True
                        return
                    _install_log("task: download OK, merging extract")
                    _set_stage(1, "Updating application files (venv preserved)…")
                    progress_cb("Extracting…", 0, 0, 0)
                    _extract_source_zip_merged(zip_path, app_dir, progress_cb)
                    _install_log(f"task: after extract, src __version__ = {_read_source_version(app_dir)!r}")
            finally:
                if zip_path:
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass
            _set_stage(2, "Virtual environment…")
            progress_cb("Virtual environment…", 0, 0, 0)
            _set_stage(3, "Installing dependencies…")
            _install_log("task: starting venv / pip bootstrap")
            ok, err = _run_setup_bootstrap(app_dir, progress_cb)
            if not ok:
                _install_log(f"task: bootstrap FAILED {err!r}")
                _install_log_footer(False, "bootstrap")
                result[0] = False
                result_error[0] = err or "Dependency installation failed."
                done[0] = True
                return
            _install_log("task: bootstrap OK")
            _set_stage(4, "Verifying installation…")
            progress_cb("Verifying…", 100, 0, 0)
            _set_stage(5, "Creating shortcuts…")
            progress_cb("Creating shortcuts…", 0, 0, 0)
            if platform.system() == "Windows":
                _create_windows_shortcuts(app_dir)
            else:
                _create_macos_app_and_uninstaller(app_dir)
            _app_dir().mkdir(parents=True, exist_ok=True)
            _version_file().write_text(VERSION)
            _install_log(f"task: wrote version.txt -> {VERSION!r}")
            _install_log(f"task: final src __version__ = {_read_source_version(app_dir)!r}")
            progress_cb("Completed", 100, 0, 0, "Installation finished successfully.")
            _install_log_footer(True, "setup_complete")
            result[0] = True
        except Exception as e:
            _install_log(f"task: EXCEPTION {type(e).__name__}: {e!r}")
            _install_log_chunk("task exception traceback", traceback.format_exc(), 8000)
            _install_log_footer(False, "exception")
            result[0] = False
            result_error[0] = str(e)
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
        msg = "Setup failed."
        if result_error[0]:
            msg += f"\n\n{result_error[0][:600]}"
        messagebox.showerror("ChronoArchiver", msg)
        root2.destroy()
        return False
    return True


def main():
    proceed, want_log = _show_welcome_and_log_choice()
    if not proceed:
        return
    _setup_install_logging(want_log)
    _install_log(f"main: VERSION={VERSION!r} frozen={getattr(sys, 'frozen', False)}")
    _install_log(f"main: sys.executable={sys.executable!r}")

    app_dir = _app_dir()
    _install_log(f"main: app_dir={app_dir}")
    sv = _read_source_version(app_dir)
    _install_log(f"main: installed src __version__={sv!r} quick_launch_eligible={_can_launch_without_setup(app_dir)}")

    if _can_launch_without_setup(app_dir):
        _install_log("main: quick-launch (source already matches VERSION); skipping setup GUI")
        _install_log_footer(True, "quick_launch")
        _run_app(app_dir)
        return

    url = _download_url()
    if not url:
        _install_log("main: ERROR could not resolve source zip URL from GitHub")
        _install_log_footer(False, "no_artifact_url")
        try:
            import tkinter as tk
            from tkinter import messagebox

            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "ChronoArchiver",
                f"Could not find download for v{VERSION}. Check your connection.",
            )
            r.destroy()
        except Exception:
            pass
        return

    if _do_setup_gui(url):
        _run_app(app_dir)


if __name__ == "__main__":
    main()
