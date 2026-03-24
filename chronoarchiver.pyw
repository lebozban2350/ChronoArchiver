#!/usr/bin/env python3
"""
ChronoArchiver launcher — runs via pythonw (Windows) or python3 (macOS).
Sets install root so venv lives in app dir for clean uninstall.
"""
import os
import sys
from pathlib import Path

_LAUNCHER_DIR = Path(__file__).resolve().parent
os.environ["CHRONOARCHIVER_INSTALL_ROOT"] = str(_LAUNCHER_DIR)
os.chdir(str(_LAUNCHER_DIR))
sys.path.insert(0, str(_LAUNCHER_DIR))

# Run bootstrap (creates venv on first run, then launches app)
import importlib.util
bootstrap_path = _LAUNCHER_DIR / "src" / "bootstrap.py"
if not bootstrap_path.exists():
    bootstrap_path = _LAUNCHER_DIR / "bootstrap.py"
spec = importlib.util.spec_from_file_location("bootstrap", bootstrap_path)
if spec and spec.loader:
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap"] = mod
    spec.loader.exec_module(mod)
else:
    print("ChronoArchiver: bootstrap.py not found.", file=sys.stderr)
    sys.exit(1)
