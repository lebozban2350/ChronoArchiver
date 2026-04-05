"""
bootstrap.py — First-run venv setup (stdlib + optional tkinter).
Run before main app when venv does not exist.
"""
import argparse
import os
import platform
import sys
from pathlib import Path

# Must run before app imports
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from core.venv_manager import (
    add_venv_to_path,
    ensure_venv,
    get_python_exe,
    get_venv_path,
    is_venv_runnable,
    remove_venv,
)


def _run_with_ui():
    """Use tkinter for setup window."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return _run_headless()

    root = tk.Tk()
    root.title("ChronoArchiver — First-time Setup")
    root.geometry("480x200")
    root.resizable(False, False)
    root.configure(bg="#1a1a1a")

    lbl_title = tk.Label(root, text="Setting up ChronoArchiver...", font=("", 12, "bold"), fg="#e5e7eb", bg="#1a1a1a")
    lbl_title.pack(pady=(20, 8))
    lbl_phase = tk.Label(root, text="Preparing...", font=("", 9), fg="#9ca3af", bg="#1a1a1a")
    lbl_phase.pack(pady=4)
    lbl_detail = tk.Label(root, text="", font=("", 8), fg="#6b7280", bg="#1a1a1a", wraplength=440)
    lbl_detail.pack(pady=4, padx=20)
    prog = ttk.Progressbar(root, mode="determinate", length=400)
    prog.pack(pady=16)
    lbl_pct = tk.Label(root, text="0%", font=("", 8), fg="#6b7280", bg="#1a1a1a")
    lbl_pct.pack(pady=2)

    done = [False]
    result = [False]

    def progress(phase, detail="", pct=None):
        lbl_phase.config(text=phase)
        lbl_detail.config(text=detail[:100] if detail else "")
        if pct is not None:
            prog["value"] = min(100, max(0, pct))
            lbl_pct.config(text=f"{pct:.0f}%")
        root.update_idletasks()

    def task():
        result[0] = ensure_venv(progress_callback=progress)
        done[0] = True
        root.after(0, root.quit)

    import threading
    t = threading.Thread(target=task, daemon=True)
    t.start()
    root.mainloop()
    root.destroy()
    return result[0]


def _run_headless():
    """No UI — print to stdout."""
    def progress(phase, detail="", pct=None):
        print(f"  {phase}  {detail}")

    return ensure_venv(progress_callback=progress)


def _show_setup_error(msg: str) -> None:
    """Show setup failure; use GUI when possible (pythonw has no console)."""
    print(msg, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ChronoArchiver — Setup Failed", msg)
        root.destroy()
    except Exception:
        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, msg, "ChronoArchiver — Setup Failed", 0x10)
            except Exception:
                pass


def _find_app_py() -> Path:
    """Locate app.py for repo (src/ui/) or installed (app/src/ui/) layout."""
    for candidate in (
        _SCRIPT_DIR / "src" / "ui" / "app.py",
        _SCRIPT_DIR / "ui" / "app.py",
    ):
        if candidate.is_file():
            return candidate
    return _SCRIPT_DIR / "ui" / "app.py"  # fallback for error msg


def _get_gui_python_exe() -> Path:
    """Use pythonw on Windows to avoid opening a console window."""
    py = get_python_exe()
    if platform.system() == "Windows":
        pyw = py.with_name("pythonw.exe")
        if pyw.exists():
            return pyw
    return py


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--reset-venv",
        action="store_true",
        help="Delete the app-private venv and recreate it on next setup (fixes broken pip/venv).",
    )
    args, argv_rest = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + argv_rest

    venv_path = get_venv_path()
    if args.reset_venv and venv_path.exists():
        print(f"Removing app venv: {venv_path}", file=sys.stderr)
        remove_venv()

    get_venv_path()
    py = _get_gui_python_exe()
    app_py = _find_app_py()
    app_root = str(app_py.parent.parent.parent)

    if not app_py.is_file():
        print(f"ChronoArchiver: app not found (looked for {app_py})", file=sys.stderr)
        sys.exit(1)

    if py.exists() and is_venv_runnable():
        add_venv_to_path()  # LD_LIBRARY_PATH for OpenCV CUDA (libcufft, libcudnn) before execv
        os.chdir(app_root)
        try:
            os.execv(str(py), [str(py), str(app_py)] + sys.argv[1:])
        except OSError as e:
            print(f"Failed to launch: {e}")
            sys.exit(1)

    # Use UI on Windows/macOS; headless only when no display (e.g. SSH)
    use_ui = bool(os.environ.get("DISPLAY")) or platform.system() in ("Windows", "Darwin")
    if use_ui:
        print("ChronoArchiver — First-time setup (creating environment)...")
    ok = _run_with_ui() if use_ui else _run_headless()
    if not ok:
        _show_setup_error("Setup failed. Check that Python 3.11+ is installed and you have internet access.")
        sys.exit(1)
    print("Setup complete. Launching...")
    add_venv_to_path()  # LD_LIBRARY_PATH for OpenCV CUDA (libcufft, libcudnn) before execv
    os.chdir(app_root)
    try:
        os.execv(str(py), [str(py), str(app_py)] + sys.argv[1:])
    except OSError as e:
        print(f"Failed to launch: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
