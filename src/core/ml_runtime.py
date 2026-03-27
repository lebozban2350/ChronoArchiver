"""Install / remove PyTorch + diffusers stack via pip (used by Z-Image Pro Upscaler)."""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from typing import Optional

try:
    from .debug_logger import UTILITY_APP, UTILITY_INSTALLER_POPUP, debug as _debug_log
except ImportError:
    from core.debug_logger import UTILITY_APP, UTILITY_INSTALLER_POPUP, debug as _debug_log

try:
    from .venv_manager import VENV_PYTHON_MAX_LINUX_WIN, VENV_PYTHON_MIN, get_ml_torch_install_variant
except ImportError:
    from core.venv_manager import VENV_PYTHON_MAX_LINUX_WIN, VENV_PYTHON_MIN, get_ml_torch_install_variant

ProgressCB = Callable[[str, str, int, int], None]


def _cuda_torch_supported_python() -> tuple[bool, str]:
    """
    Published PyTorch + CUDA wheels lag the latest CPython; pip otherwise fails opaquely
    ("No matching distribution found for torch").
    """
    major, minor = sys.version_info[:2]
    if (major, minor) > VENV_PYTHON_MAX_LINUX_WIN:
        return False, (
            f"Python {major}.{minor} is not supported by published PyTorch CUDA wheels yet "
            f"(bundled install targets {VENV_PYTHON_MIN[0]}.{VENV_PYTHON_MIN[1]}–"
            f"{VENV_PYTHON_MAX_LINUX_WIN[0]}.{VENV_PYTHON_MAX_LINUX_WIN[1]}). "
            "Recreate the ChronoArchiver venv, then retry."
        )
    if (major, minor) < VENV_PYTHON_MIN:
        return False, (
            f"Python {major}.{minor} is too old for the bundled PyTorch install path "
            f"(need {VENV_PYTHON_MIN[0]}.{VENV_PYTHON_MIN[1]}+)."
        )
    return True, ""


def estimate_ml_runtime_components() -> tuple[list[tuple[str, int]], int]:
    """
    Return ([(label, approx_bytes), ...], total_bytes) for the pip-based install.
    Coarse estimates used only for UI sizing/progress display.
    """
    use_cuda = get_ml_torch_install_variant() == "cuda"
    if use_cuda:
        components = [
            ("torch (CUDA/cu124 wheel)", int(2.80 * 1024**3)),
            ("torchvision", int(0.35 * 1024**3)),
            ("diffusers + transformers stack", int(0.50 * 1024**3)),
        ]
    else:
        components = [
            ("torch (CPU wheel)", int(0.65 * 1024**3)),
            ("torchvision", int(0.20 * 1024**3)),
            ("diffusers + transformers stack", int(0.30 * 1024**3)),
        ]
    total = sum(s for _, s in components)
    return components, total


def win_hide_kw() -> dict:
    if platform.system() == "Windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _pip(*args: str) -> list[str]:
    return [sys.executable, "-m", "pip", *args]


def check_ml_runtime() -> tuple[bool, str]:
    """
    Returns (ready_for_upscale, reason).
    reason: ok | missing_torch | missing_diffusers | no_cuda | import_error
    NVIDIA + Linux/Windows: CUDA must be usable. macOS / AMD / Intel: torch+diffusers only (CPU).
    """
    try:
        import torch
    except ImportError:
        return False, "missing_torch"
    try:
        import diffusers  # noqa: F401
    except ImportError:
        return False, "missing_diffusers"
    try:
        if get_ml_torch_install_variant() == "cuda" and not torch.cuda.is_available():
            return False, "no_cuda"
    except Exception:
        return False, "import_error"
    return True, "ok"


