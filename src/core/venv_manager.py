"""
venv_manager.py — App-private venv for ChronoArchiver (no sudo).
Ensures all Python deps run from ~/.local/share/ChronoArchiver/venv.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

try:
    import requests
except ImportError:
    requests = None

import urllib.request

try:
    from .debug_logger import debug, UTILITY_OPENCV_INSTALL
except ImportError:
    from core.debug_logger import debug, UTILITY_OPENCV_INSTALL

try:
    from .subprocess_tee import tee_line, win_hide_kw
except ImportError:
    from core.subprocess_tee import tee_line, win_hide_kw

from . import app_paths


def _is_frozen() -> bool:
    """True when running as PyInstaller bundle (no venv)."""
    return getattr(sys, "frozen", False)


def _running_in_flatpak() -> bool:
    """True when running as a Flatpak (dependencies in /app; no app-private venv)."""
    return os.path.isfile("/.flatpak-info")
OPENCV_CUDA_API = "https://api.github.com/repos/cudawarped/opencv-python-cuda-wheels/releases/latest"
OPENCV_STANDARD_APPROX_BYTES = 90 * 1024 * 1024  # ~90 MB
# Fallback when API unavailable: cudawarped wheel ~500 MB
OPENCV_CUDA_FALLBACK_BYTES = 506 * 1024 * 1024

# Base packages (opencv chosen by get_opencv_package())
# numpy required by scanner; PySide6-Essentials sufficient but PySide6 ensures compatibility
VENV_PACKAGES_BASE = [
    "PySide6", "numpy", "psutil", "requests", "Pillow", "platformdirs",
    "piexif", "static-ffmpeg", "GitPython",
]


def detect_gpu() -> str:
    """Return 'nvidia', 'amd', 'intel', or ''."""
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=3,
            **win_hide_kw(),
        )
        if r.returncode == 0:
            return "nvidia"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        with open("/sys/class/drm/card0/device/vendor", "r") as f:
            vendor = f.read().strip()
        if "0x1002" in vendor or "amd" in vendor.lower():
            return "amd"
        if "0x8086" in vendor:
            return "intel"
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            out = (r.stdout or "").lower()
            if "amd" in out and ("radeon" in out or "graphics" in out):
                return "amd"
            if "intel" in out and ("xe" in out or "arc" in out or "uhd" in out or "iris" in out or "graphics" in out):
                return "intel"
            if "amd" in out:
                return "amd"
            if "intel" in out:
                return "intel"
    except Exception:
        pass
    return ""


def get_opencv_variant() -> str:
    """
    Return OpenCV install variant based on GPU:
    - 'cuda': NVIDIA → cudawarped wheel
    - 'opencl_amd': AMD Radeon → opencv-python (OpenCL / ROCm path, cv2.UMat)
    - 'opencl_intel': Intel Xe/Arc/integrated → opencv-python (OpenCL)
    - 'opencl': No discrete GPU → opencv-python (OpenCL, universal)
    """
    gpu = detect_gpu()
    if gpu == "nvidia":
        return "cuda"
    if gpu == "amd":
        return "opencl_amd"
    if gpu == "intel":
        return "opencl_intel"
    return "opencl"


def get_opencv_variant_label() -> str:
    """Human-readable label for the selected OpenCV variant."""
    v = get_opencv_variant()
    return {
        "cuda": "OpenCV (CUDA)",
        "opencl_amd": "OpenCV (OpenCL — AMD Radeon)",
        "opencl_intel": "OpenCV (OpenCL — Intel)",
        "opencl": "OpenCV (OpenCL)",
    }.get(v, "OpenCV (OpenCL)")


def get_opencv_package() -> str:
    """Return opencv package for pip (bootstrap/ensure_venv). CUDA uses wheel install separately."""
    return "opencv-python"


def get_venv_packages() -> list:
    return VENV_PACKAGES_BASE + [get_opencv_package()]


def get_venv_path() -> Path:
    return app_paths.data_dir() / "venv"


def get_python_exe() -> Path:
    venv = get_venv_path()
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def get_pip_exe() -> Path:
    venv = get_venv_path()
    if platform.system() == "Windows":
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"


def check_opencv_in_venv() -> bool:
    """True if venv exists and can import cv2 (runtime check, not import-time cache)."""
    try:
        from .debug_logger import debug, UTILITY_OPENCV_INSTALL
    except ImportError:
        debug = lambda *a: None
        UTILITY_OPENCV_INSTALL = "OpenCV"
    if _is_frozen():
        try:
            import cv2  # noqa: F401
            return True
        except ImportError:
            return False
    if _running_in_flatpak():
        try:
            import cv2  # noqa: F401
            return True
        except ImportError:
            return False
    py = get_python_exe()
    if not py.exists():
        debug(UTILITY_OPENCV_INSTALL, "check_opencv_in_venv: python exe not found")
        return False
    _add_nvidia_libs_to_ld_path()
    env = os.environ.copy()
    try:
        r = subprocess.run(
            [str(py), "-c", "import cv2"], capture_output=True, timeout=5, env=env,
            **win_hide_kw(),
        )
        ok = r.returncode == 0
        debug(UTILITY_OPENCV_INSTALL, f"check_opencv_in_venv: returncode={r.returncode} ok={ok}")
        return ok
    except Exception as e:
        debug(UTILITY_OPENCV_INSTALL, f"check_opencv_in_venv: exception {e}")
        return False


def check_ffmpeg_in_venv() -> bool:
    """True if venv has static-ffmpeg with binaries installed (installed.crumb exists). No download triggered."""
    if _is_frozen():
        try:
            import os as _os
            from static_ffmpeg.run import get_platform_dir
            crumb = _os.path.join(get_platform_dir(), "installed.crumb")
            return _os.path.isfile(crumb)
        except Exception:
            return False
    if _running_in_flatpak():
        if shutil.which("ffmpeg"):
            return True
        try:
            import os as _os
            from static_ffmpeg.run import get_platform_dir
            crumb = _os.path.join(get_platform_dir(), "installed.crumb")
            return _os.path.isfile(crumb)
        except Exception:
            return False
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", (
                "import os; "
                "from static_ffmpeg.run import get_platform_dir; "
                "crumb = os.path.join(get_platform_dir(), 'installed.crumb'); "
                "exit(0 if os.path.isfile(crumb) else 1)"
            )],
            capture_output=True, timeout=10,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_ffmpeg_in_venv() -> bool:
    """
    Ensure FFmpeg/ffprobe binaries are available via static-ffmpeg. Downloads on first run.
    Call add_ffmpeg_to_path() after this returns True.
    """
    return ensure_bundled_ffmpeg(None)


def ensure_ffmpeg_in_venv_with_progress(progress_callback=None) -> bool:
    """
    Ensure FFmpeg/ffprobe via static-ffmpeg. Downloads on first run with real progress/speed.
    progress_callback(phase: str, pct: int, detail: str) where phase in ('downloading','extracting','done'),
    pct 0-100, detail e.g. "2.3 MB/s" or "Extracting...". Call add_ffmpeg_to_path() after True.
    """
    def prog(phase: str, pct: int, detail: str):
        if progress_callback:
            progress_callback(phase, pct, detail)
        tee_line(f"[ffmpeg] {phase} {pct}% {detail}".strip())

    try:
        from static_ffmpeg.run import (
            get_platform_http_zip,
            get_platform_dir,
            get_platform_key,
            LOCK_FILE,
            PLATFORM_ZIP_FILES,
        )
        from filelock import FileLock, Timeout
    except ImportError:
        # Fallback to subprocess when static_ffmpeg not importable (e.g. bootstrap)
        py = get_python_exe()
        if not py.exists():
            return False
        try:
            subprocess.run(
                [str(py), "-c", (
                    "from static_ffmpeg.run import get_or_fetch_platform_executables_else_raise; "
                    "get_or_fetch_platform_executables_else_raise()"
                )],
                capture_output=True, timeout=600,
                **win_hide_kw(),
            )
            return True
        except Exception:
            return False

    if get_platform_key() not in PLATFORM_ZIP_FILES:
        return False

    exe_dir = get_platform_dir()
    installed_crumb = os.path.join(exe_dir, "installed.crumb")
    if os.path.exists(installed_crumb):
        return True

    if not requests:
        return False

    TIMEOUT = 10 * 60
    lock = FileLock(LOCK_FILE, timeout=TIMEOUT)
    acquired = False
    try:
        lock.acquire()
        acquired = True
    except Timeout:
        debug(UTILITY_OPENCV_INSTALL, "FFmpeg install lock timeout; another instance may be installing")
        return False

    try:
        install_dir = os.path.dirname(exe_dir)
        os.makedirs(exe_dir, exist_ok=True)
        url = get_platform_http_zip()
        local_zip = exe_dir + ".zip"

        prog("downloading", 0, "")
        start = time.time()
        downloaded = 0
        chunk_size = 256 * 1024
        total = -1

        with requests.get(url, stream=True, timeout=TIMEOUT) as req:
            req.raise_for_status()
            try:
                total = int(req.headers.get("content-length", 0))
            except (ValueError, TypeError):
                total = -1

            with open(local_zip, "wb") as f:
                for chunk in req.iter_content(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.time() - start
                    speed_bps = downloaded / elapsed if elapsed > 0 else 0
                    speed_mb = speed_bps / (1024 * 1024)
                    pct = int((downloaded / total * 100)) if total > 0 else min(90, downloaded // (1024 * 1024))
                    detail = f"{speed_mb:.1f} MB/s" if speed_mb >= 0.01 else f"{speed_bps / 1024:.0f} KB/s"
                    prog("downloading", min(90, pct), detail)

        prog("extracting", 92, "Extracting...")
        import zipfile
        with zipfile.ZipFile(local_zip, mode="r") as zipf:
            zipf.extractall(install_dir)
        try:
            os.remove(local_zip)
        except OSError:
            pass
        from datetime import datetime
        with open(installed_crumb, "wt") as fd:
            fd.write(f"installed from {url} on {str(datetime.now())}")

        # Fix permissions on Unix
        if platform.system() != "Windows":
            import stat
            for name in ("ffmpeg", "ffprobe"):
                exe = os.path.join(exe_dir, name)
                if os.path.exists(exe):
                    os.chmod(exe, stat.S_IXOTH | stat.S_IXUSR | stat.S_IXGRP | stat.S_IRUSR | stat.S_IRGRP)

        prog("done", 100, "")
        return True
    except Exception as e:
        debug(UTILITY_OPENCV_INSTALL, f"FFmpeg install failed: {e}")
        return False
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass


COMPONENTS_MANIFEST_URL = (
    "https://raw.githubusercontent.com/UnDadFeated/ChronoArchiver/main/docs/components_manifest.json"
)


def get_settings_dir() -> Path:
    """Shared Settings/ — see app_paths.settings_dir."""
    return app_paths.settings_dir()


def fetch_components_manifest() -> dict | None:
    """Remote JSON from main branch; None on failure (offline)."""
    try:
        req = urllib.request.Request(
            COMPONENTS_MANIFEST_URL,
            headers={"User-Agent": "ChronoArchiver-Components/1.0"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_local_ffmpeg_revision() -> int:
    p = get_settings_dir() / "ffmpeg_revision.txt"
    try:
        if not p.is_file():
            return 0
        line = (p.read_text(encoding="utf-8").strip() or "0").split()[0]
        return int(line)
    except (ValueError, OSError):
        return 0


def set_local_ffmpeg_revision(rev: int) -> None:
    try:
        p = get_settings_dir() / "ffmpeg_revision.txt"
        p.write_text(str(int(rev)) + "\n", encoding="utf-8")
    except OSError:
        pass


def _remove_ffmpeg_installed_crumb() -> None:
    try:
        from static_ffmpeg.run import get_platform_dir
        exe_dir = get_platform_dir()
        crumb = os.path.join(exe_dir, "installed.crumb")
        if os.path.isfile(crumb):
            os.remove(crumb)
        z = exe_dir + ".zip"
        if os.path.isfile(z):
            os.remove(z)
    except Exception:
        pass


def apply_ffmpeg_manifest_policy() -> None:
    """
    If manifest ffmpeg_revision increased, remove installed.crumb so binaries refetch.
    If FFmpeg already present but no revision file (legacy), seed revision without re-download.
    """
    if _is_frozen():
        return
    m = fetch_components_manifest()
    if not m:
        # Offline: pin revision so we do not treat legacy installs as "behind" once manifest is reachable.
        if get_local_ffmpeg_revision() == 0 and check_ffmpeg_in_venv():
            set_local_ffmpeg_revision(1)
        return
    try:
        remote = int(m.get("ffmpeg_revision", 0))
    except (TypeError, ValueError):
        return
    local = get_local_ffmpeg_revision()
    if local == 0 and check_ffmpeg_in_venv():
        set_local_ffmpeg_revision(remote)
        return
    if remote > local:
        _remove_ffmpeg_installed_crumb()


def _sync_ffmpeg_revision_from_manifest() -> None:
    m = fetch_components_manifest()
    if not m:
        return
    try:
        remote = int(m.get("ffmpeg_revision", 0))
    except (TypeError, ValueError):
        return
    if remote > 0:
        set_local_ffmpeg_revision(remote)


def ensure_bundled_ffmpeg(progress_callback=None) -> bool:
    """
    Apply online component manifest, ensure static-ffmpeg binaries, persist revision, add to PATH.
    Prefer this over ensure_ffmpeg_in_venv_with_progress alone (setup + app + Pre-req).
    """
    if _is_frozen():
        try:
            add_ffmpeg_to_path()
        except Exception:
            pass
        return check_ffmpeg_in_venv()
    apply_ffmpeg_manifest_policy()
    if check_ffmpeg_in_venv():
        _sync_ffmpeg_revision_from_manifest()
        add_ffmpeg_to_path()
        return True
    ok = ensure_ffmpeg_in_venv_with_progress(progress_callback)
    if not ok:
        return False
    _sync_ffmpeg_revision_from_manifest()
    add_ffmpeg_to_path()
    return True


def add_ffmpeg_to_path() -> bool:
    """Add static-ffmpeg ffmpeg/ffprobe to PATH. Call after ensure_ffmpeg_in_venv or when check_ffmpeg_in_venv."""
    try:
        from static_ffmpeg import add_paths
        add_paths()
        return True
    except Exception:
        return False


def is_venv_runnable() -> bool:
    """True if venv exists and can run the app (PySide6, PIL, requests). Does NOT require OpenCV."""
    if _is_frozen():
        return True
    if _running_in_flatpak():
        try:
            import PySide6  # noqa: F401
            import PIL  # noqa: F401
            import requests  # noqa: F401
            return True
        except ImportError:
            return False
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import PySide6; import PIL; import requests"],
            capture_output=True, timeout=5,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def is_venv_ready() -> bool:
    """True if venv exists and has all required packages including OpenCV."""
    if _running_in_flatpak():
        try:
            import PySide6  # noqa: F401
            import numpy  # noqa: F401
            import cv2  # noqa: F401
            import PIL  # noqa: F401
            import requests  # noqa: F401
            return True
        except ImportError:
            return False
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import PySide6; import numpy; import cv2; import PIL; import requests"],
            capture_output=True, timeout=5,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_venv(progress_callback=None, skip_opencv: bool = False) -> bool:
    """
    Create venv and install packages. progress_callback(phase, detail, pct=None).
    skip_opencv: if True, do not install opencv (caller will install separately).
    Returns True on success. No-op when frozen.
    """
    if _is_frozen():
        return True
    if _running_in_flatpak():
        return True
    data = app_paths.data_dir()
    venv = get_venv_path()
    data.mkdir(parents=True, exist_ok=True)

    def prog(phase, detail="", pct=None):
        if progress_callback:
            progress_callback(phase, detail, pct)

    if not (venv / "bin" / "python").exists() and not (venv / "Scripts" / "python.exe").exists():
        prog("Creating virtual environment...", "", 0)
        r = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True, text=True, timeout=60,
            **win_hide_kw(),
        )
        if r.returncode != 0:
            prog("venv creation failed", (r.stderr or r.stdout or "")[:150], 0)
            return False

    pip = get_pip_exe()
    if not pip.exists():
        prog("venv pip not found", "", 0)
        return False

    packages = VENV_PACKAGES_BASE + ([] if skip_opencv else [get_opencv_package()])
    n = len(packages)
    for i, pkg in enumerate(packages):
        prog(f"Installing {pkg} ({i + 1}/{n})...", "", 100.0 * i / n)
        proc = subprocess.Popen(
            [str(pip), "install", pkg],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            **win_hide_kw(),
        )
        for line in iter(proc.stdout.readline, "") if proc.stdout else []:
            line = (line or "").strip()
            if line:
                tee_line(f"[pip] {line[:500]}")
                prog(f"Installing {pkg} ({i + 1}/{n})...", line[:100], 100.0 * (i + 0.5) / n)
        try:
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            prog("pip install timeout", "", 0)
            return False
        if proc.returncode != 0:
            prog(f"Failed: {pkg}", "", 0)
            return False
        prog(f"Installed {pkg} ({i + 1}/{n})", "", 100.0 * (i + 1) / n)

    prog("Setup complete.", "Restart ChronoArchiver.", 100)
    return True


def get_opencv_install_size(variant: str | None = None) -> tuple:
    """Return (size_bytes, human_str) for OpenCV install."""
    components = get_opencv_install_components(variant)
    total = sum(s for _, s in components)
    if total <= 0:
        total = OPENCV_CUDA_FALLBACK_BYTES if (variant or get_opencv_variant()) == "cuda" else OPENCV_STANDARD_APPROX_BYTES
    gb, mb = total / (1024**3), total / (1024**2)
    return total, f"~{gb:.2f} GB" if gb >= 0.1 else f"~{mb:.1f} MB"


# Approximate sizes for NVIDIA pip packages (venv install, no sudo)
NVIDIA_CUDA_RUNTIME_APPROX_BYTES = int(2.2 * 1024 * 1024)   # ~2.2 MB
NVIDIA_CUBLAS_APPROX_BYTES = int(384 * 1024 * 1024)        # ~384 MB (manylinux x86_64 wheel)
NVIDIA_CUDNN_APPROX_BYTES = int(366 * 1024 * 1024)          # ~366 MB
NVIDIA_CUFFT_APPROX_BYTES = int(25 * 1024 * 1024)          # ~25 MB (libcufft.so.12 for OpenCV CUDA wheel)

# PyPI packages for CUDA/cuDNN/cuFFT in venv (compatible with cudawarped OpenCV CUDA wheel)
NVIDIA_CUDA_CUDNN_PIP_PACKAGES = [
    "nvidia-cuda-runtime",
    "nvidia-cublas",
    "nvidia-cufft",  # libcufft.so.12 required by OpenCV CUDA wheel
    "nvidia-cudnn-cu13",
]


def _is_cuda_cudnn_installed() -> bool:
    """Check if CUDA and cuDNN are installed in the app venv (pip packages)."""
    pip = get_pip_exe()
    if not pip.exists():
        return False
    try:
        r = subprocess.run(
            [str(pip), "show", "nvidia-cudnn-cu13"],
            capture_output=True, text=True, timeout=5,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def _install_cuda_cudnn_venv(progress_callback=None) -> tuple[bool, str | None]:
    """Install CUDA and cuDNN via pip into app venv (no sudo). Returns (success, error)."""
    def prog(msg, detail=""):
        if progress_callback:
            progress_callback(msg, detail, 0, 0)

    pip = get_pip_exe()
    if not pip.exists():
        debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN install: venv not ready")
        return False, "venv not ready"

    debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN/cuFFT install: starting pip install (~775 MB, may take 2–5 min)")
    prog("Installing CUDA runtime, cuBLAS, cuFFT, and cuDNN...", "Downloading ~775 MB (may take 2–5 min)...")
    proc = None
    try:
        proc = subprocess.Popen(
            [str(pip), "install", *NVIDIA_CUDA_CUDNN_PIP_PACKAGES],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **win_hide_kw(),
        )
        out_lines: list[str] = []
        for line in iter(proc.stdout.readline, "") if proc.stdout else []:
            ln = (line or "").rstrip("\n")
            if ln.strip():
                out_lines.append(ln)
                tee_line(f"[pip] {ln[:500]}")
                prog("Installing CUDA stack...", ln[:120], 0, 0)
        proc.wait(timeout=600)
        if proc.returncode == 0:
            debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN install: success")
            return True, None
        err = "\n".join(out_lines[-40:]) or "Unknown error"
        debug(UTILITY_OPENCV_INSTALL, f"CUDA/cuDNN install FAILED: {err[:500]}")
        return False, err
    except subprocess.TimeoutExpired:
        debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN install: timed out")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        return False, "Installation timed out"
    except Exception as e:
        debug(UTILITY_OPENCV_INSTALL, f"CUDA/cuDNN install ERROR: {e}")
        return False, str(e)


def get_opencv_install_components(variant: str | None = None) -> list[tuple[str, int]]:
    """Return [(component_name, size_bytes), ...] for the install confirmation dialog.
    variant: 'cuda'|'opencl_amd'|'opencl_intel'|'opencl' (default: from get_opencv_variant)."""
    v = variant or get_opencv_variant()
    if v == "cuda":
        components = [
            ("nvidia-cuda-runtime (CUDA, venv)", NVIDIA_CUDA_RUNTIME_APPROX_BYTES),
            ("nvidia-cublas (cuBLAS, venv)", NVIDIA_CUBLAS_APPROX_BYTES),
            ("nvidia-cufft (cuFFT, venv)", NVIDIA_CUFFT_APPROX_BYTES),
            ("nvidia-cudnn-cu13 (cuDNN, venv)", NVIDIA_CUDNN_APPROX_BYTES),
        ]
        wheel_size = OPENCV_CUDA_FALLBACK_BYTES
        if requests:
            try:
                r = requests.get(OPENCV_CUDA_API, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    is_win = platform.system() == "Windows"
                    for a in data.get("assets", []):
                        name = a.get("name", "")
                        if not name.endswith(".whl"):
                            continue
                        sz = int(a.get("size", 0) or 0)
                        if sz <= 0:
                            continue
                        if is_win and "win_amd64" in name:
                            wheel_size = sz
                            break
                        if not is_win and "linux" in name.lower() and "x86_64" in name:
                            wheel_size = sz
                            break
            except Exception:
                pass
        components.append(("opencv-contrib-python (CUDA)", wheel_size))
        return components
    # opencl_amd, opencl_intel, opencl: all use opencv-python
    url, size = _get_opencv_standard_wheel_url()
    labels = {
        "opencl_amd": "opencv-python (OpenCL — AMD Radeon)",
        "opencl_intel": "opencv-python (OpenCL — Intel)",
        "opencl": "opencv-python (OpenCL)",
    }
    label = labels.get(v, "opencv-python (OpenCL)")
    if url and size > 0:
        return [(label, size)]
    return [(label, OPENCV_STANDARD_APPROX_BYTES)]


def _get_opencv_standard_wheel_url() -> tuple:
    """Return (url, size_bytes) for opencv-python wheel from PyPI. Returns (None, 0) on failure."""
    if not requests:
        return None, 0
    try:
        r = requests.get("https://pypi.org/pypi/opencv-python/json", timeout=15)
        if r.status_code != 200:
            return None, 0
        data = r.json()
        is_win = platform.system() == "Windows"
        for info in data.get("urls", []):
            if info.get("packagetype") != "bdist_wheel":
                continue
            fn = info.get("filename", "").lower()
            if is_win and "win_amd64" in fn:
                return info.get("url"), int(info.get("size", 0) or 0)
            if not is_win and "manylinux" in fn and "x86_64" in fn:
                return info.get("url"), int(info.get("size", 0) or 0)
            if platform.system() == "Darwin" and "macosx" in fn:
                return info.get("url"), int(info.get("size", 0) or 0)
        return None, 0
    except Exception:
        return None, 0


def _get_wheel_filename(r, url: str) -> str:
    """Extract a valid PEP 427 wheel filename from response or URL. Pip requires proper naming."""
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', cd, re.I)
    if m:
        name = unquote(m.group(1).strip()).strip('"')
        if name.endswith(".whl"):
            return name
    for u in (r.url, url):
        if not u:
            continue
        parsed = urlparse(u)
        name = os.path.basename(unquote(parsed.path))
        if name.endswith(".whl") and name.count("-") >= 4:
            return name
    return "opencv_wheel-0.0.0-py3-none-any.whl"


def _download_wheel_with_progress(url: str, progress_callback, total_hint: int = 0) -> Path | None:
    """Download wheel to temp file with valid PEP 427 filename. Returns path or None on failure."""
    if not requests:
        return None
    try:
        r = requests.get(url, stream=True, timeout=(10, 120))
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0) or 0) or total_hint
        progress_callback("Downloading...", "0.00 MB/s", 0, total)
        filename = _get_wheel_filename(r, url)
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, filename)
        try:
            start = time.monotonic()
            last_update = start
            downloaded = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if now - last_update >= 0.2:  # throttle updates
                            elapsed = now - start
                            speed_mbs = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                            progress_callback("Downloading...", f"{speed_mbs:.2f} MB/s", downloaded, total)
                            last_update = now
                # final update at 100%
                elapsed = time.monotonic() - start
                speed_mbs = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                progress_callback("Downloading...", f"{speed_mbs:.2f} MB/s", downloaded, total)
            return Path(path)
        except Exception:
            try:
                if os.path.exists(path):
                    os.unlink(path)
                if os.path.isdir(tmpdir):
                    shutil.rmtree(tmpdir, ignore_errors=True)
            except OSError:
                pass
            return None
    except Exception:
        return None


def install_opencv(progress_callback=None, variant: str | None = None) -> tuple[bool, str | None]:
    """Install OpenCV into venv.
    variant: 'cuda'|'opencl_amd'|'opencl_intel'|'opencl' (default: from get_opencv_variant).
    progress_callback(phase, detail, downloaded=0, total=0) — total>0 enables size-based bar.
    Returns (success, error_message). On success: (True, None). On failure: (False, "reason")."""
    v = variant or get_opencv_variant()
    debug(UTILITY_OPENCV_INSTALL, f"install_opencv START variant={v}")

    pip = get_pip_exe()
    if not pip.exists():
        debug(UTILITY_OPENCV_INSTALL, "install_opencv FAIL: venv not ready")
        if progress_callback:
            progress_callback("venv not ready", "Run first-time setup first.", 0, 0)
        return False, "venv not ready"

    def prog(phase, detail="", downloaded=0, total=0):
        if progress_callback:
            progress_callback(phase, detail[:100] if detail else "", downloaded, total)

    # Uninstall existing opencv (all variants)
    debug(UTILITY_OPENCV_INSTALL, "install_opencv: removing previous OpenCV")
    prog("Removing...", "Uninstalling previous OpenCV", 0, 0)
    subprocess.run(
        [str(pip), "uninstall", "-y",
         "opencv-python", "opencv-python-headless",
         "opencv-contrib-python", "opencv-contrib-python-headless",
         "opencv-openvino-contrib-python"],
        capture_output=True, timeout=60,
        **win_hide_kw(),
    )

    wheel_path: Path | None = None
    try:
        if v == "cuda" and detect_gpu() == "nvidia":
            if not _is_cuda_cudnn_installed():
                prog("Installing CUDA runtime and cuDNN...", "pip install into venv...", 0, 0)
                ok_venv, err_venv = _install_cuda_cudnn_venv(
                    lambda msg, det, d, t: prog(msg, det, d, t)
                )
                if not ok_venv:
                    debug(UTILITY_OPENCV_INSTALL, f"install_opencv FAIL at CUDA/cuDNN: {err_venv}")
                    prog("Failed", err_venv[:80] if err_venv else "Could not install CUDA/cuDNN", 0, 0)
                    return False, err_venv or "Could not install CUDA/cuDNN"
            if not requests:
                return False, "requests module required for wheel download"
        if v == "cuda" and detect_gpu() == "nvidia" and requests:
            debug(UTILITY_OPENCV_INSTALL, "install_opencv: fetching CUDA wheel URL")
            prog("Fetching OpenCV CUDA wheel URL...", "")
            try:
                r = requests.get(OPENCV_CUDA_API, timeout=10)
                if r.status_code != 200:
                    prog("Failed", "Could not fetch release info", 0, 0)
                    return False, "Could not fetch CUDA wheel release info"
                data = r.json()
                wheel_url = None
                wheel_size = 0
                is_win = platform.system() == "Windows"
                for a in data.get("assets", []):
                    name = a.get("name", "")
                    if name.endswith(".whl"):
                        if is_win and "win_amd64" in name:
                            wheel_url = a.get("browser_download_url")
                            wheel_size = int(a.get("size", 0) or 0)
                            break
                        if not is_win and "linux" in name.lower() and "x86_64" in name:
                            wheel_url = a.get("browser_download_url")
                            wheel_size = int(a.get("size", 0) or 0)
                            break
                if not wheel_url:
                    prog("Failed", "No matching CUDA wheel for this platform", 0, 0)
                    return False, "No matching CUDA wheel for this platform"
                debug(UTILITY_OPENCV_INSTALL, f"install_opencv: downloading CUDA wheel ({wheel_size} bytes)")
                wheel_path = _download_wheel_with_progress(
                    wheel_url,
                    lambda p, d, down, tot: prog(p, d, down, tot),
                    total_hint=wheel_size,
                )
                debug(UTILITY_OPENCV_INSTALL, f"install_opencv: CUDA wheel download done, path={wheel_path}")
            except Exception as e:
                msg = str(e)[:200]
                debug(UTILITY_OPENCV_INSTALL, f"install_opencv FAIL: {msg}")
                prog("Failed", msg[:80], 0, 0)
                return False, msg
        else:
            debug(UTILITY_OPENCV_INSTALL, "install_opencv: OpenCL path, fetching standard wheel")
            wheel_url, wheel_size = _get_opencv_standard_wheel_url()
            if wheel_url:
                wheel_path = _download_wheel_with_progress(
                    wheel_url,
                    lambda p, d, down, tot: prog(p, d, down, tot),
                    total_hint=wheel_size or OPENCV_STANDARD_APPROX_BYTES,
                )
            if not wheel_path:
                debug(UTILITY_OPENCV_INSTALL, "install_opencv: pip install opencv-python (no wheel URL)")
                prog("Installing OpenCV...", "Downloading via pip...", 0, 0)
                ok = install_package("opencv-python", lambda p, d: progress_callback(p, d, 0, 0))
                debug(UTILITY_OPENCV_INSTALL, f"install_opencv OpenCL pip: {'SUCCESS' if ok else 'FAIL'}")
                return (ok, None if ok else "pip install opencv-python failed")

        if not wheel_path or not wheel_path.exists():
            debug(UTILITY_OPENCV_INSTALL, "install_opencv FAIL: download failed (no wheel path)")
            prog("Failed", "Download failed", 0, 0)
            return False, "Download failed"

        debug(UTILITY_OPENCV_INSTALL, f"install_opencv: pip install wheel {wheel_path}")
        prog("Installing...", "Setting up wheel (this may take a minute)", 1, 1)
        proc_w = subprocess.Popen(
            [str(pip), "install", str(wheel_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            **win_hide_kw(),
        )
        acc_lines: list[str] = []
        for line in iter(proc_w.stdout.readline, "") if proc_w.stdout else []:
            ln = (line or "").rstrip("\n")
            if ln.strip():
                acc_lines.append(ln)
                tee_line(f"[pip] {ln[:500]}")
                prog("Installing...", ln[:100], 1, 1)
        proc_w.wait(timeout=300)
        try:
            wheel_path.unlink()
            parent = wheel_path.parent
            if parent != Path(tempfile.gettempdir()) and parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
        except OSError:
            pass
        if proc_w.returncode != 0:
            err = "\n".join(acc_lines[-40:]) or "Unknown error"
            debug(UTILITY_OPENCV_INSTALL, f"install_opencv FAIL pip install wheel: {err[:800]}")
            prog("Failed", err[:80], 0, 0)
            return False, err
        debug(UTILITY_OPENCV_INSTALL, "install_opencv SUCCESS, returning (True, None)")
        prog("Complete.", "", 1, 1)
        return True, None
    finally:
        if wheel_path and wheel_path.exists():
            try:
                wheel_path.unlink()
                parent = wheel_path.parent
                if parent != Path(tempfile.gettempdir()) and parent.exists():
                    shutil.rmtree(parent, ignore_errors=True)
            except OSError:
                pass


def uninstall_opencv(progress_callback=None) -> bool:
    """Remove OpenCV from venv (all variants). Also removes NVIDIA CUDA/cuDNN pip packages if present."""
    debug(UTILITY_OPENCV_INSTALL, "uninstall_opencv START")
    pip = get_pip_exe()
    if not pip.exists():
        return False
    packages = [
        "opencv-python", "opencv-python-headless",
        "opencv-contrib-python", "opencv-contrib-python-headless",
        "opencv-openvino-contrib-python",
        # CUDA stack (pip installs into venv; safe to uninstall even if not present)
        "nvidia-cudnn-cu13", "nvidia-cuda-runtime", "nvidia-cublas", "nvidia-cufft",
    ]
    r = subprocess.run(
        [str(pip), "uninstall", "-y", *packages],
        capture_output=True, text=True, timeout=120,
        **win_hide_kw(),
    )
    ok = r.returncode == 0
    debug(UTILITY_OPENCV_INSTALL, f"uninstall_opencv: {'SUCCESS' if ok else f'FAIL rc={r.returncode}'}")
    return ok


def install_package(pkg: str, progress_callback=None) -> bool:
    """Install a single package into app venv."""
    get_venv_path()
    pip = get_pip_exe()
    if not pip.exists():
        if progress_callback:
            progress_callback("venv not ready", "Run Setup Models first.")
        return False

    def prog(phase, detail=""):
        if progress_callback:
            progress_callback(phase, detail)

    prog(f"Installing {pkg}...", "")
    proc = subprocess.Popen(
        [str(pip), "install", pkg],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        **win_hide_kw(),
    )
    for line in iter(proc.stdout.readline, "") if proc.stdout else []:
        line = (line or "").strip()
        if line:
            tee_line(f"[pip] {line[:500]}")
            prog(f"Installing {pkg}...", line[:100])
    proc.wait(timeout=300)
    return proc.returncode == 0


def remove_venv() -> bool:
    """Remove the app venv. Returns True on success."""
    venv = get_venv_path()
    if venv.exists():
        try:
            shutil.rmtree(venv)
            return True
        except OSError:
            pass
    return False


def _add_nvidia_libs_to_ld_path():
    """Prepend nvidia CUDA lib dirs to LD_LIBRARY_PATH so OpenCV CUDA wheel finds libcufft, libcudnn."""
    if platform.system() == "Windows":
        return
    venv = get_venv_path()
    lib = venv / "lib"
    if not lib.exists():
        return
    nvidia_libs = []
    for d in lib.iterdir():
        if d.name.startswith("python") and (d / "site-packages" / "nvidia").exists():
            nv = d / "site-packages" / "nvidia"
            for sub in ("cu13", "cudnn"):
                p = nv / sub / "lib"
                if p.is_dir():
                    nvidia_libs.append(str(p))
            break
    if nvidia_libs:
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        prefix = ":".join(nvidia_libs)
        os.environ["LD_LIBRARY_PATH"] = f"{prefix}:{existing}" if existing else prefix


def add_venv_to_path():
    """Add venv site-packages to sys.path (call before importing app deps). No-op when frozen."""
    if _is_frozen():
        add_ffmpeg_to_path()
        return
    venv = get_venv_path()
    lib = venv / ("Lib" if platform.system() == "Windows" else "lib")
    if not lib.exists():
        return
    for d in lib.iterdir():
        if d.name.startswith("python") and (d / "site-packages").exists():
            sp = str(d / "site-packages")
            if sp not in sys.path:
                sys.path.insert(0, sp)
            break
    _add_nvidia_libs_to_ld_path()
