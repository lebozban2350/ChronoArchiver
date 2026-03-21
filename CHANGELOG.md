# Changelog

## [2.0.5] - 2026-03-21
### Added
- **Update and restart flow**: When an update is available and the user clicks the update button, the app prompts for confirmation, then closes, performs the update, and restarts.
- **Windows (git)**: Uses `git pull` in the repository root.
- **Linux (git)**: Same git-pull flow for development/source installs.
- **Arch Linux (AUR)**: Uses `paru`, `yay`, or `pkexec pacman` to update the `chronoarchiver` package. Spawns a terminal when available for interactive sudo/AUR prompts.
- Install method is detected automatically (git clone vs AUR package).

## [2.0.4] - 2026-03-21
### Changed
- AI Encoder: Reorganized config layout—Directories on top, Configuration below, Options on the right spanning full height.
- AI Encoder: Removed Metrics box; moved CPU/GPU/RAM to global footer (right-aligned, labels and values only).
- Nav bar: Added "☕ Buy me a coffee" donate button linking to PayPal $5 USD for jscheema@gmail.com.

## [2.0.3] - 2026-03-21
### Fixed
- **Linux icon display (AUR pkgrel≥2)**: Install application icon to `/usr/share/icons/hicolor/` (256x256 and 48x48) in addition to pixmaps, so GNOME/KDE and other modern desktop environments use the correct green hourglass icon instead of cached or legacy icons.
- Added `chronoarchiver.install` with post_install hook to run `gtk-update-icon-cache` on hicolor, forcing icon cache refresh after install/upgrade.
### Changed
- Media Organizer: Squished top boxes (Directories, Options, Execution Mode) to content height; console now expands to fill all remaining vertical space.
- AI Encoder: Squished top boxes (Directories, Configuration, Options, Metrics) and Work Progress to content height; console now expands to fill all remaining vertical space.
- Applied `QSizePolicy.Maximum` on vertical axis for config/option group boxes so they do not scale when the window is resized.
- AI Scanner layout left unchanged (user may scale to view sample photos).

## [2.0.2] - 2026-03-21
### Fixed
- Fixed `_job_speeds` list corruption in `AV1EncoderPanel` where QLabel references were overwritten with float values.
- Fixed `ModelManager` progress callback in `AIScannerPanel` to use a proper wrapper compatible with `Signal(str)`.
- Corrected malformed docstrings (`""""` → `"""`) across UI modules and updater.
- Removed stray quote in `_on_telemetry` comment.

## [2.0.1] - 2026-03-21
### Fixed
- Fixed `ModelManager` path resolution in `AIScannerPanel` for correct local core directory detection.
- Corrected `OrganizerEngine` progress callback signature (added filename arg).
- Fixed engine control API mismatches (`cancel()` instead of `stop()`).
- Optimized `requirements.txt` by removing unused heavy dependencies (`torch`, `torchvision`, `tqdm`).
- Moved `QTimer` import to top-level for better module structure in `scanner_panel.py`.

## [2.0.0] - 2026-03-21
### Added
- Complete migration from CustomTkinter to **PySide6**.
- New high-density UI matching Mass AV1 Encoder v12 style.
- Panel-based architecture (`MediaOrganizerPanel`, `AV1EncoderPanel`, `AIScannerPanel`).
- Global QSS stylesheet support.
- Headless `ApplicationUpdater` with callback integration.

### Changed
- Refactored `app.py` to use `QStackedWidget`.
- Updated `requirements.txt` with PySide6 dependencies.

### Removed
- Legacy CustomTkinter UI files (`src/ui/tabs/`, `src/ui/theme.py`).

## [1.0.26] - 2026-03-21
### Fixed
- Further optimized AV1 Tab layout for ultra-high-density (Top Strip ~150-160px).
- Moved configuration hints inline with checkboxes/controls to save vertical rows.
- Simplified ThreadSlot UI: removed redundant VID/AUD labels to focus on progress and speed.
- Tightened all vertical padding across the tab to prevent any UI overflow.

## [1.0.25] - 2026-03-21
### Fixed
- Refined AV1 Tab layout for high-density environments (Top Strip <= 200px).
- Reduced checkbox sizes (16x16px) and padding to prevent vertical overflow.
- Implemented explicit grid row weighting to ensure thread slots expand correctly.
- Enhanced browse button anchoring using a 100% width entry grid.

