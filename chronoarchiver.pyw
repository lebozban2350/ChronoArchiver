#!/usr/bin/env python3
"""
ChronoArchiver launcher — runs via pythonw (Windows) or python3 (macOS).
Sets install root so venv lives in app dir for clean uninstall.
"""
import os
import sys
import traceback
from pathlib import Path

# Same key as src/core/app_paths.ENV_INSTALL_ROOT (launcher cannot import src before chdir).
_ENV_INSTALL_ROOT = "CHRONOARCHIVER_INSTALL_ROOT"


def _show_error(title: str, msg: str) -> None:
    """Show error to user when running under pythonw (no console)."""
    print(f"{title}: {msg}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes
            full = f"{msg}\n\nRun from command prompt with: python chronoarchiver.pyw\n to see full traceback."
            ctypes.windll.user32.MessageBoxW(0, full, f"ChronoArchiver — {title}", 0x10)
        except Exception:
            pass

try:
    _LAUNCHER_DIR = Path(__file__).resolve().parent
    os.environ[_ENV_INSTALL_ROOT] = str(_LAUNCHER_DIR)
    os.chdir(str(_LAUNCHER_DIR))
    sys.path.insert(0, str(_LAUNCHER_DIR))

    import importlib.util
    bootstrap_path = _LAUNCHER_DIR / "src" / "bootstrap.py"
    if not bootstrap_path.exists():
        bootstrap_path = _LAUNCHER_DIR / "bootstrap.py"
    if not bootstrap_path.is_file():
        _show_error("Launch Error", f"bootstrap.py not found. Looked in:\n{_LAUNCHER_DIR / 'src'}\n{_LAUNCHER_DIR}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("bootstrap", bootstrap_path)
    if not spec or not spec.loader:
        _show_error("Launch Error", "Could not load bootstrap module.")
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap"] = mod
    spec.loader.exec_module(mod)
    mod.main()  # never returns on success (execv); exits on failure
except Exception as e:
    _show_error("Launch Error", str(e))
    sys.exit(1)
