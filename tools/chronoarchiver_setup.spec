# -*- mode: python ; coding: utf-8 -*-
# Minimal setup launcher (~6MB) - downloads full app on first run.
# Only stdlib: tkinter, urllib, zipfile, json. No PySide6, OpenCV, etc.
# Run from repo root: pyinstaller tools/chronoarchiver_setup.spec

import sys
import os

block_cipher = None
try:
    _spec_dir = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _spec_dir = os.path.join(os.getcwd(), "tools")
repo_root = os.path.normpath(os.path.join(_spec_dir, ".."))
src_dir = os.path.join(repo_root, "src")

# Embed version at build time
_version = os.environ.get("CHRONOARCHIVER_VERSION", "3.6.0")
_version_txt = os.path.join(_spec_dir, "_setup_version.txt")
with open(_version_txt, "w") as f:
    f.write(_version)
# Bundle as version.txt so setup_launcher finds it
_datas_version = [(_version_txt, ".")]

a = Analysis(
    [os.path.join(_spec_dir, "setup_launcher.py")],
    pathex=[_spec_dir],
    binaries=[],
    datas=_datas_version,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6", "cv2", "PIL", "psutil", "requests", "platformdirs", "piexif",
        "static_ffmpeg", "numpy", "matplotlib", "scipy", "pandas", "git",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

is_win = sys.platform == "win32"
is_mac = sys.platform == "darwin"
icon_path = os.path.join(src_dir, "ui", "assets", "icon.ico") if is_win else None
if is_mac:
    icon_path = os.path.join(src_dir, "ui", "assets", "icon.icns") if os.path.exists(os.path.join(src_dir, "ui", "assets", "icon.icns")) else None

if is_win:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="ChronoArchiver-Setup",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path,
    )
elif is_mac:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ChronoArchiver-Setup",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon=icon_path,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="ChronoArchiver-Setup",
    )
    app = BUNDLE(
        coll,
        name="ChronoArchiver-Setup.app",
        icon=icon_path,
        bundle_identifier="com.undadfeated.chronoarchiver-setup",
        info_plist={
            "CFBundleName": "ChronoArchiver Setup",
            "CFBundleDisplayName": "ChronoArchiver Setup",
            "CFBundleVersion": _version,
            "CFBundleShortVersionString": _version,
        },
    )
else:
    raise SystemExit("Setup launcher only supports Windows and macOS")
