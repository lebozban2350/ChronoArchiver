# ChronoArchiver

<img src="src/ui/assets/icon.png" width="96" align="right" alt="" />

Desktop app for organizing media by date, batch-encoding video to AV1, and optional local AI tools (scanner, upscalers). Cross-platform (Windows, Linux, macOS). Uses PySide6 and a private app environment—no need to install Python packages system-wide.

[![Version](https://img.shields.io/badge/version-5.7.7-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](https://github.com/UnDadFeated/ChronoArchiver#overview)

## Get started

**Installers (Windows & macOS):** [GitHub Releases](https://github.com/UnDadFeated/ChronoArchiver/releases) (current **5.7.6**).

**From source** (Python 3.10+):

```bash
git clone https://github.com/UnDadFeated/ChronoArchiver.git
cd ChronoArchiver
python src/bootstrap.py
```

If the bundled environment breaks: `python src/bootstrap.py --reset-venv`.

**Arch Linux:** [`chronoarchiver`](https://aur.archlinux.org/packages/chronoarchiver) — e.g. `paru -S chronoarchiver` or `yay -S chronoarchiver`.

## Overview

| Area | Role |
|------|------|
| Media Organizer | Sort files into date folders (EXIF, metadata, filename, or modified time). |
| Mass AV1 Encoder | Batch transcode; software or hardware encoders when available. |
| AI Media Scanner | Local OpenCV / ONNX classification (no cloud upload for analysis). |
| AI Image / Video Upscaler | Optional AI upscaling workflows. |

GPU support is optional; CPU paths are available. After launch, wait until the footer shows **READY**, then open a panel and set paths or models as prompted.

**If something fails:** wait for **READY**, use each panel’s install/setup actions for engines and models, or open **HEALTH** / the **DEBUG** log path from the footer. Offline-only work continues when the network is unavailable; downloads may show **NO NETWORK**.

For JSON logs: set `CHRONOARCHIVER_JSON_LOG=1` before starting the app.

## Privacy

Scanner and inference run on your machine unless you choose to move data elsewhere. See [SECURITY.md](SECURITY.md) for policy and reporting.

## Repository

| Resource | Link |
|----------|------|
| Changelog | [CHANGELOG.md](CHANGELOG.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| License | [LICENSE](LICENSE) |

Maintainer: [UnDadFeated](https://github.com/UnDadFeated).
