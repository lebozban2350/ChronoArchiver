# CHANGELOG

## [1.0.14] - 2026-03-21
### Added
- **Transparent Premium Icon**: Re-generated the application icon with a pure transparent background and tighter framing for a more professional look.
### Fixed
- **Circular Import**: Resolved a critical `ImportError` by extracting UI constants into `src/ui/theme.py` and refactoring the `ui.tabs` module into a proper package.


## [1.0.13] - 2026-03-21
### Added
- **Brand Catchline**: Integrated the official catchline "Time to Archive!" across the UI (title bar and log header), `README.md`, and packaging metadata.


## [1.0.12] - 2026-03-21
### Added
- **Premium Icon Design**: Generated and integrated a high-fidelity application icon suite (`src/assets/icon.png` and `src/assets/icon.ico`) to give ChronoArchiver a professional, branded identity.


## [1.0.11] - 2026-03-21
### Added
- **Linux Desktop Integration**: Added a standard `.desktop` entry and application icon installation to ensure ChronoArchiver appears in system application menus (fixed "missing in apps" issue).
- **Packaging**: Updated `PKGBUILD` to automate the installation of the desktop file and icon.


## [1.0.10] - 2026-03-21
### Fixed
- **Extraction Warnings**: Fixed `DeprecationWarning` in Python 3.12+ environments by explicitly requesting `filter='data'` during AI model `.tar.gz` extractions.
- **Model Download Statuses**: Download manager now correctly isolates the `.tar.gz` download state from the `.pb` network payload. 
- **Dead Code**: Pruned unreachable initialization statements inside the OpenCV Deep Neural Network (`cv2.dnn`) constructor branches.## [1.0.9] - 2026-03-21
### Fixed
- **Updater Repo Issue**: Corrected the destination URLs in the updater to point to `UnDadFeated/ChronoArchiver` instead of the old app name.
- **Cancel Crash Fix**: Fixed an issue where stopping a model download would attempt to destroy an already-destroyed UI component.
- **OpenCV Inference Compatibility**: Migrated the animal scanner from a quantized TFLite model to the official SSD MobileNet V1 Frozen Inference Graph to retain full `cv2.dnn` compatibility.
- **Model Extractor**: Added native `.tar.gz` payload extraction inside the model downloader.

## [1.0.8] - 2026-03-21
### Fixed
- **Post-Download Freeze**: Ensured the SHA-256 hash verification runs in a background thread immediately after downloading models, preventing a temporary UI hang.
- **Animal Detection Logic**: Updated parsing logic in `_detect_animal()` to properly index the 4-tensor output (boxes, class_ids, scores, num_detections) from the TF Task Library SSD model.

## [1.0.7] - 2026-03-21
### Added
- **AI Scanner UX**: Added a dedicated `ModelDownloadDialog` with real-time progress bars, speed tracking, and a responsive cancellation option.

### Fixed
- **Model Compatibility**: Switched animal detection model from EfficientDet Lite0 to SSD MobileNet V1 quantized TFLite. This uses the standard `[1, 1, N, 7]` SSD output format natively supported by OpenCV, resolving silent detection failures.
- **Startup Performance**: Wrapped the initial AI model SHA-256 verification sequence in a background thread to completely eliminate UI freezing on slower disks.

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