## [1.0.24] - 2026-03-21
### Fixed
- Overhauled AV1 Tab layout: replaced broken absolute positioning on Browse buttons with proper relative rows.
- Fixed metrics loop bug that captured stale CPU/RAM values.
- Integrated inline HH:MM:SS for "Skip Short Clips" to prevent layout overflow.
### Added
- "Optimize Audio" option to re-encode PCM/unsupported tracks to Opus.
- Comprehensive muted hint labels for all encoding options.

## [1.0.23] - 2026-03-21
### Changed
- Moved `python-opencv` to optional dependencies to reduce installation size by ~320MB (excludes vtk/etc).
- Application now checks for OpenCV at runtime and provides a clear message if AI features are disabled.

## [1.0.22] - 2026-03-21
### Fixed
- Removed bundled large AI models from the source repository to restore intended on-demand download behavior.
- Added `.gitignore` to `src/core/models/` to ensure directory persistence without bundling binary assets.

## [1.0.21] - 2026-03-21
### Fixed
- AUR build failure caused by incorrect icon path in `PKGBUILD`.

## [1.0.20] - 2026-03-21
### Fixed
- Application startup crash (`ImportError`) by restoring `__version__` variable.
- Application icon loading by restructuring assets into `src/ui/assets/`.
- Malformed `.desktop` file entries.
- Corrupted `CHANGELOG.md` document formatting.


## [1.0.19] - 2026-03-21
### Added
- Feature parity with Mass AV1 Encoder v12.0.0.
- Restoration of the Options panel (Shutdown, HW Accel, Skip Short, Delete Source).
- Real-time Metrics dashboard (CPU, GPU, RAM) in the top row.
- Pause/Resume control for active encoding jobs.
- Per-thread speed labels (e.g., "2.3x") and Space Saved telemetry.
- Muted hint text under directory fields for better guidance.
### Improved
- Preset labels are now more descriptive (e.g., "P4: Standard").
- Refactored top row layout to 4-column high-density grid.

## [1.0.18] - 2026-03-21
### Added
- **Custom Split Navigation**: Replaced the standard tab view with a bespoke navbar. Functional tools (Media Organizer, Mass AI Encoder, AI Scan) are pinned to the left, while **Donate** is pinned to the right.
- **Footer-Integrated Updates**: Relocated the "Check for Updates" action to the global status footer for a cleaner header area.
### Removed
- Removed the "Time to Archive!" catchline and legacy update button from the console header to minimize visual clutter.

## [1.0.17] - 2026-03-21
### Added
- **Major UI Overhaul**: Renamed and reordered tabs for better workflow (Media Organizer, Mass AI Encoder, AI Scan).
- **Global Status Footer**: Added a persistent footer showing app status, background activity, and quick-access support links.
- **Mass AI Encoder Mastery**:
  - High-density thread monitors with per-thread progress and speed.
  - Stacked Video/Audio codec information per encoding slot.
  - Master Queue progress bar with file count tracking.
  - Real-time ETA and Elapsed Session Timer.
  - Live Queue discovery list.
- **Unified Status Architecture**: Integrated all functional tabs into the global status and background tracking system.

## [1.0.16] - 2026-03-21
### Fixed
- **Startup Crash (TclError)**: Removed invalid `width` parameter from `.pack()` call in AV1 Encoder tab that caused the application to fail during initialization.
### Added
- **Full-Frame Premium Icon**: Re-generated the application icon with zero-margin framing and intrinsic rounded corners to ensure maximum visual presence in the taskbar and desktop.

### Added
- **Pixel-Perfect Icon Scaling**: Re-processed the premium icon to fit exactly top-to-bottom within the 256px frame, maximizing visual impact and ensuring absolute alpha transparency.
### Fixed
- **AUR Dependency Fix**: Corrected `PKGBUILD` to depend on `python-opencv` instead of `opencv`, resolving the `ModuleNotFoundError: No module named 'cv2'` on Arch Linux.

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
- **Dead Code**: Pruned unreachable initialization statements inside the OpenCV Deep Neural Network (`cv2.dnn`) constructor branches.
## [1.0.9] - 2026-03-21
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
