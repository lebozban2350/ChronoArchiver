"""
app_paths.py — Install root vs platform user directories (shared by main app and panels).

CHRONOARCHIVER_INSTALL_ROOT (chronoarchiver.pyw / setup): venv, Logs, Settings, runtime lock,
and bundled models live under that tree. Otherwise use platformdirs(APP_NAME, APP_AUTHOR).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    import platformdirs
except ImportError:
    platformdirs = None

APP_NAME = "ChronoArchiver"
APP_AUTHOR = "UnDadFeated"
ENV_INSTALL_ROOT = "CHRONOARCHIVER_INSTALL_ROOT"


def install_root() -> Path | None:
    r = os.environ.get(ENV_INSTALL_ROOT, "").strip()
    return Path(r) if r else None


def uses_install_layout() -> bool:
    return install_root() is not None


def data_dir() -> Path:
    """Parent of venv/."""
    ir = install_root()
    if ir is not None:
        return ir
    if platformdirs:
        return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return Path.home() / ".local" / "share" / APP_NAME


def settings_dir() -> Path:
    """Shared Settings/ (ffmpeg_revision, ONNX models when install, encoder config when install)."""
    ir = install_root()
    p = (ir / "Settings") if ir is not None else (data_dir() / "Settings")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def logs_dir() -> Path:
    """Session debug logs."""
    ir = install_root()
    if ir is not None:
        p = ir / "Logs"
    elif platformdirs:
        p = Path(platformdirs.user_log_dir(APP_NAME, APP_AUTHOR))
    else:
        p = Path.home() / ".local" / "state" / APP_NAME / "log"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def runtime_dir() -> Path:
    """Single-instance lock directory."""
    ir = install_root()
    if ir is not None:
        p = ir / "Settings" / "runtime"
    elif platformdirs:
        p = Path(platformdirs.user_runtime_dir(APP_NAME, APP_AUTHOR))
    else:
        p = Path.home() / ".local" / "state" / APP_NAME
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def user_models_dir() -> Path:
    """Platform user_data …/models (dev / AUR; legacy source when migrating to install Settings/models)."""
    if platformdirs:
        return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)) / "models"
    return data_dir() / "models"


def _migrate_models_from_user_data_if_needed(dest: Path) -> None:
    if not platformdirs:
        return
    legacy = user_models_dir()
    try:
        if legacy.resolve() == dest.resolve() or not legacy.is_dir():
            return
    except OSError:
        return

    def _has_onnx(d: Path) -> bool:
        try:
            return any(d.glob("*.onnx"))
        except OSError:
            return False

    if _has_onnx(dest) or not _has_onnx(legacy):
        return
    try:
        for f in legacy.glob("*.onnx"):
            tgt = dest / f.name
            if not tgt.is_file():
                shutil.copy2(f, tgt)
    except OSError:
        pass


def models_dir() -> Path:
    """AI Scanner ONNX models."""
    ir = install_root()
    if ir is not None:
        p = ir / "Settings" / "models"
    else:
        p = user_models_dir()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if ir is not None:
        _migrate_models_from_user_data_if_needed(p)
    return p


def encoder_config_dir() -> Path:
    """Directory containing av1_config.json (install Settings/ else single-segment user config)."""
    ir = install_root()
    if ir is not None:
        return ir / "Settings"
    if platformdirs:
        return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))
    return Path.home() / ".config" / APP_NAME


def legacy_av1_config_file() -> Path:
    """Pre-unification Windows path (nested …\\ChronoArchiver\\ChronoArchiver\\av1_config.json)."""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            return Path(local) / APP_NAME / APP_NAME / "av1_config.json"
    return encoder_config_dir() / "av1_config.json"
