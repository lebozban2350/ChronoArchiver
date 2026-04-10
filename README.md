# ChronoArchiver

<div>
<img src="src/ui/assets/icon.png" width="112" height="184" align="right" />
<strong>Time to Archive!</strong> — A unified media management platform for archival, classification, and transcoding.

ChronoArchiver consolidates date-based file organization, AI-driven image analysis, and batch AV1 encoding into a single desktop application. Built on PySide6 with an app-private Python environment; no system-wide package installation required.
</div>

[![Version](https://img.shields.io/badge/version-5.5.0-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#system-requirements)

---

## What This App Does

ChronoArchiver helps you clean up and process large photo/video collections in one place:

- Organize files into date folders automatically.
- Convert videos to AV1 in batches.
- Scan images with local AI tools (no cloud upload required for scanner analysis).
- Upscale images and videos with optional AI models.

---

## Quick Start

Release **5.5.0**.

### Option 1: Download installer (Windows/macOS)

Get the latest release from [Releases](https://github.com/UnDadFeated/ChronoArchiver/releases).

### Option 2: Run from source (Linux/Windows/macOS)

Requires Python 3.10+.

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
python src/bootstrap.py
```

If your app environment breaks, rebuild it with:

```bash
python src/bootstrap.py --reset-venv
```

### Option 3: Arch Linux (AUR)

Install package [`chronoarchiver`](https://aur.archlinux.org/packages/chronoarchiver):

```bash
paru -S chronoarchiver
# or
yay -S chronoarchiver
```

---

## First Run Checklist

1. Launch the app and wait for footer status to show **READY**.
2. Open the panel you want (Organizer, Encoder, Scanner, or Upscaler).
3. Select required paths/models.
4. Start the task.

The app keeps its own local data and environment in your user data directory.

---

## Main Features

<a id="system-requirements"></a>

- **Media Organizer**: Sort by date using EXIF, metadata, filename, or modified time.
- **Mass AV1 Encoder**: Batch encode with software or available hardware acceleration.
- **AI Media Scanner**: Detect and classify content with local OpenCV/ONNX models.
- **AI Image Upscaler**: Improve image quality with optional AI workflows.
- **AI Video Upscaler**: Upscale frames with Real-ESRGAN-based processing and re-export.

GPU acceleration is optional; CPU paths remain available.

---

## Troubleshooting

- **App not ready**: wait for **READY** in the footer, then retry.
- **Model/runtime issues**: use in-app setup/install buttons in each AI panel.
- **Need diagnostics**: use **COPY DEBUG INFO** or **EXPORT DIAGNOSTICS** in the footer.
- **Offline mode**: tasks that need downloads show **NO NETWORK**; local-only tasks still work.

For machine-readable local logs, set `CHRONOARCHIVER_JSON_LOG=1` before launch.

---

## Security and Privacy

- Scanner analysis runs locally on your machine.
- Diagnostics are local files unless you manually share them.
- See [SECURITY.md](SECURITY.md) for policy and reporting.

---

## Project Docs

- Release notes: [CHANGELOG.md](CHANGELOG.md)
- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- License: [LICENSE](LICENSE)

---

*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
