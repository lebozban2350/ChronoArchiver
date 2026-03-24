# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ChronoArchiver (Windows x64 and macOS)
# Run from project root: pyinstaller tools/chronoarchiver.spec

import sys
import os

block_cipher = None

# Project layout: repo_root/src/{bootstrap.py, core/, ui/, version.py}
# Run from repo root: pyinstaller tools/chronoarchiver.spec
# SPEC is the spec file path when PyInstaller runs
try:
    _spec_dir = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _spec_dir = os.path.join(os.getcwd(), 'tools')
repo_root = os.path.normpath(os.path.join(_spec_dir, '..'))
src_dir = os.path.join(repo_root, 'src')
datas = [
    (os.path.join(src_dir, 'ui', 'assets', 'icon.png'), 'src/ui/assets'),
    (os.path.join(src_dir, 'ui', 'assets', 'icon.ico'), 'src/ui/assets'),
]
# Add each package dir so 'from core.xxx' and 'from ui.xxx' work
for pkg in ('core', 'ui', 'ui/panels'):
    pkg_path = os.path.join(src_dir, pkg)
    if os.path.isdir(pkg_path):
        datas.append((pkg_path, os.path.join('src', pkg)))
datas.append((os.path.join(src_dir, 'bootstrap.py'), 'src'))
datas.append((os.path.join(src_dir, 'version.py'), 'src'))

a = Analysis(
    [os.path.join(src_dir, 'bootstrap.py')],
    pathex=[src_dir, repo_root],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PIL', 'PIL.Image', 'psutil', 'requests', 'platformdirs', 'piexif',
        'static_ffmpeg', 'static_ffmpeg.run', 'filelock',
        'cv2', 'git',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

is_mac = sys.platform == 'darwin'
is_win = sys.platform == 'win32'

if is_mac:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='ChronoArchiver',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='ChronoArchiver',
    )
    app = BUNDLE(
        coll,
        name='ChronoArchiver.app',
        icon=os.path.join(src_dir, 'ui', 'assets', 'icon.icns') if os.path.exists(os.path.join(src_dir, 'ui', 'assets', 'icon.icns')) else None,
        bundle_identifier='com.undadfeated.chronoarchiver',
        info_plist={
            'CFBundleName': 'ChronoArchiver',
            'CFBundleDisplayName': 'ChronoArchiver',
            'CFBundleVersion': '3.5.2',
            'CFBundleShortVersionString': '3.5.2',
            'NSHighResolutionCapable': True,
        },
    )
elif is_win:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='ChronoArchiver',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=os.path.join(src_dir, 'ui', 'assets', 'icon.ico'),
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='ChronoArchiver',
    )
else:
    raise SystemExit('Build only supported on Windows or macOS')
