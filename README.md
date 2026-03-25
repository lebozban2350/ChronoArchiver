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

## Media Organizer

Organizes media into date-based folder structures (dropdown):

- **YYYY/YYYY-MM** — Nested (year → month)
- **YYYY-MM** — Flat by month
- **YYYY-MM-DD** — Flat by day
- **YYYY/YYYY-MM/YYYY-MM-DD** — Nested by day

Date resolution order:

1. **Images**: EXIF `DateTimeOriginal`/`DateTimeDigitized` → filename → modification time
2. **Videos**: FFprobe `creation_time` → filename → modification time
3. **Filename** — `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD` (with optional separators)
4. **Modification time** — Fallback; timestamps before 1957 are rejected

Features:

- **Action**: Move, Copy, or Symlink.
- **Exclude**: .trash, @Recently Deleted, .thumbnails, etc. excluded by default.
- **Duplicates**: Rename, Skip, Keep newer, or Overwrite if same.
- Appends `YYYY-MM-DD_` to filenames for chronological ordering
- Corrects mismatched date prefixes
- Optional target directory for organizing into a separate root
- Photos and/or Videos checkboxes — processes all supported extensions for selected types
- Duplicate detection via size comparison and partial MD5 (first 1 MB)
- Dry-run mode; cancellable during execution
- Summary statistics: Moved, Skipped, Duplicates

---

## AI Media Scanner

Dual-list workflow: **Keep** (subjects detected) and **Move** (no subjects). Detection stack:

- **Face** — OpenCV YuNet (`face_detection_yunet_2023mar.onnx`), OpenCL when available
- **Persons & Animals** — YOLOv8-nano ONNX (optional, configurable confidence threshold)

Models are stored in `~/.local/share/ChronoArchiver/models` (Linux) or the platform equivalent. Use Setup Models to download; OpenCV is installed via the Install OpenCV button in the AI Scanner panel.

Features:

- Keep/Move lists with inline preview
- Manual item transfer between lists
- Move Files — relocates Move list to `Archived_Others/` within the scan directory
- Export CSV for Keep/Move path lists
- Progress with ETA; cancellable

---

## Mass AV1 Encoder

Batch AV1 transcoding with preserved folder structure and metadata.

**Encoding backends:**

- **NVIDIA NVENC** (`av1_nvenc`) when a compatible GPU is present (RTX 40-series or later for AV1)
- **AMD VAAPI** (Linux) and **AMF** (Windows) when supported
- **SVT-AV1** (`libsvtav1`) as software fallback

**Interface:**

- 4-slot job grid with per-job progress and I/O throughput (MB/s)
- Real-time CPU, GPU, and RAM monitoring
- Pause and resume for active jobs
- Master progress bar across the queue

**Options:**

- Output: `.mp4` (`stem_av1.mp4`); files ending `_av1.ext` skipped on rescan
- Auto-scan on source selection; queue resets when source changes
- Skip Short Clips, Auto-Shutdown, Delete Source (safety-locked)
- Space Saved, ETA, per-thread speed

---

## Installation

### Arch Linux (AUR)

```bash
paru -S chronoarchiver
# or
yay -S chronoarchiver
```

### Fedora Atomic / Bazzite (and similar immutable desktops)

There is no first-party RPM or Flatpak in this repository yet. To use ChronoArchiver on Bazzite or other Fedora Atomic variants:

