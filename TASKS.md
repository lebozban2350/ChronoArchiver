# TASKS

- [x] **v1.0.15: Dependency & Icon Refinement (2026-03-21)**
  - [x] Fix AUR Dependency: Change `opencv` to `python-opencv` in `PKGBUILD`.
  - [x] Refine Icon: Pixel-perfect vertical scaling (256px height) and transparency.
  - [x] Bump version to 1.0.15 and push to GitHub/AUR.


- [x] **v1.0.14: Architecture & Branding Refresh (2026-03-21)**
  - [x] Fix Circular Import: Move constants to `ui.theme`.
  - [x] Refactor `ui.tabs.py` into `ui.tabs/__init__.py`.
  - [x] Refine Icon: Transparent background, maximized size within 256x256.
  - [x] Bump version to 1.0.14 and push to GitHub/AUR.


- [x] **v1.0.13: Brand Identity - Catchline (2026-03-21)**
  - [x] Integrate "Time to Archive!" into `app.py` UI (title and label).
  - [x] Update `README.md` with the new catchline.
  - [x] Update `PKGBUILD` and `.desktop` descriptions.
  - [x] Bump version to 1.0.13 and push to GitHub/AUR.


- [x] **v1.0.12: Premium Icon Branding (2026-03-21)**
  - [x] Research and generate a high-fidelity application icon.
  - [x] Convert generated asset to `icon.png` and `icon.ico`.
  - [x] Verify icon display in the `chronoarchiver.desktop` entry.
  - [x] Bump version to 1.0.12 and synchronize GitHub/AUR.


- [x] **v1.0.11: Linux Desktop Integration (2026-03-21)**
  - [x] Create `chronoarchiver.desktop` specification file.
  - [x] Update `PKGBUILD` to install desktop entry and application icon.
  - [x] Bump version to 1.0.11 in `src/version.py`, `README.md`, and `CHANGELOG.md`.


- [x] **v1.0.10: Final Polish & Audits (2026-03-21)**
  - [x] Refactor `tarfile.extract()` to safely use the Python 3.12+ `filter='data'` parameter.
  - [x] Remove dead guard code around `cv2.dnn.readNetFromTensorflow()` path references.
  - [x] Emit explicit "Extracting..." GUI status when expanding AI models from `.tar.gz` payload.

- [x] **v1.0.9: Final Pre-release Bugfixes (2026-03-21)**
  - [x] Fix `updater.py` repo target URLs (`MediaArchiveOrganizer` -> `ChronoArchiver`)
  - [x] Fix `dialog.destroy()` TclError on cancel in `tabs.py`
  - [x] Switch Animal Detector to TF `frozen_graph` (`.pb`/`.pbtxt`) format to bypass OpenCV `UINT8` quantization crash
  - [x] Support remote `.tar.gz` model payload extraction inside `model_manager.py`

- [x] **v1.0.8: Hotfix (2026-03-21)**
  - [x] Fix parsing of 4-tensor output for `ssd_mobilenet_v1_1_metadata_2.tflite`
  - [x] Thread post-download `_init_model_check` in `tabs.py`

- [x] **v1.0.7: Logic Hardening & UX (2026-03-21)**
  - [x] Refactor AI Scanner to SSD MobileNet V1
  - [x] Implement ModelDownloadDialog with real-time progress
  - [x] Thread `_init_model_check` in `__init__` to prevent startup freeze
  - [x] Push v1.0.7 to GitHub and AUR

- [x] **v1.0.6: Architectural Optimization (2026-03-21)**
  - [x] Migrate AI Scanner to OpenCV DNN (MediaPipe Removal)
  - [x] Implement manual user-triggered model download flow
  - [x] Prune dependencies (`mediapipe`, `sounddevice`, `send2trash`)
  - [x] Push v1.0.6 to GitHub and AUR

- [x] **v1.0.5: Model Integrity & Doc Fixes (2026-03-21)**
  - [x] Integrate ModelManager for mandatory SHA-256 verification
  - [x] Implement background verification thread in AIScannerTab
  - [x] Fix README preset direction semantics
  - [x] Fix missing os/sys imports in tabs.py
  - [x] Implement immediate process cancellation in AV1 Encoder
  - [x] Push v1.0.5 to GitHub and AUR

- [x] **v1.0.4: Final Polish & Concurrency (2026-03-21)**
  - [x] UI: Wire up Photo/Video filters in Organizer
  - [x] Performance: Implement Parallel Encoding using ThreadPoolExecutor
  - [x] UI: Fix "Recommmended" typo (three m's)
  - [x] UI: Remove redundant `minsize` constraint in `app.py`
  - [x] Release: Tag v1.0.4 and push to GitHub/AUR

- [x] **v1.0.3: Final Ship & Polish (2026-03-21)**
  - [x] Integrity: Fix `efficientdet_lite0.tflite` SHA-256 hash
  - [x] Cleanup: Remove stale comments in `tabs.py`
  - [x] Cleanup: Delete unused `use_gpu` in `tabs.py`
  - [x] Refactor: Move `hashlib` and `queue` imports to top level
  - [x] Release: Bump version to `v1.0.3`

- [x] **v1.0.2: Regression Fixes & Refinement**
  - [x] Fix crash: `NameError: filename` in `av1_tab.py`
  - [x] Security: Update official face model hash
  - [x] UX: Fix swapped file counters in AI Scanner lists
  - [x] Cleanup: Remove redundant loops in `organizer.py`
  - [x] Consistency: Fix CRLF in `logger.py`
  - [x] Release: Bump version to `v1.0.2`

- [x] **v1.0.1: Code Review & Stability Overhaul**
  - [x] **Fix Crash Bugs**
    - [x] `pathlib` imports in `organizer.py` and `scanner.py`
    - [x] `logger.py`: Fix path handling & platformdirs
  - [x] **Fix Logic Bugs**
    - [x] `updater.py`: Semantic version comparison
    - [x] `scanner.py` & `tabs.py`: Fix inverted naming (Keep/Move)
    - [x] `organizer.py`: Validate dates with `strptime`
    - [x] `av1_tab.py`: Implement `maintain_structure`
  - [x] **Cleanup Code Smells**
    - [x] `requirements.txt`: Remove unused `PySide6`
    - [x] `model_manager.py`: Add SHA-256 integrity checks
    - [x] `organizer.py`: Move all imports to top
    - [x] `logger.py`: Fix line endings & `.gitattributes`
    - [x] `tabs.py`: Use PayPal.me/Venmo handles for donations
  - [x] **Verify & Final Version Bump (1.0.1)**

- [x] **v1.0.0: Initial Release**
  - [x] Initialize project structure and artifacts
  - [x] Research source codebases
  - [x] Port `Media_Archive_Organizer` (Theme & Core)
  - [x] Port `Mass_AV1_Encoder` as a tab
  - [x] Implement LLM model check & download feature
  - [x] Verify merged application
