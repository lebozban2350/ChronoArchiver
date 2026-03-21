# ChronoArchiver 🕰️

**ChronoArchiver** is a unified, high-performance media management suite designed for long-term data preservation and optimization. It combines intelligent data archival with professional-grade video transcoding, providing a seamless workflow for modern digital libraries.

[![Version](https://img.shields.io/badge/version-1.0.4-blue.svg)](https://github.com/UnDadFeated/ChronoArchiver/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AUR](https://img.shields.io/aur/version/chronoarchiver.svg)](https://aur.archlinux.org/packages/chronoarchiver)

---

## 🚀 Key Features

### 📁 Archival Core
Advanced data management for large-scale media collections.
- **Smart Sorting**: Categorizes assets by chronological metadata (Year/Month).
- **Metadata Analytics**: Processes EXIF and file-system headers for accurate historical mapping.
- **Dry Run Mode**: Validates organizational shifts before execution.
- **Flat Topographies**: Support for streamlined `YYYY-MM` archival structures.

### 🤖 AI Scanner
Professional media classification leveraging industry-standard models.
- **Feature Extraction**: Identify human and biological presence within media streams.
- **Automated Filtering**: Distinction between primary archival assets and secondary captures.
- **On-Demand Precision**: Modular architecture allowing for specialized model deployment.

### 🎬 Transcoding Dashboard
Integrated high-efficiency video transformation suite.
- **Modern Standards**: Conversion optimized for space-saving AV1 deployment.
- **Cinematic Integrity**: Native passthrough for HDR10 and HLG high-dynamic-range metadata.
- **Hardware Acceleration**: Deep integration with NVIDIA NVENC and high-performance SVT-AV1 engines.

---

## 🛠️ Installation

### Arch Linux (AUR)
Install via any AUR wrapper:
```bash
yay -S chronoarchiver
```

### Manual Deployment
1. **Source Download**:
   ```bash
   git clone https://github.com/UnDadFeated/ChronoArchiver.git
   cd ChronoArchiver
   ```
2. **Environment Setup**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Execution**:
   ```bash
   python src/ui/app.py
   ```

---

## 📋 System Requirements
- **Python 3.10+**
- **FFmpeg Core Utilities**
- **NVIDIA GPU** (Optional, recommended for accelerated transcoding)

---

## ☕ Support
If ChronoArchiver enhances your archival workflow, contributions are welcome via the **Donate** section within the application.

## 📜 License
Independent software distributed under the MIT License.

---
*Maintained by [UnDadFeated](https://github.com/UnDadFeated)*
