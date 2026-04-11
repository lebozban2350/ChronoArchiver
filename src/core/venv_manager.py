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
from typing import Optional

try:
    from .debug_logger import debug, UTILITY_OPENCV_INSTALL
    from .http_utils import requests_get_stream_with_retries
except ImportError:
    from core.debug_logger import debug, UTILITY_OPENCV_INSTALL
    from core.http_utils import requests_get_stream_with_retries

try:
    from .subprocess_tee import tee_line, win_hide_kw
except ImportError:
    from core.subprocess_tee import tee_line, win_hide_kw

from . import app_paths


def _is_frozen() -> bool:
    """True when running as PyInstaller bundle (no venv)."""
    return getattr(sys, "frozen", False)


OPENCV_CUDA_API = "https://api.github.com/repos/cudawarped/opencv-python-cuda-wheels/releases/latest"
OPENCV_STANDARD_APPROX_BYTES = 90 * 1024 * 1024  # ~90 MB
# Fallback when API unavailable: cudawarped wheel ~500 MB
OPENCV_CUDA_FALLBACK_BYTES = 506 * 1024 * 1024

# Base venv only — no OpenCV. AI Scanner installs: NVIDIA → CUDA wheel + stack; AMD/Intel/other → opencv-python (OpenCL), same as before.
VENV_PACKAGES_BASE = [
    "PySide6-Essentials",
    "numpy",
    "psutil",
    "requests",
    "Pillow",
    "platformdirs",
    "piexif",
    "static-ffmpeg",
    "GitPython",
]

# New venvs: prefer newest Python on the host in this inclusive range (PyTorch CUDA: cu124 for 3.9–3.13, cu130 for 3.14+).
VENV_PYTHON_MIN = (3, 9)
VENV_PYTHON_MAX_LINUX_WIN = (3, 14)
VENV_PYTHON_MAX_DARWIN = (3, 14)


def _vendor_rank(v: str) -> int:
    """NVIDIA > AMD > Intel (matches OpenCV / PyTorch install precedence)."""
    return {"nvidia": 3, "amd": 2, "intel": 1}.get(v, 0)


def _pci_bdf_normalize(s: str) -> str:
    """Normalize PCI bus id from lspci or nvidia-smi (e.g. ``00000000:01:00.0`` → ``01:00.0``)."""
    m = re.search(r"([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])", (s or "").lower())
    return m.group(1) if m else ""


def _lspci_line_bus_bdf(line: str) -> str:
    """
    First PCI BDF on an ``lspci -nn`` line. Supports ``01:00.0`` and ``0000:01:00.0`` (4-digit domain).
    Without this, hybrid laptops often fail to match ``nvidia-smi``, and the footer falls back to the wrong GPU.
    """
    s = (line or "").strip()
    m = re.match(
        r"^(?:[0-9a-f]{4}:)?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\s",
        s,
        re.I,
    )
    return m.group(1).lower() if m else ""


def _bdf_from_nvidia_smi_L_line(line: str) -> str:
    """Extract normalized ``bb:dd.f`` from one ``nvidia-smi -L`` line if present."""
    # Long form: 0000:01:00.0 or 00000000:01:00.0
    mm = re.search(r"\b([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\b", line, re.I)
    if mm:
        return _pci_bdf_normalize(mm.group(1))
    mm2 = re.search(r"\b([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\b", line, re.I)
    if mm2:
        return mm2.group(1).lower()
        # "at PCI:1:0:0" (bus:device.function as decimal / hex)
        mm3 = re.search(r"PCI:\s*([0-9a-fx]+):([0-9a-fx]+):([0-9a-fx]+)", line, re.I)
        if mm3:
            try:
                bus, dev, fn = (int(mm3.group(i), 0) for i in (1, 2, 3))
                return f"{bus & 0xFF:02x}:{dev & 0xFF:02x}.{fn & 0x7:x}"
            except ValueError:
                pass
    return ""


