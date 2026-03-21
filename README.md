# ChronoArchiver: Time to Archive! 🕰️

**ChronoArchiver** is a unified, high-performance media management suite designed for long-term data preservation and optimization. It combines intelligent data archival with professional-grade video transcoding, providing a seamless workflow for modern digital libraries. *Time to Archive!*

[![Version](https://img.shields.io/badge/version-1.0.24-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux-lightgrey.svg)](#system-requirements)

ChronoArchiver is a desktop application for organizing, classifying, and re-encoding large media libraries. It combines three independent tools — a date-based file organizer, an AI-powered photo scanner, and a batch AV1 encoder — into a single fixed-window interface built with CustomTkinter.

---

## Features

### Media Organizer

Sorts photos and videos into a date-based folder hierarchy using the most reliable date source available for each file.

- Reads **EXIF DateTimeOriginal** (or DateTimeDigitized) for images
- Falls back to **filename parsing** — recognizes `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD`, and common prefixes like `IMG_`, `VID-`, `Signal-`
- Falls back to **file modification time** as a last resort, rejecting timestamps before 1980
- Adds a `YYYY-MM-DD_` prefix to each filename so files sort correctly by date inside any folder
- Corrects existing prefixes that don't match the detected date
- Organizes into **nested** (`YYYY/YYYY-MM/`) or **flat** (`YYYY-MM/`) folder structures
- **Dry run mode** previews all planned moves in the log without touching any files
- **Duplicate detection** — compares file size then a partial MD5 of the first 1 MB before skipping or renaming collisions
- Handles photos and videos independently — select either or both before running
- Cancellable mid-run with a single click

### AI Scanner

Classifies images into two buckets — photos containing people or animals, and everything else — so you can review and move the latter in bulk.

- Face detection via **OpenCV YuNet** (`face_detection_yunet_2023mar.onnx`), running on OpenCL if available
- Optional animal detection via **MediaPipe EfficientDet Lite 0** (`efficientdet_lite0.tflite`), covering cats, dogs, birds, horses, sheep, cows, bears, zebras, and giraffes
- Both models ship with the application; SHA-256 integrity is verified on every launch and re-downloaded automatically if corrupt
- Results appear in two scrollable lists — **Keep** (subjects detected) and **Move** (no subjects) — with an inline image preview on click
- Items can be manually moved between lists before committing
- "Move Files" sends the right-hand list to an `Archived_Others/` subfolder inside the scanned directory
- Progress bar shows current file, count, and estimated time remaining
- Cancellable at any point

### Mass AI Encoder

Batch-encodes video files to AV1, preserving folder structure and file metadata.

- Encodes using **NVIDIA NVENC** (`av1_nvenc`) if a compatible GPU is detected, otherwise falls back to **SVT-AV1** (`libsvtav1`) in software
- **High-Density Monitoring**: Features a 4-slot high-density thread grid with real-time per-job progress.
- **System Metrics Dashboard**: Integrated real-time monitoring of **CPU, GPU (NVENC), and RAM** utilization.
- **Pause/Resume Control**: Suspend active encoding jobs at any time to free up system resources without losing progress.
- **Advanced Automation**: Features **Skip Short Clips** (via user-defined threshold), **Auto-Shutdown**, and **Safety-locked File Deletion**.
- **Accurate Telemetry**: Real-time **Space Saved** calculation, **ETA** estimation, and per-thread speed labels (e.g. `2.3x`).
- Master progress bar tracks completion across the entire batch.

---

## Installation

### Arch Linux (AUR)

```bash
yay -S chronoarchiver
```

### From Source

**Requirements:** Python 3.10 or later, FFmpeg (must be on `PATH`)

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
pip install -r requirements.txt
python src/ui/app.py
```

**Optional:** An NVIDIA GPU with NVENC AV1 support (Ada Lovelace / RTX 40-series or later) enables hardware-accelerated encoding in the Transcoding Dashboard. The application works fully without it.

---

## System Requirements

| Component | Requirement |
|---|---|
| Python | 3.10 or later |
| FFmpeg | Any recent version on `PATH` |
| OS | Windows, Linux (Arch/AUR package available) |
| GPU | Optional — NVIDIA RTX 40-series for NVENC AV1 |

---

## Settings

All settings are persisted automatically to the platform-appropriate config directory (via `platformdirs`). There is no manual configuration file to edit.

| Setting | Default | Notes |
|---|---|---|
| Encoding quality (CQ) | 30 | Lower = better quality, larger file |
| Encoding preset | p4 | p1 to p7 representing varying speed/quality trade-offs (behavior varies by backend) |
| Re-encode audio | On | Off copies the original audio stream |
| Concurrent jobs | 2 | 1, 2, or 4 parallel encode workers |
| Maintain structure | On | Mirrors source folder layout in target |
| Skip Short Clips | Off | Threshold for ignoring small media files |
| HW Accel Decode | Off | Use GPU for demux / decode stage |
| Auto-Shutdown | Off | Power off system after queue finishes |

---

## Updating

The application checks for updates against GitHub Releases on startup (or manually via the **CHECK FOR UPDATES** action in the global status footer). On Arch Linux it also checks the AUR. Version comparison is semantic — `1.10.0` is correctly identified as newer than `1.9.0`.

---

## Support

ChronoArchiver is free and open-source. If it saves you time, the **Donate** tab inside the application has PayPal and Venmo links.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