1. **From source (recommended)** — Install Python 3.10+ (or use `toolbox` / `distrobox`), then clone and run bootstrap as in [From Source](#from-source) below. Data dirs follow XDG / `platformdirs` under your home.
2. **AUR package inside a container** — Create an Arch container (`distrobox create -i archlinux`), enter it, install `paru`/`yay`, then `paru -S chronoarchiver`. Launch the app from that environment (or symlink the generated launcher); models and config live in the container home unless you bind-mount.
3. **Visibility in Discover / Flathub** — To have the app appear in GNOME Software / Discover for everyone, publish a [Flatpak](https://docs.flathub.org/docs/for-app-authors) manifest in a separate repo and submit it to [Flathub](https://flathub.org/). Upstream can link that from the README once listed.
4. **Separate packaging repo** — If you maintain a COPR, Flatpak, or `bazzite`-specific fork, add it as a `git remote`, bump `pkgver` alongside this repo, and push there on each release (same pattern as the AUR `PKGBUILD`).

### Windows (x64) / macOS

Download the setup from the [Releases](https://github.com/UnDadFeated/ChronoArchiver/releases) page:

| Platform | File |
|----------|------|
| **Windows x64** | `ChronoArchiver-Setup-3.8.2-win64.exe` |
| **macOS** | `ChronoArchiver-Setup-3.8.2-mac64.zip` |

The setup (~6MB) downloads Python source on first run. Requires Python 3.11+ installed. Creates venv during install; desktop shortcut runs `pythonw` (no command prompt). Install location: `%LOCALAPPDATA%\ChronoArchiver` (Windows) or `~/Library/Application Support/ChronoArchiver` (macOS). Uninstall: Windows Settings → Installed apps → ChronoArchiver (or Start Menu → ChronoArchiver → `Uninstall_ChronoArchiver.cmd`), macOS: `Uninstall ChronoArchiver.app` / `Uninstall ChronoArchiver.command`.

### From Source

**Requirements:** Python 3.10 or later. FFmpeg is bundled; no system installation required.

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
python src/bootstrap.py
```

First launch creates an app-private virtual environment at `~/.local/share/ChronoArchiver/venv` and installs dependencies. Subsequent runs start directly. NVIDIA RTX 40-series (or later) with AV1 NVENC enables hardware-accelerated encoding; the application runs fully in software without it.

---

## System Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.10 or later |
| OS | Windows, Linux, macOS (Arch/AUR package available) |
| GPU | Optional — NVIDIA RTX 40-series for NVENC AV1 |

---

## Configuration Reference

### Media Organizer

| Setting | Default | Description |
|---------|---------|-------------|
| Action | Move | Move, Copy, or Symlink files |
| Duplicate policy | Rename | Rename, Skip, Keep newer, or Overwrite if same |
| Folder structure | YYYY/YYYY-MM | Nested, flat by month/day |

### Mass AV1 Encoder

| Setting | Default | Description |
|---------|---------|-------------|
| Encoding quality (CQ) | 30 | Lower = higher quality, larger file |
| Preset | p4 | p1–p7 (speed/quality trade-off; backend-dependent) |
| Re-encode audio | On | Off copies original audio stream |
| Concurrent jobs | 2 | 1, 2, or 4 parallel workers |
| Maintain structure | On | Mirrors source folder layout in target |
| Skip Short Clips | Off | User-defined threshold |
| HW Accel Decode | Off | GPU demux/decode |
| Auto-Shutdown | Off | Power off after queue completion |

---

## Uninstall

**AUR:** `pacman -R chronoarchiver` removes the application and all user data (models, config, logs).

**Windows/macOS setup:** **Windows** — Settings → Apps → **ChronoArchiver** → Uninstall (or Start Menu → ChronoArchiver → **`Uninstall_ChronoArchiver.cmd`**). Confirm in the dialog; the install folder under `%LOCALAPPDATA%\ChronoArchiver`, shortcuts, and the Installed Apps entry are removed. **macOS** — in the install folder, open **Uninstall ChronoArchiver.app** or run **Uninstall ChronoArchiver.command**.

**Source install:** Delete the following directories to remove all traces:

- `~/.local/share/ChronoArchiver` (venv, models)
- `~/.config/ChronoArchiver` (settings)
- `~/.local/state/ChronoArchiver` (logs)

On Windows, use `%LOCALAPPDATA%\ChronoArchiver` and `%APPDATA%\ChronoArchiver`. On macOS, use `~/Library/Application Support/ChronoArchiver` (via `platformdirs`).

---

## Troubleshooting

**Python required (Windows/macOS)**  
The setup installs the app as a Python program. Install Python 3.11+ from [python.org](https://python.org) if prompted.

**Debug log location**  
Session logs: `chronoarchiver_YYYY-MM-DD_HH-MM-SS.log`  
- **Windows/macOS setup install** (desktop shortcut / `.app`): under the app folder, `Logs\` (Windows) or `Logs/` (macOS), e.g. `%LOCALAPPDATA%\ChronoArchiver\Logs\`
- **Linux / source / AUR** (no install-root env): `~/.local/state/ChronoArchiver/log/`
- **macOS** when not using the setup install layout: often `~/Library/Logs/ChronoArchiver/` (via `platformdirs`)  

The in-app "Debug" button in the footer opens the log folder. If the app crashes before the GUI loads, no log file is created.

**Windows — ChronoArchiver stuck in Settings → Apps**  
If you deleted the install folder by hand, the Apps list can still show ChronoArchiver until the **uninstall registry key** is updated. Run the **current** setup installer again (it removes and recreates that key), or delete it yourself in **cmd**:

`reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ChronoArchiver" /f`

If the entry persists, sign out and back in or restart **Windows Explorer**.

**Windows — Uninstall can’t delete files**  
The uninstall script stops **pythonw.exe** / **python.exe** processes launched from your install directory. Close ChronoArchiver first if something still holds files open.

---

## Updates

The application checks GitHub tags on startup. In-app updates work on:

- **Arch Linux (AUR)**: `paru`/`yay` — app closes, updates, restarts.
- **Git clone (Linux, Windows, macOS)**: `git pull` — app closes, pulls, restarts.
- **Windows/macOS setup**: Fetches the new setup launcher; running it performs the update.

---

## Changelog

Release notes are available in [CHANGELOG.md](CHANGELOG.md). AUR installations include the changelog at `/usr/share/doc/chronoarchiver/CHANGELOG.md`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