def _nvidia_smi_L_index_to_bdf() -> dict[int, str]:
    """``nvidia-smi -L``: GPU index → normalized PCI BDF (authoritative vs CSV when lspci matching fails)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {}
    try:
        out = subprocess.check_output(
            [smi, "-L"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
            **win_hide_kw(),
        )
    except Exception:
        return {}
    m: dict[int, str] = {}
    for raw in (out or "").splitlines():
        line = raw.strip()
        mi = re.match(r"GPU\s+(\d+)\s*:", line, re.I)
        if not mi:
            continue
        idx = int(mi.group(1))
        bdf = _bdf_from_nvidia_smi_L_line(line)
        if bdf:
            m[idx] = bdf
    return m


def _linux_lspci_display_controller_rows() -> list[tuple[str, str, bool]]:
    """
    Parse lspci display controllers in bus order: (vendor_key, pci_bdf, is_integrated_heuristic).
    ``pci_bdf`` is normalized ``bb:dd.f`` for matching ``nvidia-smi`` pci.bus_id.
    """
    cand: list[tuple[str, str, bool]] = []
    try:
        r = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True,
            text=True,
            timeout=6,
            **win_hide_kw(),
        )
        if r.returncode != 0:
            return []
        for line in (r.stdout or "").splitlines():
            if not re.search(
                r"VGA compatible controller|3D controller|Display controller",
                line,
                re.I,
            ):
                continue
            bdf = _lspci_line_bus_bdf(line)
            lc = line.lower()
            vendor = ""
            if re.search(r"\b10de:|\[10de:|\bnvidia\b", line, re.I):
                vendor = "nvidia"
            elif re.search(r"\b1002:|\[1002:|\bamd\b|\bradeon\b|\bati technologies\b", line, re.I):
                vendor = "amd"
            elif re.search(r"\b8086:|\[8086:|\bintel\b", line, re.I):
                vendor = "intel"
            if not vendor:
                continue
            if vendor == "nvidia":
                integrated = "integrated" in lc
            elif vendor == "amd":
                integrated = "integrated" in lc
            else:
                discrete_intel = any(
                    x in lc
                    for x in (
                        "arc",
                        "dg2",
                        "a770",
                        "a750",
                        "a730",
                        "a580",
                        "a380",
                        "a310",
                        "iris xe max",
                    )
                )
                integrated = not discrete_intel
            cand.append((vendor, bdf, integrated))
    except Exception:
        pass
    return cand


def _linux_lspci_gpu_candidates() -> list[tuple[str, bool]]:
    """
    Parse lspci display controllers: list of (vendor_key, is_integrated_heuristic).
    Used on Linux for discrete-before-integrated ordering.
    """
    return [(v, integrated) for v, _bdf, integrated in _linux_lspci_display_controller_rows()]


def _pick_vendor_prefer_discrete(candidates: list[tuple[str, bool]]) -> str:
    """
    Prefer discrete (non-integrated) adapters, then vendor: NVIDIA > AMD > Intel.
    """
    if not candidates:
        return ""
    non_i = [c for c in candidates if not c[1]]
    pool = non_i if non_i else candidates
    best = max(pool, key=lambda c: (_vendor_rank(c[0]),))
    return best[0]


# Footer / status metrics: which NVIDIA adapter index `nvidia-smi` should query (discrete-first, same policy as ``detect_gpu``).
_footer_metrics_nv_index: int | None = None


def preferred_nvidia_gpu_index_for_metrics() -> int:
    """
    Return the NVIDIA GPU index for footer **GPU %** (``nvidia-smi -i``), aligned with
    ``detect_gpu()`` / ``_pick_vendor_prefer_discrete``: discrete before integrated, then vendor rank.

    ``CHRONOARCHIVER_FOOTER_NVIDIA_GPU`` or ``CHRONOARCHIVER_FFMPEG_NVENC_GPU`` (integer) overrides when valid.

    PCI matching uses ``nvidia-smi -L`` (primary) plus CSV ``pci.bus_id``, and ``lspci`` BDFs with domain
    prefix support so the **discrete** NVIDIA card is chosen instead of falling back to index 0 (often wrong on hybrid iGPU + dGPU laptops).

    Result is cached for the process lifetime.
    """
    global _footer_metrics_nv_index
    if _footer_metrics_nv_index is not None:
        return _footer_metrics_nv_index

    smi = shutil.which("nvidia-smi")
    if not smi:
        _footer_metrics_nv_index = 0
        return 0

    try:
        out = subprocess.check_output(
            [
                smi,
                "--query-gpu=index,pci.bus_id,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
            **win_hide_kw(),
        )
    except Exception:
        _footer_metrics_nv_index = 0
        return 0

    rows: list[tuple[int, str, int]] = []
    for ln in (out or "").strip().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 2:
            continue
        try:
            idx = int(float(parts[0]))
        except ValueError:
            continue
        pci_raw = parts[1] if len(parts) > 1 else ""
        mem_mb = 0
        if len(parts) > 2:
            try:
                mem_mb = int(float(parts[2]))
            except ValueError:
                pass
        bdf = _pci_bdf_normalize(pci_raw)
        rows.append((idx, bdf, mem_mb))

    if not rows:
        _footer_metrics_nv_index = 0
        return 0

    indices = {r[0] for r in rows}
    gpu_env = (
        os.environ.get("CHRONOARCHIVER_FOOTER_NVIDIA_GPU") or os.environ.get("CHRONOARCHIVER_FFMPEG_NVENC_GPU") or ""
    ).strip()
    if gpu_env:
        try:
            want = int(gpu_env)
            if want in indices:
                _footer_metrics_nv_index = want
                return want
        except ValueError:
            pass

    if len(rows) == 1:
        _footer_metrics_nv_index = rows[0][0]
        return rows[0][0]

    # BDF → index: merge CSV pci.bus_id with ``nvidia-smi -L`` (latter wins per index).
    l_map = _nvidia_smi_L_index_to_bdf()
    smi_by_bdf: dict[str, int] = {}
    for idx, bdf_csv, _mem in rows:
        if bdf_csv:
            smi_by_bdf[bdf_csv] = idx
    for idx, bdf_l in l_map.items():
        smi_by_bdf[bdf_l] = idx

    if platform.system() == "Linux":
        full = _linux_lspci_display_controller_rows()
        nv_lines = [(v, bdf, ig) for v, bdf, ig in full if v == "nvidia" and bdf]
        if nv_lines:
            non_i = [x for x in nv_lines if not x[2]]
            pool = non_i if non_i else nv_lines
            for _v, bdf, _ig in pool:
                if bdf in smi_by_bdf:
                    _footer_metrics_nv_index = smi_by_bdf[bdf]
                    return smi_by_bdf[bdf]

    best_idx, _bdf, _m = max(rows, key=lambda t: t[2])
    _footer_metrics_nv_index = best_idx
    return best_idx


def _parse_nvidia_smi_util_csv_cell(s: str) -> Optional[int]:
    t = (s or "").strip()
    if not t or t.upper() in ("N/A", "[N/A]"):
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def footer_nvidia_gpu_utilization_text() -> str:
    """
    ``nvidia-smi`` utilization for ``preferred_nvidia_gpu_index_for_metrics()``, formatted like ``' 12%'``
    (fixed width for UI) or ``'  N/A'`` on failure.

    Uses the max of ``utilization.gpu`` and ``utilization.encoder`` when both exist, so NVENC-heavy work shows up
    even when SM utilization stays low (common on hybrid laptops).
    """
    smi = shutil.which("nvidia-smi")
    if not smi:
        return "  N/A"
    idx = preferred_nvidia_gpu_index_for_metrics()

    def _query(fields: str) -> str:
        return subprocess.check_output(
            [
                smi,
                "-i",
                str(idx),
                "--query-gpu=" + fields,
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
            **win_hide_kw(),
        ).strip()

    try:
        out = _query("utilization.gpu,utilization.encoder")
    except Exception:
        try:
            out = _query("utilization.gpu")
        except Exception:
            return "  N/A"
    line0 = (out or "").split("\n")[0].strip() if out else ""
    parts = [p.strip() for p in line0.split(",")] if line0 else []
    vals: list[int] = []
    if parts:
        v0 = _parse_nvidia_smi_util_csv_cell(parts[0])
        if v0 is not None:
            vals.append(v0)
        if len(parts) > 1:
            v1 = _parse_nvidia_smi_util_csv_cell(parts[1])
            if v1 is not None:
                vals.append(v1)
    g = max(vals) if vals else 0
    return f"{min(999, g):3d}%"


def detect_gpu() -> str:
    """
    Return 'nvidia', 'amd', 'intel', or ''.

    Precedence (same idea as AI Image Upscaler engine hints):
    - **API stack**: CUDA (NVIDIA) > OpenCL (AMD/Intel) for OpenCV; PyTorch uses CUDA only on NVIDIA.
    - **Vendor**: NVIDIA > AMD > Intel when choosing among adapters.
    - **Role**: discrete GPU before integrated when both are visible (Windows WMI; Linux lspci).

    Linux: prefer `lspci` classification with discrete-first pick, then sysfs / lspci fallbacks.
    """
    found = {"nvidia": False, "amd": False, "intel": False}

    # Windows: Prefer NVIDIA when present (hybrid APU/iGPU + RTX): WMI AdapterRAM is often 0 for new
    # dGPUs, so sorting by VRAM alone incorrectly picks the integrated AMD GPU over an RTX card.
    if platform.system() == "Windows":
        try:
            smi = shutil.which("nvidia-smi")
            if smi:
                r = subprocess.run(
                    [smi, "-L"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **win_hide_kw(),
                )
                if r.returncode == 0 and r.stdout and re.search(r"\bNVIDIA\b", r.stdout, re.I):
                    return "nvidia"
        except Exception:
            pass

        try:
            ps_cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM,VideoProcessor,Description | "
                "ConvertTo-Json -Compress"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                **win_hide_kw(),
            )
            if proc.returncode == 0 and (proc.stdout or "").strip():
                data = json.loads(proc.stdout)
                if isinstance(data, dict):
                    entries = [data]
                else:
                    entries = list(data)

                def _parse_vendor(s: str) -> str:
                    t = (s or "").lower()
                    if "nvidia" in t or "geforce" in t or "rtx" in t or "quadro" in t or "tesla" in t:
                        return "nvidia"
                    if "amd" in t or "radeon" in t:
                        return "amd"
                    if "intel" in t:
                        return "intel"
                    return ""

                candidates: list[tuple[int, bool, str]] = []  # (adapterRAM, integrated, vendor)
                for e in entries:
                    name = e.get("Name") or ""
                    desc = e.get("Description") or ""
                    vp = e.get("VideoProcessor") or ""
                    adapter_ram_raw = e.get("AdapterRAM")
                    try:
                        adapter_ram = int(adapter_ram_raw) if adapter_ram_raw else 0
                    except (TypeError, ValueError):
                        adapter_ram = 0

                    blob = f"{name} {desc} {vp}"
                    vendor = _parse_vendor(blob)
                    if not vendor:
                        continue

                    is_integrated = "integrated" in blob.lower()
                    candidates.append((adapter_ram, is_integrated, vendor))

                # Prefer discrete when listed; else any adapter.
                non_int = [c for c in candidates if not c[1]]
                pick_from = non_int if non_int else candidates
                if pick_from:
                    # Primary: vendor rank (NVIDIA over AMD over Intel). tie-break: AdapterRAM.
                    _, _, vendor = max(pick_from, key=lambda x: (_vendor_rank(x[2]), x[0]))
                    return vendor
        except Exception:
            pass

    # 1) NVIDIA direct check (most reliable when available)
    try:
        smi = shutil.which("nvidia-smi")
        if smi:
            r = subprocess.run(
                [smi, "-L"],
                capture_output=True,
                text=True,
                timeout=3,
                **win_hide_kw(),
            )
            if r.returncode == 0 and re.search(r"\bNVIDIA\b", (r.stdout or "") + (r.stderr or ""), re.I):
                found["nvidia"] = True
    except Exception:
        pass

    if found["nvidia"]:
        return "nvidia"

    # Linux: structured lspci list — discrete before integrated; NVIDIA > AMD > Intel
    if platform.system() == "Linux":
        cand = _linux_lspci_gpu_candidates()
        if cand:
            picked = _pick_vendor_prefer_discrete(cand)
            if picked:
                try:
                    debug(
                        UTILITY_OPENCV_INSTALL,
                        f"detect_gpu: lspci pick={picked} candidates={cand}",
                    )
                except Exception:
                    pass
                return picked

    # 2) sysfs scan: /sys/class/drm/card*/device/vendor
    try:
        drm = Path("/sys/class/drm")
        if drm.is_dir():
            for card in drm.glob("card*"):
                try:
                    vendor_file = card / "device" / "vendor"
                    if not vendor_file.is_file():
                        continue
                    vendor = vendor_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                    # Vendor IDs: NVIDIA=0x10de, AMD=0x1002, Intel=0x8086
                    if "0x10de" in vendor:
                        found["nvidia"] = True
                    elif "0x1002" in vendor:
                        found["amd"] = True
                    elif "0x8086" in vendor:
                        found["intel"] = True
                except Exception:
                    continue
    except Exception:
        pass

    # 3) lspci fallback (hybrid-friendly): look only at display controller lines
    try:
        if not (found["nvidia"] or found["amd"] or found["intel"]):
            r = subprocess.run(
                ["lspci", "-nnk"],
                capture_output=True,
                text=True,
                timeout=4,
                **win_hide_kw(),
            )
            out = (r.stdout or "") if r.returncode == 0 else ""
            for line in out.splitlines():
                if not re.search(r"(VGA compatible controller|3D controller|Display controller)", line, re.I):
                    continue
                line_lc = line.lower()
                if ("nvidia" in line_lc) or ("10de" in line_lc):
                    found["nvidia"] = True
                elif ("advanced micro devices" in line_lc) or ("amd" in line_lc) or ("1002" in line_lc):
                    found["amd"] = True
                elif ("intel" in line_lc) or ("8086" in line_lc):
                    found["intel"] = True
    except Exception:
        pass

    try:
        debug(
            UTILITY_OPENCV_INSTALL,
            "detect_gpu: " + f"nvidia={found['nvidia']} amd={found['amd']} intel={found['intel']}",
        )
    except Exception:
        pass

    if found["nvidia"]:
        return "nvidia"
    if found["amd"]:
        return "amd"
    if found["intel"]:
        return "intel"
    return ""


def get_ml_torch_install_variant() -> str:
    """
    PyTorch pip variant for Z-Image / ml_runtime (parity with OpenCV GPU precedence).
    - **cuda**: Linux/Windows when **detect_gpu() == "nvidia"** (published cu12x wheels).
    - **cpu**: macOS (no CUDA), AMD/Intel, or unknown — PyPI CPU wheels (PyTorch has no OpenCL wheel).
    """
    if platform.system() == "Darwin":
        return "cpu"
    if detect_gpu() == "nvidia":
        return "cuda"
    return "cpu"


def get_ml_torch_install_label() -> str:
    """Human-readable install line for dialogs (mirrors OpenCV variant labels)."""
    if platform.system() == "Darwin":
        return "PyTorch (CPU — macOS)"
    gpu = detect_gpu()
    if gpu == "nvidia":
        return "PyTorch (CUDA — NVIDIA)"
    if gpu == "amd":
        return "PyTorch (CPU — AMD; OpenCL N/A for torch)"
    if gpu == "intel":
        return "PyTorch (CPU — Intel; OpenCL N/A for torch)"
    return "PyTorch (CPU)"


def format_pytorch_ready_line() -> tuple[str, str]:
    """
    Shared PyTorch **READY** line for AI Image Upscaler and AI Video Upscaler.
    Uses the same rules as runtime: CUDA when `torch.cuda.is_available()`, else CPU.
    Returns (label, tooltip).
    """
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            suf = name[:28] + "…" if len(name) > 28 else name
            return (f"READY · CUDA · {suf}" if suf else "READY · CUDA"), ""
        tip = "PyTorch on CPU (typical for AMD/Intel, macOS, or no NVIDIA CUDA). Runs are slower than on NVIDIA CUDA."
        return "READY · CPU", tip
    except Exception:
        tip = "PyTorch on CPU (typical for AMD/Intel, macOS, or no NVIDIA CUDA). Runs are slower than on NVIDIA CUDA."
        return "READY · CPU", tip


def get_opencv_variant() -> str:
    """
    Variant for **AI Scanner → Install OpenCV** only (not installed by setup/bootstrap).
    **GPU precedence** (same as `detect_gpu`): discrete before integrated; **NVIDIA > AMD > Intel**;
    **CUDA** (NVIDIA) before **OpenCL** (AMD/Intel) for this OpenCV wheel choice.
    - 'cuda': NVIDIA → CUDA wheel + pip CUDA stack
    - 'opencl_amd': AMD primary → opencv-python (OpenCL)
    - 'opencl_intel': Intel primary → opencv-python (OpenCL)
    - 'opencl': fallback when no vendor detected
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
        "cuda": "OpenCV (CUDA build)",
        "opencl_amd": "OpenCV (OpenCL — AMD Radeon)",
        "opencl_intel": "OpenCV (OpenCL — Intel)",
        "opencl": "OpenCV (OpenCL)",
    }.get(v, "OpenCV (OpenCL)")


