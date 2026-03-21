# CHANGELOG

## [1.0.6] - 2026-03-21
### Added
- **AI Scanner**: Migrated animal detection to native OpenCV DNN using TFLite. This eliminates the heavy `mediapipe` dependency and reduces the installation footprint.
- **UI Logic**: Transitioned AI model downloads to a manual, user-triggered flow via a new "Download Models" button.
- **Packaging**: Simplified AUR dependencies by removing `python-mediapipe`, `python-sounddevice`, and `python-send2trash`.

### Fixed
- **Performance**: Optimized startup time by removing automatic background model verification/download on every launch.
- **Dependency Map**: Cleaned up `requirements.txt` and packaging scripts to reflect the leaner architecture.

## [1.0.5] - 2026-03-21
### Added
- **AI Scanner**: Integrated `ModelManager` for mandatory SHA-256 integrity verification on launch. The engine now verifies model health and automatically restores corrupt models before allowing a scan.
- **AV1 Encoder**: Implemented immediate process cancellation. Hitting "Stop" now terminates active ffmpeg processes instantly rather than waiting for the current file to finish.

### Fixed
- **UI Logic**: Wired background threading for model verification in the AI Scanner tab with real-time status reporting.
- **README**: Corrected backend-specific preset direction semantics to be technically accurate for both NVENC and SVT-AV1.
- **Stability**: Fixed potential NameErrors by ensuring `os` and `sys` are correctly imported in `tabs.py`.

## [1.0.4] - 2026-03-21
### Fixed
- **Phantom UI Controls**: Wired up "Photos" and "Videos" checkboxes in Archival Core to filter valid extensions.
- **Parallel Encoding**: Implemented `ThreadPoolExecutor` in Transcoding Dashboard to honor the "Threads" setting.
- **UI Nits**: Fixed "Recommmended" typo (three m's) and removed redundant `minsize` window constraints.
- **Code Cleanup**: Removed stale/backwards comments in `AIScannerTab` from v1.0.0.

### Changed
- **Performance**: High-efficiency concurrent encoding now utilizes separate engine instances per worker thread for stability.
- **Git Tracking**: Restricted `.md` internal documentation to local scope only.

## [1.0.3] - 2026-03-21
### Fixed
- **Integrity**: Fixed `efficientdet_lite0.tflite` (Animal Detection) SHA-256 hash.
- **Cleanup**: Removed stale comments in `tabs.py`.
- **Cleanup**: Deleted unused `use_gpu` variable.
- **Refactor**: Moved `hashlib` and `queue` imports to module level.

## [1.0.2] - 2026-03-21
### Fixed
- **CRITICAL**: Fixed `NameError: filename` and regression in `av1_tab.py` that caused encoder crashes.
- **Improved Security**: Updated `face_detection` hash to official digest.
- **Better Debugging**: Added actual hash logging on mismatch for AI models.
- **UI Metrics**: Fixed swapped file counters in the AI Scanner lists.
- **Code Optimization**: Removed redundant date parsing loops in `organizer.py`.
- **Consistency**: Fixed CRLF line endings in `logger.py`.

## [1.0.1] - 2026-03-21
### Fixed
- Resolved `NameError` in `organizer.py` and `scanner.py` (missing `pathlib` import).
- Robust cross-platform logging using `platformdirs`.
- Corrected logic inversion in AI Scanner results (Keep Subjects / Move Others).
- Implemented semantic versioning for update checks.
- Wired up `maintain_structure` for AV1 Encoder.
- Sanitized donation links (PayPal.me/Venmo).

## [1.0.0] - 2026-03-21
### Added
- Initial project release of **ChronoArchiver**.
- Merged **Media Archive Organizer** and **Mass AV1 Encoder** into a single application.
- New **AV1 Encoder** tab with a unified CustomTkinter premium UI.
- **AI Model Manager**: Automated check and on-demand downloader for scanner models.
- Support for **HDR Detection** and **NVENC/SVT-AV1** encoding in a unified interface.
- Thread-safe UI updates for all long-running processes (encoding, scanning, downloading).
