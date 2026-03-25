# ChronoArchiver

<div>
<img src="src/ui/assets/icon.png" width="112" height="184" align="right" />
<strong>Time to Archive!</strong> — A unified media management platform for archival, classification, and transcoding.

ChronoArchiver consolidates date-based file organization, AI-driven image analysis, and batch AV1 encoding into a single desktop application. Built on PySide6 with an app-private Python environment; no system-wide package installation required.
</div>

[![Version](https://img.shields.io/badge/version-3.8.2-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#system-requirements)

---

## Overview

ChronoArchiver provides three core workflows for managing large media libraries:

| Module | Purpose |
|--------|---------|
| **Media Organizer** | Sorts photos and videos into date-based folder hierarchies using EXIF, filename, or metadata. |
| **AI Media Scanner** | Classifies images by subject presence (faces, animals) for bulk triage and archival. |
| **Mass AV1 Encoder** | Batch-transcodes video to AV1 with optional hardware acceleration. |

Configuration is stored in the platform user-data directory. Each panel validates prerequisites before enabling execution; Start remains disabled until all required inputs (paths, models, etc.) are satisfied.

---

## Installation

Release **3.8.2** — installers, AUR `pkgver`, and Flatpak metadata are aligned on this version.

### GitHub (Windows / macOS installers)

Download from [**Releases**](https://github.com/UnDadFeated/ChronoArchiver/releases) (**tag `v3.8.2`**):

| Platform | Asset |
|----------|--------|
| Windows x64 | `ChronoArchiver-Setup-3.8.2-win64.exe` |
| macOS | `ChronoArchiver-Setup-3.8.2-mac64.zip` |

The setup is small; first run may download Python-related components. **Python 3.11+** must be installed for this install path. Data: `%LOCALAPPDATA%\ChronoArchiver` (Windows) or `~/Library/Application Support/ChronoArchiver` (macOS).

### Git clone (Linux, Windows, macOS)

**Needs Python 3.10+.** FFmpeg is bundled.

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
python src/bootstrap.py
```

First launch creates an app-private venv (e.g. `~/.local/share/ChronoArchiver/venv` on Linux). Updates: `git pull` and restart when prompted.

### Arch Linux (AUR)

Package **[chronoarchiver](https://aur.archlinux.org/packages/chronoarchiver)** at **3.8.2**:

```bash
paru -S chronoarchiver
# or
yay -S chronoarchiver
```

### Flatpak (Flathub)

App ID **`io.github.UnDadFeated.ChronoArchiver`**. Manifests live in [`flatpak/`](flatpak/) in this repo.

When the app is published on [Flathub](https://flathub.org/):

```bash
flatpak install flathub io.github.UnDadFeated.ChronoArchiver
```

Until then, build locally with [`flatpak/README.md`](flatpak/README.md). Updates: `flatpak update` (or your software center).

**Fedora Atomic / Bazzite:** use Flatpak from Flathub when available; otherwise run [from git](#git-clone-linux-windows-macos) or an Arch toolbox with the AUR package.

---

## Technical overview & features

<a id="system-requirements"></a>

| | |
|--|--|
| **UI / runtime** | PySide6 (Qt), Python **3.10+**, bundled **FFmpeg** |
| **Media Organizer** | Date-based folders (nested or flat); EXIF, video metadata, filename, mtime; move / copy / symlink; duplicates and dry-run |
| **AI Media Scanner** | OpenCV YuNet + optional YOLO ONNX; keep/move lists; models under user data (`Setup Models` / `Install OpenCV` in-app) |
| **Mass AV1 Encoder** | Queue with folder structure preserved; **SVT-AV1**, **NVENC** (e.g. RTX 40+), **VAAPI** / **AMF** where available; pause/resume |
| **Requirements** | **GPU optional** — hardware AV1/NVENC when supported; full software path otherwise |

Full release notes: [CHANGELOG.md](CHANGELOG.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). On Arch, the changelog is also installed at `/usr/share/doc/chronoarchiver/CHANGELOG.md`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