def get_opencv_package() -> str:
    """PyPI name for non-CUDA OpenCV (OpenCL) when installing from AI Scanner — opencv-python, not the CUDA wheel."""
    return "opencv-python"


def get_venv_packages() -> list:
    """Packages for ensure_venv / pip install -r requirements.txt (OpenCV only via AI Scanner)."""
    return list(VENV_PACKAGES_BASE)


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


def _venv_python_ceiling() -> tuple[int, int]:
    return VENV_PYTHON_MAX_DARWIN if platform.system() == "Darwin" else VENV_PYTHON_MAX_LINUX_WIN


def _version_in_venv_range(ver: tuple[int, int]) -> bool:
    return VENV_PYTHON_MIN <= ver <= _venv_python_ceiling()


def _version_tuple_from_command(cmd_base: list[str]) -> tuple[int, int] | None:
    try:
        r = subprocess.run(
            cmd_base + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=30,
            **win_hide_kw(),
        )
        if r.returncode != 0:
            return None
        parts = r.stdout.strip().split()
        if len(parts) < 2:
            return None
        return int(parts[0]), int(parts[1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def get_venv_python_creator_cmd() -> list[str] | None:
    """
    argv prefix for: <cmd> -m venv <path>
    Prefer newest 3.14 … 3.9 on PATH (or Windows `py -3.x`); None if none in range.
    """
    system = platform.system()

    ceiling_m = _venv_python_ceiling()[1]

    if system == "Windows":
        for minor in range(ceiling_m, VENV_PYTHON_MIN[1] - 1, -1):
            base = ["py", f"-3.{minor}"]
            ver = _version_tuple_from_command(base)
            if ver and _version_in_venv_range(ver):
                debug(UTILITY_OPENCV_INSTALL, f"venv: create with {' '.join(base)} (Python {ver[0]}.{ver[1]})")
                return base
    else:
        for minor in range(ceiling_m, VENV_PYTHON_MIN[1] - 1, -1):
            exe = shutil.which(f"python3.{minor}")
            if not exe:
                continue
            base = [exe]
            ver = _version_tuple_from_command(base)
            if ver and _version_in_venv_range(ver):
                debug(UTILITY_OPENCV_INSTALL, f"venv: create with {exe} (Python {ver[0]}.{ver[1]})")
                return base
        p3 = shutil.which("python3")
        if p3:
            ver = _version_tuple_from_command([p3])
            if ver and _version_in_venv_range(ver):
                debug(UTILITY_OPENCV_INSTALL, f"venv: create with {p3} (Python {ver[0]}.{ver[1]})")
                return [p3]

    ver = _version_tuple_from_command([sys.executable])
    if ver and _version_in_venv_range(ver):
        debug(UTILITY_OPENCV_INSTALL, f"venv: create with sys.executable {sys.executable} ({ver[0]}.{ver[1]})")
        return [sys.executable]

    hi = _venv_python_ceiling()
    debug(
        UTILITY_OPENCV_INSTALL,
        "venv: no Python in %s.%s–%s.%s range found on PATH" % (VENV_PYTHON_MIN[0], VENV_PYTHON_MIN[1], hi[0], hi[1]),
    )
    return None


def venv_interpreter_version() -> tuple[int, int] | None:
    py = get_python_exe()
    if not py.is_file():
        return None
    return _version_tuple_from_command([str(py)])


def _running_inside_venv_tree(venv: Path) -> bool:
    try:
        pref = Path(sys.prefix).resolve()
        root = venv.resolve()
        return pref == root or str(pref).startswith(str(root) + os.sep)
    except OSError:
        return False


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
    py = get_python_exe()
    if not py.exists():
        debug(UTILITY_OPENCV_INSTALL, "check_opencv_in_venv: python exe not found")
        return False
    _add_nvidia_libs_to_ld_path()
    env = os.environ.copy()
    try:
        r = subprocess.run(
            [str(py), "-c", "import cv2"],
            capture_output=True,
            timeout=5,
            env=env,
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
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [
                str(py),
                "-c",
                (
                    "import os; "
                    "from static_ffmpeg.run import get_platform_dir; "
                    "crumb = os.path.join(get_platform_dir(), 'installed.crumb'); "
                    "exit(0 if os.path.isfile(crumb) else 1)"
                ),
            ],
            capture_output=True,
            timeout=10,
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
                [
                    str(py),
                    "-c",
                    (
                        "from static_ffmpeg.run import get_or_fetch_platform_executables_else_raise; "
                        "get_or_fetch_platform_executables_else_raise()"
                    ),
                ],
                capture_output=True,
                timeout=600,
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

        with requests_get_stream_with_retries(url, stream=True, timeout=TIMEOUT, attempts=3) as req:
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


def check_venv_bootstrap_prereqs(py_exe: Path) -> tuple[bool, str]:
    """
    Verify the host Python can create a venv with pip (ensurepip / venv module).
    On some Linux distros users must install the ``python-venv`` / ``python-ensurepip`` package.
    """
    if not py_exe.is_file():
        return False, f"Interpreter not found: {py_exe}"
    try:
        r = subprocess.run(
            [str(py_exe), "-c", "import venv, ensurepip"],
            capture_output=True,
            text=True,
            timeout=15,
            **win_hide_kw(),
        )
        if r.returncode == 0:
            return True, ""
        err = ((r.stderr or "") + (r.stdout or "")).strip()[:500]
        return False, err or "venv/ensurepip not available"
    except FileNotFoundError:
        return False, f"Interpreter not found: {py_exe}"
    except Exception as e:
        return False, str(e)[:500]


def is_venv_runnable() -> bool:
    """True if venv exists and can run the app (PySide6, PIL, requests). Does NOT require OpenCV."""
    if _is_frozen():
        return True
    py = get_python_exe()
    if not py.exists():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import PySide6; import PIL; import requests"],
            capture_output=True,
            timeout=5,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_venv(progress_callback=None) -> bool:
    """
    Create venv and install base packages (no OpenCV). progress_callback(phase, detail, pct=None).
    Returns True on success. No-op when frozen.
    """
    if _is_frozen():
        return True
    data = app_paths.data_dir()
    venv = get_venv_path()
    data.mkdir(parents=True, exist_ok=True)

    def prog(phase, detail="", pct=None):
        if progress_callback:
            progress_callback(phase, detail, pct)

    if get_python_exe().exists():
        ver = venv_interpreter_version()
        if ver and not _version_in_venv_range(ver):
            if _running_inside_venv_tree(venv):
                hi = _venv_python_ceiling()
                prog(
                    "Venv Python not supported",
                    f"This venv is Python {ver[0]}.{ver[1]}. Exit ChronoArchiver, delete this folder, "
                    f"then restart: {venv}",
                    0,
                )
                debug(
                    UTILITY_OPENCV_INSTALL,
                    f"ensure_venv: Python {ver[0]}.{ver[1]} outside {VENV_PYTHON_MIN}–{hi} "
                    f"while running inside venv — recreate manually",
                )
                return False
            hi = _venv_python_ceiling()
            prog(
                "Removing incompatible venv…",
                f"Replacing Python {ver[0]}.{ver[1]} with {VENV_PYTHON_MIN[0]}.{VENV_PYTHON_MIN[1]}–"
                f"{hi[0]}.{hi[1]} for installers/ML stack.",
                0,
            )
            shutil.rmtree(venv, ignore_errors=True)

    if not (venv / "bin" / "python").exists() and not (venv / "Scripts" / "python.exe").exists():
        prog("Creating virtual environment...", "", 0)
        creator = get_venv_python_creator_cmd()
        if not creator:
            hi = _venv_python_ceiling()
            prog(
                "No suitable Python for venv",
                f"Install Python 3.{hi[1]} or 3.12 (any in 3.{VENV_PYTHON_MIN[1]}–3.{hi[1]}) and restart.",
                0,
            )
            return False
        py_create = Path(creator[0])
        ok_pre, err_pre = check_venv_bootstrap_prereqs(py_create)
        if not ok_pre:
            prog(
                "Python venv prerequisites missing",
                (err_pre or "Install python-venv / ensurepip on your system.") + f"  Interpreter: {py_create}",
                0,
            )
            debug(UTILITY_OPENCV_INSTALL, f"ensure_venv: bootstrap prereq failed: {err_pre}")
            return False
        r = subprocess.run(
            creator + ["-m", "venv", str(venv)],
            capture_output=True,
            text=True,
            timeout=180,
            **win_hide_kw(),
        )
        if r.returncode != 0:
            err = ((r.stderr or "") + (r.stdout or "")).strip()[:400]
            prog("venv creation failed", err or "unknown error", 0)
            debug(UTILITY_OPENCV_INSTALL, f"ensure_venv: venv failed rc={r.returncode} err={err}")
            return False

    pip = get_pip_exe()
    if not pip.exists():
        prog("venv pip not found", "", 0)
        return False

    packages = get_venv_packages()
    n = len(packages)
    for i, pkg in enumerate(packages):
        prog(f"Installing {pkg} ({i + 1}/{n})...", "", 100.0 * i / n)
        proc = subprocess.Popen(
            [str(pip), "install", pkg],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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


# Approximate sizes for NVIDIA pip packages (venv install, no sudo)
NVIDIA_CUDA_RUNTIME_APPROX_BYTES = int(2.2 * 1024 * 1024)  # ~2.2 MB
NVIDIA_CUBLAS_APPROX_BYTES = int(384 * 1024 * 1024)  # ~384 MB (manylinux x86_64 wheel)
NVIDIA_CUDNN_APPROX_BYTES = int(366 * 1024 * 1024)  # ~366 MB
NVIDIA_CUFFT_APPROX_BYTES = int(25 * 1024 * 1024)  # ~25 MB (libcufft.so.12 for OpenCV CUDA wheel)

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
            capture_output=True,
            text=True,
            timeout=5,
            **win_hide_kw(),
        )
        return r.returncode == 0
    except Exception:
        return False


def _install_cuda_cudnn_venv(progress_callback=None) -> tuple[bool, str | None]:
    """Install CUDA and cuDNN via pip into app venv (no sudo). Returns (success, error)."""

    def prog(msg, detail="", downloaded=0, total=0):
        """
        progress_callback(phase, detail, downloaded_bytes, total_bytes)
        Some callers provide only (msg, detail), others pass 4 args; keep it permissive.
        """
        if progress_callback:
            progress_callback(msg, detail, downloaded, total)

    pip = get_pip_exe()
    if not pip.exists():
        debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN install: venv not ready")
        return False, "venv not ready"

    debug(UTILITY_OPENCV_INSTALL, "CUDA/cuDNN/cuFFT install: starting pip install (~775 MB, may take 2–5 min)")
    t0 = time.monotonic()
    prog("Installing CUDA runtime, cuBLAS, cuFFT, and cuDNN...", "Downloading ~775 MB (may take 2–5 min)...", 0, 0)
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
            elapsed_s = time.monotonic() - t0
            tail = out_lines[-5:] if out_lines else []
            tail_str = (" | ".join(tail))[:800] if tail else ""
            debug(
                UTILITY_OPENCV_INSTALL,
                f"CUDA/cuDNN install: success elapsed={elapsed_s:.1f}s lines={len(out_lines)} tail={tail_str}",
            )
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
        [
            str(pip),
            "uninstall",
            "-y",
            "opencv-python",
            "opencv-python-headless",
            "opencv-contrib-python",
            "opencv-contrib-python-headless",
            "opencv-openvino-contrib-python",
        ],
        capture_output=True,
        timeout=60,
        **win_hide_kw(),
    )

    wheel_path: Path | None = None
    try:
        # Use CUDA path only when the caller selected variant="cuda".
        # Do not re-detect GPU again here (variant is already computed once for the UI flow).
        if v == "cuda":
            if not _is_cuda_cudnn_installed():
                prog("Installing CUDA runtime and cuDNN...", "pip install into venv...", 0, 0)
                ok_venv, err_venv = _install_cuda_cudnn_venv(lambda msg, det, d, t: prog(msg, det, d, t))
                if not ok_venv:
                    debug(UTILITY_OPENCV_INSTALL, f"install_opencv FAIL at CUDA/cuDNN: {err_venv}")
                    prog("Failed", err_venv[:80] if err_venv else "Could not install CUDA/cuDNN", 0, 0)
                    return False, err_venv or "Could not install CUDA/cuDNN"
            if not requests:
                return False, "requests module required for wheel download"
        if v == "cuda" and requests:
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
                dl_t0 = time.monotonic()
                wheel_path = _download_wheel_with_progress(
                    wheel_url,
                    lambda p, d, down, tot: prog(p, d, down, tot),
                    total_hint=wheel_size,
                )
                dl_elapsed_s = time.monotonic() - dl_t0
                if wheel_path and wheel_path.exists():
                    st = wheel_path.stat()
                    debug(
                        UTILITY_OPENCV_INSTALL,
                        f"install_opencv: CUDA wheel download done bytes={st.st_size} elapsed={dl_elapsed_s:.1f}s hint={wheel_size}",
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
                dl_t0 = time.monotonic()
                wheel_path = _download_wheel_with_progress(
                    wheel_url,
                    lambda p, d, down, tot: prog(p, d, down, tot),
                    total_hint=wheel_size or OPENCV_STANDARD_APPROX_BYTES,
                )
                dl_elapsed_s = time.monotonic() - dl_t0
                if wheel_path and wheel_path.exists():
                    st = wheel_path.stat()
                    debug(
                        UTILITY_OPENCV_INSTALL,
                        f"install_opencv: standard wheel download done bytes={st.st_size} elapsed={dl_elapsed_s:.1f}s hint={wheel_size}",
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
        pip_t0 = time.monotonic()
        proc_w = subprocess.Popen(
            [str(pip), "install", str(wheel_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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
        pip_elapsed_s = time.monotonic() - pip_t0
        try:
            wheel_path.unlink()
            parent = wheel_path.parent
            if parent != Path(tempfile.gettempdir()) and parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
        except OSError:
            pass
        if proc_w.returncode != 0:
            err = "\n".join(acc_lines[-40:]) or "Unknown error"
            debug(
                UTILITY_OPENCV_INSTALL,
                f"install_opencv FAIL pip install wheel rc={proc_w.returncode} elapsed={pip_elapsed_s:.1f}s tail={err[:800]}",
            )
            prog("Failed", err[:80], 0, 0)
            return False, err
        debug(UTILITY_OPENCV_INSTALL, f"install_opencv SUCCESS, elapsed={pip_elapsed_s:.1f}s lines={len(acc_lines)}")
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
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
        "opencv-openvino-contrib-python",
        # CUDA stack (pip installs into venv; safe to uninstall even if not present)
        "nvidia-cudnn-cu13",
        "nvidia-cuda-runtime",
        "nvidia-cublas",
        "nvidia-cufft",
    ]
    r = subprocess.run(
        [str(pip), "uninstall", "-y", *packages],
        capture_output=True,
        text=True,
        timeout=120,
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
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
    """Remove the app venv (ignore_errors=True for partially broken trees). Returns True if gone."""
    venv = get_venv_path()
    if not venv.exists():
        return True
    shutil.rmtree(venv, ignore_errors=True)
    return not venv.exists()


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
