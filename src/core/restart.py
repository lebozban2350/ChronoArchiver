"""Relaunch ChronoArchiver after installing packages (e.g. AI Image Upscaler PyTorch stack)."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_app_py() -> Path | None:
    core = Path(__file__).resolve().parent
    cand = core.parent / "ui" / "app.py"
    return cand if cand.is_file() else None


def restart_application() -> bool:
    """
    Spawn a detached script that waits for this process to exit, then relaunches with the same Python.
    Call QApplication.quit() after this returns True.
    """

    app_py = _find_app_py()
    if app_py is None:
        return False
    src_dir = str(app_py.parent.parent.resolve())
    if any(c in src_dir for c in '"\n\r'):
        src_dir = os.getcwd()
    cmd = [sys.executable, str(app_py)]

    if platform.system() == "Windows":
        script = f"""@echo off
ping -n 3 127.0.0.1 > nul
cd /d "{src_dir}"
start "" {" ".join('"%s"' % c for c in cmd)}
"""
        fd, path = tempfile.mkstemp(suffix=".bat")
        try:
            os.write(fd, script.encode("utf-8"))
        finally:
            os.close(fd)
        _det = getattr(subprocess, "DETACHED_PROCESS", 0)
        _grp = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            ["cmd", "/c", path],
            creationflags=_grp | _det,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(path),
        )
        return True

    cmd_str = " ".join(repr(c) for c in cmd)
    script = f"""#!/bin/sh
sleep 2
cd "{src_dir}" && exec {cmd_str}
"""
    fd, path = tempfile.mkstemp(suffix=".sh")
    try:
        os.write(fd, script.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o755)
    subprocess.Popen(
        [path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True

