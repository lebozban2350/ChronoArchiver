# ChronoArchiver

<div>
<img src="src/ui/assets/icon.png" width="112" height="184" align="right" />
<strong>Time to Archive!</strong> — A unified media management platform for archival, classification, and transcoding.

ChronoArchiver consolidates date-based file organization, AI-driven image analysis, and batch AV1 encoding into a single desktop application. Built on PySide6 with an app-private Python environment; no system-wide package installation required.
</div>

[![Version](https://img.shields.io/badge/version-5.1.2-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#system-requirements)

---

## Overview

ChronoArchiver provides five core pillars for managing large media libraries:

| Module | Purpose |
|--------|---------|
| **Media Organizer** | Sorts photos and videos into date-based folder hierarchies using EXIF, filename, or metadata. |
| **Mass AV1 Encoder** | Batch transcodes video to AV1 with optional hardware acceleration. |
| **AI Media Scanner** | Classifies images by subject presence (faces, animals) for bulk triage and archival. |
| **AI Image Upscaler** | Z-Image-Turbo–style refinement (optional PyTorch/diffusers + HF models). |
| **AI Video Upscaler** | Real-ESRGAN (x2/x4+) frame upscaling with color tuning; source-frame preview; AV1 export via FFmpeg (optional PyTorch + weight download). |

Configuration is stored in the platform user-data directory. Each panel validates prerequisites before enabling execution; Start remains disabled until all required inputs (paths, models, etc.) are satisfied.

---

## Installation

Release **5.1.2** — installers and AUR `pkgver` are aligned on this version.

### GitHub (Windows / macOS installers)

Download from [**Releases**](https://github.com/UnDadFeated/ChronoArchiver/releases) (**tag `v5.1.2`**):

| Platform | Asset |
|----------|--------|
| Windows x64 | `ChronoArchiver-Setup-5.1.2-win64.exe` |
| macOS | `ChronoArchiver-Setup-5.1.2-mac64.zip` |

The installer is lightweight; the first launch may download Python-related components. **Python 3.11+** must be installed for this install path. Data: `%LOCALAPPDATA%\ChronoArchiver` (Windows) or `~/Library/Application Support/ChronoArchiver` (macOS).

### Git clone (Linux, Windows, macOS)

**Python 3.10+ is required.** FFmpeg is bundled.

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
python src/bootstrap.py
```

Use `python src/bootstrap.py --reset-venv` to delete and recreate a broken app-private venv.

First launch creates an app-private venv (e.g. `~/.local/share/ChronoArchiver/venv` on Linux). Updates: run `git pull` and restart when prompted.

### Arch Linux (AUR)

Package **[chronoarchiver](https://aur.archlinux.org/packages/chronoarchiver)** at **5.1.2**:

```bash
paru -S chronoarchiver
# or
yay -S chronoarchiver
```

### Fedora Atomic (and similar immutable desktops)

Run [from git](#git-clone-linux-windows-macos) in toolbox/distrobox, or use an Arch container with the [AUR package](#arch-linux-aur).

---

## Technical overview & features

<a id="system-requirements"></a>

| | |
|--|--|
| **UI / runtime** | PySide6 (Qt), Python **3.10+**, bundled **FFmpeg** |
| **Media Organizer** | Date-based folders (nested or flat); EXIF, video metadata, filename, mtime; move / copy / symlink; duplicates and dry-run |
| **AI Media Scanner** | OpenCV YuNet + optional YOLO ONNX; keep/move lists; models under user data (`Setup Models` / `Install OpenCV` in-app) |
| **Mass AV1 Encoder** | Queue with folder structure preserved; **SVT-AV1**, **NVENC** (e.g. RTX 40+), **VAAPI** / **AMF** where available; pause/resume |
| **AI Image Upscaler** | LANCZOS + Z-Image-Turbo img2img; real-time source edits; prompt-aware mode (**blank = cleanup/upscale only**); optional Beautify mode (local face analysis + optional BLIP captioning); optional LaMa inpainting for cleanup; in-app PyTorch/model setup with progress/speed telemetry |
| **AI Video Upscaler** | Official **Real-ESRGAN** RRDB weights (2× / 4× nets, 3× via resize); HSV saturation + brightness/contrast + optional unsharp; source-frame preview with adjustable color controls; AV1 export via FFmpeg (MP4/MKV) with optional audio copy |
| **Requirements** | **GPU optional** — hardware AV1/NVENC when supported; full software path otherwise |

**Privacy note (AI Media Scanner):** analysis runs locally on your machine. Selected images are processed on-device using OpenCV/ONNX and are not uploaded to any server.

Full release notes: [CHANGELOG.md](CHANGELOG.md).

**Updates:** AUR (`paru`/`yay`), git clone (`git pull`), or Windows/macOS setup installer — see [CHANGELOG.md](CHANGELOG.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). On Arch, the changelog is also installed at `/usr/share/doc/chronoarchiver/CHANGELOG.md`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