def install_ml_runtime(progress: Optional[ProgressCB] = None) -> tuple[bool, Optional[str]]:
    """
    pip install torch (CUDA on NVIDIA Linux/Windows, else CPU) + diffusers stack.
    progress(phase, detail, downloaded, total) — total may be 0 when unknown.
    """

    def prog(phase: str, detail: str = "", downloaded: int = 0, total: int = 0) -> None:
        d = (detail or "").replace("\n", " ")[:260]
        _debug_log(
            UTILITY_INSTALLER_POPUP,
            f"PyTorch/diffusers UI: {phase} | {d} | bytes={downloaded}/{total}",
        )
        if progress:
            progress(phase, detail, downloaded, total)

    variant = get_ml_torch_install_variant()

    # CUDA wheels track a narrower CPython range than many CPU builds.
    if platform.system() != "Darwin" and variant == "cuda":
        py_ok, py_msg = _cuda_torch_supported_python()
        if not py_ok:
            _debug_log(UTILITY_APP, f"install_ml_runtime: blocked ({py_msg})")
            return False, py_msg

    if variant == "cuda":
        torch_cmd = _pip(
            "install",
            "-U",
            "torch",
            "torchvision",
            "--index-url",
            "https://download.pytorch.org/whl/cu124",
        )
        torch_phase = "Installing PyTorch (CUDA)…"
    else:
        torch_cmd = _pip("install", "-U", "torch", "torchvision")
        torch_phase = "Installing PyTorch (CPU)…"

    stack_cmd = _pip(
        "install",
        "-U",
        "diffusers>=0.37.0",
        "transformers",
        "accelerate",
        "safetensors",
        "huggingface_hub",
    )
    steps = [
        ("Upgrading pip…", _pip("install", "-U", "pip")),
        (torch_phase, torch_cmd),
        ("Installing diffusers stack…", stack_cmd),
    ]

    components, total_est = estimate_ml_runtime_components()
    _ = components  # kept for parity with upstream UI expectations

    pct_re = re.compile(r"(\d+)\s*%")
    total_hint = total_est if total_est > 0 else 0

    for phase_label, cmd in steps:
        prog(phase_label, " ".join(cmd[-3:]), 0, total_hint)
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **win_hide_kw(),
            )
            if p.stdout is None:
                return False, "pip stdout unavailable"

            tail: deque[str] = deque(maxlen=48)
            for line in p.stdout:
                raw = (line or "").rstrip("\n\r")
                if raw.strip():
                    tail.append(raw.strip()[:500])
                ln = raw.strip()
                if not ln:
                    continue
                prog("Installing…", ln[:140], 0, total_hint)
                m = pct_re.search(ln)
                if m:
                    pct = int(m.group(1))
                    pct = max(0, min(100, pct))
                    downloaded_b = int(total_est * (pct / 100.0)) if total_est > 0 else 0
                    prog("Downloading…", ln[:120], downloaded_b, total_hint)

            rc = p.wait(timeout=3600)
            if rc != 0:
                snippet = " · ".join(tail)[-900:] if tail else "(no pip output)"
                err = f"{phase_label} pip exit {rc}: {snippet}"
                _debug_log(UTILITY_APP, f"install_ml_runtime: {err}")
                return False, err
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except Exception:
                pass
            return False, "pip timed out"
        except Exception as e:
            return False, str(e)

    prog(
        "Complete.",
        "Restart ChronoArchiver if the app does not see new packages.",
        total_est if total_est > 0 else 1,
        total_est if total_est > 0 else 1,
    )
    return True, None


def uninstall_ml_runtime(progress: Optional[ProgressCB] = None) -> bool:
    def prog(phase: str, detail: str = "", downloaded: int = 0, total: int = 0) -> None:
        if progress:
            progress(phase, detail, downloaded, total)

    pkgs = [
        "torch",
        "torchvision",
        "torchaudio",
        "diffusers",
        "transformers",
        "accelerate",
        "safetensors",
        "huggingface_hub",
    ]
    cmd = _pip("uninstall", "-y", *pkgs)
    prog("Removing packages…", " ".join(pkgs[:4]) + " …", 0, 0)
    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **win_hide_kw(),
        )
        if p.stdout:
            for line in p.stdout:
                ln = (line or "").strip()
                if ln:
                    prog("Uninstalling…", ln[:140], 0, 0)
        rc = p.wait(timeout=600)
        prog("Done.", "", 1, 1)
        return rc == 0
    except Exception:
        return False
