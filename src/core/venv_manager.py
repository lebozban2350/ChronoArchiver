"""
venv_manager.py — App-private venv for ChronoArchiver (no sudo).
Ensures all Python deps run from ~/.local/share/ChronoArchiver/venv.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

try:
    import platformdirs
except ImportError:
    platformdirs = None

try:
    import requests
except ImportError:
    requests = None

APP_NAME = "ChronoArchiver"
APP_AUTHOR = "UnDadFeated"
OPENCV_CUDA_API = "https://api.github.com/repos/cudawarped/opencv-python-cuda-wheels/releases/latest"
OPENCV_STANDARD_APPROX_BYTES = 90 * 1024 * 1024  # ~90 MB
# Fallback when API unavailable: system opencv-cuda (pacman) ~7498 MiB installed
# (cuda+cuDNN+vtk+openmpi+opencv-cuda+python-opencv-cuda). Our pip wheel is smaller.
OPENCV_CUDA_FALLBACK_BYTES = 7498 * 1024 * 1024

# Base packages (opencv chosen by get_opencv_package())
VENV_PACKAGES_BASE = [
    "PySide6", "psutil", "requests", "Pillow", "platformdirs",
    "piexif",
]


def detect_gpu() -> str:
    """Return 'nvidia', 'amd', or ''."""
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=3,
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
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and "amd" in (r.stdout or "").lower():
            return "amd"
    except Exception:
        pass
    return ""


def get_opencv_package() -> str:
    """Return opencv package for pip. CUDA requires build-from-source (not automated)."""
    gpu = detect_gpu()
    if gpu == "nvidia":
        # Standard pip opencv has no CUDA. opencv-contrib-python has same.
        # For CUDA: build from source with -DWITH_CUDA=ON (see docs).
        return "opencv-python"
    if gpu == "amd":
        # Standard opencv-python has OpenCL; scanner will use DNN_TARGET_OPENCL.
        return "opencv-python"
    return "opencv-python"


def get_venv_packages() -> list:
    return VENV_PACKAGES_BASE + [get_opencv_package()]


def _data_dir() -> Path:
    if platformdirs:
        return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return Path.home() / ".local" / "share" / APP_NAME


def get_venv_path() -> Path:
    return _data_dir() / "venv"


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
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run([str(py), "-c", "import cv2"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def is_venv_ready() -> bool:
    """True if venv exists and has the required packages."""
    venv = get_venv_path()
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import PySide6; import cv2; import PIL; import requests"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_venv(progress_callback=None, skip_opencv: bool = False) -> bool:
    """
    Create venv and install packages. progress_callback(phase: str, detail: str).
    skip_opencv: if True, do not install opencv (caller will install separately).
    Returns True on success.
    """
    data = _data_dir()
    venv = get_venv_path()
    data.mkdir(parents=True, exist_ok=True)

    def prog(phase, detail=""):
        if progress_callback:
            progress_callback(phase, detail)

    if not (venv / "bin" / "python").exists() and not (venv / "Scripts" / "python.exe").exists():
        prog("Creating virtual environment...", "")
        r = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            prog("venv creation failed", (r.stderr or r.stdout or "")[:150])
            return False

    pip = get_pip_exe()
    if not pip.exists():
        prog("venv pip not found", "")
        return False

    packages = VENV_PACKAGES_BASE + ([] if skip_opencv else [get_opencv_package()])
    for pkg in packages:
        prog(f"Installing {pkg}...", "")
        proc = subprocess.Popen(
            [str(pip), "install", pkg],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in iter(proc.stdout.readline, "") if proc.stdout else []:
            line = (line or "").strip()
            if line:
                prog(f"Installing {pkg}...", line[:100])
        proc.wait(timeout=300)
        if proc.returncode != 0:
            prog(f"Failed: {pkg}", "")
            return False

    prog("Setup complete.", "Restart ChronoArchiver.")
    return True


def get_opencv_install_size(use_cuda: bool) -> tuple:
    """Return (size_bytes, human_str) for OpenCV install."""
    if not use_cuda:
        return OPENCV_STANDARD_APPROX_BYTES, "~90 MB"
    if requests:
        try:
            r = requests.get(OPENCV_CUDA_API, timeout=10)
            if r.status_code == 200:
                data = r.json()
                is_win = platform.system() == "Windows"
                for a in data.get("assets", []):
                    name = a.get("name", "")
                    if "linux" in name.lower() and "x86_64" in name and not is_win:
                        size = a.get("size", 0)
                        if size > 0:
                            mb, gb = size / (1024**2), size / (1024**3)
                            return size, f"~{gb:.2f} GB" if gb >= 0.1 else f"~{mb:.1f} MB"
                    if "win_amd64" in name and is_win:
                        size = a.get("size", 0)
                        if size > 0:
                            mb, gb = size / (1024**2), size / (1024**3)
                            return size, f"~{gb:.2f} GB" if gb >= 0.1 else f"~{mb:.1f} MB"
        except Exception:
            pass
    mb = OPENCV_CUDA_FALLBACK_BYTES / (1024**2)
    return OPENCV_CUDA_FALLBACK_BYTES, f"~{mb/1024:.1f} GB"


def install_opencv(progress_callback=None, use_cuda: bool = False) -> bool:
    """Install OpenCV into venv. use_cuda=True for NVIDIA CUDA wheel."""
    pip = get_pip_exe()
    if not pip.exists():
        if progress_callback:
            progress_callback("venv not ready", "Run first-time setup first.")
        return False

    def prog(phase, detail=""):
        if progress_callback:
            progress_callback(phase, detail[:100] if detail else "")

    # Uninstall existing opencv (standard and cudawarped wheel both use opencv-contrib-python)
    prog("Removing existing OpenCV...", "")
    subprocess.run(
        [str(pip), "uninstall", "-y",
         "opencv-python", "opencv-python-headless",
         "opencv-contrib-python", "opencv-contrib-python-headless"],
        capture_output=True, timeout=60,
    )

    if use_cuda and detect_gpu() == "nvidia" and requests:
        prog("Fetching OpenCV CUDA wheel URL...", "")
        try:
            r = requests.get(OPENCV_CUDA_API, timeout=10)
            if r.status_code != 200:
                prog("Failed", "Could not fetch release info")
                return False
            data = r.json()
            wheel_url = None
            is_win = platform.system() == "Windows"
            for a in data.get("assets", []):
                name = a.get("name", "")
                if name.endswith(".whl"):
                    if is_win and "win_amd64" in name:
                        wheel_url = a.get("browser_download_url")
                        break
                    if not is_win and "linux" in name.lower() and "x86_64" in name:
                        wheel_url = a.get("browser_download_url")
                        break
            if not wheel_url:
                prog("Failed", "No matching CUDA wheel for this platform")
                return False
            prog("Installing OpenCV (CUDA)...", "Downloading wheel...")
            proc = subprocess.Popen(
                [str(pip), "install", wheel_url],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            for line in iter(proc.stdout.readline, "") if proc.stdout else []:
                line = (line or "").strip()
                if line:
                    prog("Installing OpenCV (CUDA)...", line[:100])
            proc.wait(timeout=600)
            if proc.returncode != 0:
                prog("Failed", "See console for details")
                return False
        except Exception as e:
            prog("Failed", str(e)[:80])
            return False
    else:
        prog("Installing OpenCV...", "")
        ok = install_package("opencv-python", progress_callback)
        return ok

    return True


def uninstall_opencv(progress_callback=None) -> bool:
    """Remove OpenCV from venv (standard and cudawarped CUDA wheel)."""
    pip = get_pip_exe()
    if not pip.exists():
        return False
    r = subprocess.run(
        [str(pip), "uninstall", "-y",
         "opencv-python", "opencv-python-headless",
         "opencv-contrib-python", "opencv-contrib-python-headless"],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode == 0


def install_package(pkg: str, progress_callback=None) -> bool:
    """Install a single package into app venv."""
    venv = get_venv_path()
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
    )
    for line in iter(proc.stdout.readline, "") if proc.stdout else []:
        line = (line or "").strip()
        if line:
            prog(f"Installing {pkg}...", line[:100])
    proc.wait(timeout=300)
    return proc.returncode == 0


def remove_venv() -> bool:
    """Remove the app venv. Returns True on success."""
    import shutil
    venv = get_venv_path()
    if venv.exists():
        try:
            shutil.rmtree(venv)
            return True
        except OSError:
            pass
    return False


def add_venv_to_path():
    """Add venv site-packages to sys.path (call before importing app deps)."""
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
