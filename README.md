# ChronoArchiver 🕰️

**ChronoArchiver** is a unified, high-performance media management suite. It combines powerful AI-driven file organization with a professional-grade AV1 encoding pipeline, all wrapped in a sleek, modern interface.

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AUR](https://img.shields.io/aur/version/chronoarchiver.svg)](https://aur.archlinux.org/packages/chronoarchiver)

---

## 🚀 Key Features

### 📁 Media Organizer
Effortlessly organize thousands of photos and videos.
- **Smart Sorting**: Automatically categorizes files by Date (Year/Month).
- **Metadata Aware**: Reads EXIF and file creation data for precise organization.
- **Dry Run Mode**: Preview all changes before committing them to disk.
- **Flat Layouts**: Option to use a clean `YYYY-MM` folder structure.

### 🤖 AI Scanner
Advanced media classification powered by MediaPipe and OpenCV.
- **Face Detection**: Automatically identify files containing people.
- **Animal Detection**: Special handling for your pet photos and wildlife.
- **Smart Filtering**: Quickly separate "Keep" (People/Animals) from "Move" (Landscapes/Other).
- **On-Demand Models**: Lightweight initial install; fetch AI models only when needed.

### 🎬 AV1 Encoder
Built-in high-efficiency video encoding dashboard.
- **Format Support**: Encode large media libraries into space-saving AV1 format.
- **HDR Passthrough**: Full support for HDR10 and HLG metadata.
- **Hardware Acceleration**: Leverage NVIDIA NVENC (AV1) or high-performance SVT-AV1.
- **Batch Processing**: Encode entire directories with customizable quality and presets.

---

## 🛠️ Installation

### Arch Linux (AUR)
Install directly from the AUR using your favorite helper:
```bash
yay -S chronoarchiver
```

### Manual Installation (Standard Linux)
1. **Clone the repository**:
   ```bash
   git clone https://github.com/UnDadFeated/ChronoArchiver.git
   cd ChronoArchiver
   ```
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the application**:
   ```bash
   python src/ui/app.py
   ```

---

## 📋 Requirements
- **Python 3.10+**
- **FFmpeg** (For encoding and metadata processing)
- **NVIDIA GPU** (Optional, for NVENC AV1 acceleration)

---

## ☕ Support
If ChronoArchiver saves you time, consider supporting the developer through the **Donate** tab inside the app!

## 📜 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
*Created by [UnDadFeated](https://github.com/UnDadFeated)*
