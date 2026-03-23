# ChronoArchiver

<div>
<img src="src/ui/assets/icon.png" width="112" height="140" align="right" />
<strong>Time to Archive!</strong> — A unified media management platform for archival, classification, and transcoding.

ChronoArchiver consolidates date-based file organization, AI-driven image analysis, and batch AV1 encoding into a single desktop application. Built on PySide6 with an app-private Python environment; no system-wide package installation required.
</div>

[![Version](https://img.shields.io/badge/version-3.2.24-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
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

Organizes media into `YYYY/YYYY-MM/` (nested) or `YYYY-MM/` (flat) structures. Date resolution order:

1. **EXIF** — `DateTimeOriginal` or `DateTimeDigitized`
2. **Video metadata** — FFprobe `creation_time` when available
3. **Filename** — `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD`, and common prefixes (`IMG_`, `VID-`, `Signal-`)
4. **Modification time** — Fallback; timestamps before 1980 are rejected

Features:

- Appends `YYYY-MM-DD_` to filenames for chronological ordering
- Corrects mismatched date prefixes
- Optional target directory for organizing into a separate root
- Comma-separated extension override; blank uses default photo/video sets
- Duplicate detection via size comparison and partial MD5 (first 1 MB)
- Dry-run mode; cancellable during execution
- Summary statistics: Moved, Skipped, Duplicates

---

## AI Media Scanner

Dual-list workflow: **Keep** (subjects detected) and **Move** (no subjects). Detection stack:

- **Face** — OpenCV YuNet (`face_detection_yunet_2023mar.onnx`), OpenCL when available
- **Animals** — OpenCV DNN SSD MobileNet V1 (optional, configurable confidence threshold)

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

- **NVIDIA NVENC** (`av1_nvenc`) when a compatible GPU is present
- **SVT-AV1** (`libsvtav1`) as software fallback

**Interface:**

- 4-slot job grid with per-job progress
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

**Source install:** Delete the following directories to remove all traces:

- `~/.local/share/ChronoArchiver` (venv, models)
- `~/.config/ChronoArchiver` (settings)
- `~/.local/state/ChronoArchiver` (logs)

---

## Updates

The application checks GitHub tags on startup. Updates can be applied in-app: the process closes, performs the update (git pull for source installs, or `paru`/`yay` for AUR), and restarts. Version comparison follows semantic versioning.

---

## Changelog

Release notes are available in [CHANGELOG.md](CHANGELOG.md). AUR installations include the changelog at `/usr/share/doc/chronoarchiver/CHANGELOG.md`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
