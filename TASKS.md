# TASKS

**Current:** v3.2.23 (2026-03-23)

---

- [x] **v3.2.23: Model setup size estimate (2026-03-23)**
  - [x] SSD model approx_size: 30 MB (extracted) → 76.5 MB (tar.gz download).

- [x] **v3.2.22: Model download log throttle (2026-03-23)**
  - [x] Log only when pct changes; fixes 9k+ line spam.

- [x] **v3.2.21: OpenCV manual install + Engine Status buttons (2026-03-23)**
  - [x] Bootstrap skip_opencv=True; user installs in AI Scanner.
  - [x] All Engine Status buttons 100px; guide glow no layout shift.

- [x] **v3.2.20: Engine Status UI polish (2026-03-22)**
  - [x] Install OpenCV button 100px; guide blink layout shift fix.

- [x] **v3.2.19: Footer + Engine Status queue poll (2026-03-22)**
  - [x] _refresh_footer and _check_models use queue + poll for cross-thread delivery.
  - [x] AI Scanner Engine Status labels all caps.

- [x] **v3.2.18: FFmpeg progress queue + footer caps (2026-03-22)**
  - [x] FFmpeg progress: queue + main-thread poll instead of QTimer from worker.
  - [x] Footer text all caps for visibility.

- [x] **v3.2.17: Startup hang during FFmpeg install (2026-03-22)**
  - [x] Defer scanner _check_models until prereqs done; run check_opencv_in_venv off main thread.
  - [x] _refresh_footer and _check_models use thread + QTimer for opencv check.

- [x] **v3.2.16: OpenCV CUDA fix after restart (2026-03-22)**
  - [x] check_opencv_in_venv: _add_nvidia_libs_to_ld_path + env=os.environ for subprocess.
  - [x] bootstrap: add_venv_to_path before execv so child gets LD_LIBRARY_PATH.

- [x] **v3.2.15: FFmpeg footer download speed (2026-03-22)**
  - [x] ensure_ffmpeg_in_venv_with_progress(progress_callback) with real streaming download and speed (e.g. "2.3 MB/s").
  - [x] Speed label next to FFmpeg progress bar in footer during install.

- [x] **v3.2.14: GitPython for updater (2026-03-22)**
  - [x] GitPython in venv; updater uses it for git pull instead of system git.
  - [x] Fallback to system git if GitPython unavailable.

- [x] **v3.2.13: FFmpeg venv auto-install with footer progress bar (2026-03-22)**
  - [x] static-ffmpeg in VENV_PACKAGES_BASE; check_ffmpeg_in_venv, ensure_ffmpeg_in_venv, add_ffmpeg_to_path.
  - [x] Pre-req: when venv exists and FFmpeg missing, auto-install with tiny progress bar + % in left footer.
  - [x] Always use venv FFmpeg; PKGBUILD no longer depends on system ffmpeg.

- [x] **v3.2.12: nvidia-cufft for OpenCV CUDA (2026-03-22)**
  - [x] Add nvidia-cufft to CUDA stack; provides libcufft.so.12 required by OpenCV CUDA wheel.
  - [x] Fixes post-restart "Not installed" / yellow OpenCV when cv2 import failed with missing libcufft.
  - [x] Components, uninstall list, scanner dialog, docs updated.

- [x] **v3.2.11: RESTART Button Width Fix (2026-03-22)**
  - [x] RESTART button 90px (was 165px) to avoid clipping into Engine Status border.
  - [x] Venv cleaned for re-test.

- [x] **v3.2.10: Green RESTART Button After OpenCV Install (2026-03-22)**
  - [x] After successful OpenCV install, Install button becomes green glowing RESTART; restart_app() in updater; click relaunches app.

- [x] **v3.2.9: Signal Type Fix + Intensive Debug (2026-03-22)**
  - [x] setup_complete Signal(bool)→Signal(object); fix install success not reported.
  - [x] More debug: task emit, slot recv, check_opencv_in_venv, _check_models.

- [x] **v3.2.8: Wheel Filename Fix (2026-03-22)**
  - [x] Save downloaded wheel with valid PEP 427 filename (not tmpXXX.whl); fixes pip install failure.

- [x] **v3.2.7: Install Debug Logging + Venv Clean (2026-03-22)**
  - [x] Debug log: all OpenCV install phases, pip stderr on fail, Model setup, popup completion.
  - [x] CUDA install: "may take 2–5 min" hint so UI not perceived as frozen.
  - [x] Venv cleaned for re-test (nvidia + opencv removed).

- [x] **v3.2.6: nvidia-cublas in CUDA Stack (2026-03-22)**
  - [x] Components list and pip install include `nvidia-cublas` with size estimate (~384 MB).

- [x] **v3.2.5: CUDA/cuDNN Venv-Only (No Sudo) (2026-03-22)**
  - [x] CUDA runtime and cuDNN via pip (nvidia-cuda-runtime, nvidia-cudnn-cu13) into app venv.
  - [x] Removed pacman/pkexec/sudo; all CUDA stack app-internal.

- [x] **v3.2.4: CUDA/cuDNN Auto-Install (2026-03-22)**
  - [x] CUDA Toolkit and cuDNN in components list; auto-install via pacman on Arch before wheel. (Superseded by v3.2.5 venv-only.)

- [x] **v3.2.3: OpenCV Progress UX (2026-03-22)**
  - [x] Download speed (MB/s) in progress popup.
  - [x] At 100% download → "Installing... / Setting up wheel" so UI not frozen during pip.

- [x] **v3.2.2: OpenCV Install Fix (2026-03-22)**
  - [x] CUDA: show only wheel in components (~483 MB); progress matches download.
  - [x] Surface pip error to console on failure.
  - [x] CUDA wheel fail → auto-fallback to OpenCL build.

- [x] **v3.2.1: Remove Media Converter (2026-03-22)**
  - [x] Media Converter panel and engine removed.

- [x] **v3.2.0: Layout, CUDA Components (2026-03-22)**
  - [x] Install OpenCV layout fix: Engine Status no stretch; fixed button width, variant in tooltip.
  - [x] CUDA install: CUDA Toolkit and cuDNN listed as components with sizes; removed "install separately" message.

- [x] **v3.1.0: GPU-Specific OpenCV Variants (2026-03-21)**
  - [x] detect_gpu() extended for nvidia|amd|intel; get_opencv_variant() returns cuda|opencl_amd|opencl_intel|opencl.
  - [x] Install flow: NVIDIA→CUDA wheel; AMD/Intel/integrated→opencv-python (OpenCL).
  - [x] Engine Status button shows "Install {variant}" when OpenCV missing.
  - [x] docs/GPU_ACCELERATION.md updated.

- [x] **v3.0.10: OpenCV Fixed Progress Bar (2026-03-21)**
  - [x] Progress bar driven by download size; wheel streaming; MB/total in detail.
  - [x] Install confirmation: components list, sizes, total; CUDA/cuDNN note.

- [x] **v3.0.9: OpenCV No Auto-Reinstall (2026-03-21)**
  - [x] Bootstrap uses is_venv_runnable() (no OpenCV); uninstall no longer triggers reinstall.

- [x] **v3.0.8: Models UX, Footer Refresh (2026-03-21)**
  - [x] Models row: Setup Models only when missing; Uninstall Models when installed (like OpenCV).
  - [x] Footer refreshes on OpenCV/models install or uninstall.

- [x] **v3.0.7: OpenCV Status, Uninstall, Layout (2026-03-21)**
  - [x] Runtime OpenCV check (check_opencv_in_venv); fix stale green checkmark.
  - [x] Uninstall OpenCV in thread; UI updates without restart.
  - [x] Options stacked vertically; Directories/Options/Engine same height.

- [x] **v3.0.6: Code Audit Fixes (2026-03-21)**
  - [x] OpenCVSetupDialog thread-safety (Signal for progress updates).
  - [x] venv_manager: opencv-contrib-python-headless in uninstall lists.
  - [x] Improved CUDA wheel error message.

- [x] **v3.0.0: App-Private Venv Internalization (MAJOR) (2026-03-21)**
  - [x] Launcher runs bootstrap.py; first run creates venv and installs all Python deps.
  - [x] PKGBUILD: python + ffmpeg only.
  - [x] Scanner Setup Models / Remove Models use venv_manager.
  - [x] Version check uses venv pip for opencv outdated.

- [x] **v2.0.62: OpenCV App-Private Venv (No Sudo) (2026-03-22)**
  - [x] On Linux: create venv, install opencv-python (no sudo); app adds venv to sys.path at startup.
  - [x] Remove Models: delete venv; pip uninstall for Windows.

- [x] **v2.0.61: Setup Models OpenCV Progress + Arch Hint (2026-03-22)**
  - [x] Show pip output live in setup dialog; indeterminate bar; externally-managed-environment → suggest pacman -S python-opencv.

- [x] **v2.0.60: Guide on Setup when OpenCV Missing (2026-03-22)**
  - [x] Guide targets Setup Models when OpenCV missing (even if models installed); click installs OpenCV.

- [x] **v2.0.59: Remove Models + Update! Button (2026-03-22)**
  - [x] Remove Models button always visible; deletes model files, uninstalls OpenCV (pip).
  - [x] Update! button next to "All Models Ready!" only when OpenCV or AI Models update detected during pre-check.

- [x] **v2.0.58: Footer + Setup Models + Uninstall (2026-03-22)**
  - [x] Footer: OpenCV and AI Models separate entries; OpenCV=cv2 only; AI Models=model files.
  - [x] Setup Models: installs OpenCV via pip when missing, then downloads models; restart prompt.
  - [x] Uninstall: documented clean removal; OpenCV not auto-removed.

- [x] **v2.0.57: AI Scanner OpenCV Gate Fix (2026-03-22)**
  - [x] Footer OpenCV status reflects cv2 import only (no models_ready override); scanner gates START on OPENCV_AVAILABLE; shows "OpenCV (python-opencv) required" when missing.

- [x] **v2.0.56: AI Scanner Results UX (2026-03-22)**
  - [x] Target folder input, Move/Copy dropdown, START button (green when target set); smaller console; guide flow to Browse Target and START.

- [x] **v2.0.55: OpenCV + Models Ready (2026-03-22)**
  - [x] OpenCV green when cv2 imports OR models ready; "All Models Ready!"

- [x] **v2.0.54: OpenCV Footer (2026-03-22)**
  - [x] Direct cv2 import at check time; broad exception handling.

- [x] **v2.0.53: OpenCV Footer Fix (2026-03-22)**
  - [x] Footer: OpenCV shows green ✓ when installed (use OPENCV_AVAILABLE from scanner).

- [x] **v2.0.52: Model Setup UX (2026-03-22)**
  - [x] Progress only in setup popup, not main panel bar; "Installing models... please wait..." during extract/verify.

- [x] **v2.0.51: Pre-check Footer (2026-03-22)**
  - [x] Left footer: Checking FFmpeg…, OpenCV…, PySide6… then Pre-check complete 3s, then Idle.

- [x] **v2.0.50: Model URL Fixes (2026-03-22)**
  - [x] Face: Hugging Face; Animal tar: storage.googleapis.com (TensorFlow SSL fix).

- [x] **v2.0.49: AI Scanner Setup Models Fix (2026-03-22)**
  - [x] Setup Models: popup dialog with URL, model, fixed progress bar; Signal-based thread-safe completion.
  - [x] Download all models in one go; detect on next launch; model version check (yellow optional).

- [x] **v2.0.48: Hardening + Researched Issues (2026-03-22)**
  - [x] Organizer EXIF; model manager HTTP/timeout; updater race/retry/fd; AV1 settings encoding; webbrowser.open; long-path warning.
  - [x] docs/KNOWN_ISSUES_AND_MITIGATIONS.md.

- [x] **v2.0.47: Config Sanitize + Edge Cases (2026-03-22)**
  - [x] AV1 config sanitize (concurrent_jobs, quality, preset, etc.); encoder worker clamp; scanner progress clamp; GitHub Accept header.

- [x] **v2.0.46: Minor Robustness Fixes (2026-03-22)**
  - [x] Updater: handle non-list API response; "UPDATE CHECK UNAVAILABLE" when check fails; debug log instead of print.
  - [x] Encoder: guard commonpath for ValueError (mixed drives).

- [x] **v2.0.45: Update Check Tags API (2026-03-22)**
  - [x] Use GitHub tags API instead of releases/latest; fixes "up to date" when no Releases exist (tags only).

- [x] **v2.0.44: Encoder Auto-Stop on Batch Complete (2026-03-22)**
  - [x] Emit batch_complete signal when last worker exits; _on_batch_complete transitions UI to ENCODING COMPLETE so user does not need to click STOP.

- [x] **v2.0.43: Encoder Structure Root (No Source Folder) (2026-03-22)**
  - [x] Use common parent of queued files as structure root when mirroring; no longer recreates top-level "Source" or similar wrapper folders in target.

- [x] **v2.0.42: Master Bar + ETA on File Complete (2026-03-22)**
  - [x] Update master bar and ESTIMATED TIME REMAINING in _on_encode_finished (fixes bar at 0 when progress callback never fires).
  - [x] Add out_time_ms progress parsing fallback.

- [x] **v2.0.41: AMD HW Encode, Footer Activity, Encoder Fixes (2026-03-22)**
  - [x] AMD av1_vaapi (Linux), av1_amf (Windows) when CUDA unavailable.
  - [x] NVIDIA: -hwaccel_output_format cuda for full GPU pipeline.
  - [x] Footer: activity with animated dots (Encoding..., Organizing..., Scanning...).
  - [x] Encoder: progress parsing, I/O throughput, ETA, master bar, fps/speed in threads.

- [x] **v2.0.40: Encoder Browse Target + Footer Colors (2026-03-22)**
  - [x] Encoder: _browse_dst now calls _update_start_enabled() — START button responds when target selected via Browse.
  - [x] Footer: green ✓ success, red ✗ failed, yellow — optional (OpenCV when not installed).

- [x] **v2.0.39: Guide Glow on START (2026-03-22)**
  - [x] All panels: guide now pulses on START button as 3rd step when all inputs ready (was disappearing).

- [x] **v2.0.38: Log Consolidation + Internal App Notation (2026-03-22)**
  - [x] Single log per session; prune after create to cap at 3 files in log folder.
  - [x] All entries identify internal app (av1_engine→ChronoArchiver.Encoder, model_manager→ChronoArchiver.Scanner).

- [x] **v2.0.37: Encoder Scan Completion Fix (2026-03-22)**
  - [x] Scan dialog closes and applies results correctly; thread-safe scan_done / scan_done_then_start signals.

- [x] **v2.0.36: Encoder Scan Dialog Emit (2026-03-22)**
  - [x] Scan dialog emits for every file found; count increments per file (no throttling).

- [x] **v2.0.35: Single Log File + Verbose Logging (2026-03-22)**
  - [x] One timestamped log per session; consolidate; more data logged.

- [x] **v2.0.34: Scanner Robustness (2026-03-22)**
  - [x] Emit threshold 25 files/100ms; remove processEvents; engine robustness; _done guards.

- [x] **v2.0.33: Scan Bar Animation + Freeze Fix (2026-03-22)**
  - [x] Restore indeterminate bar; more frequent updates; processEvents.

- [x] **v2.0.32: Encoder Folder + Scan Fixes (2026-03-22)**
  - [x] Don't save source/target; scan dialog thread-safe updates; fix double log; static bar.

- [x] **v2.0.31: Scan on User Action Only (2026-03-22)**
  - [x] Remove init auto-scan; scan dialog only when user selects source.

- [x] **v2.0.30: Encoder Scan Dialog (2026-03-22)**
  - [x] Separate ScanProgressDialog for auto-scan (file count, total size); main bar encoding-only.

- [x] **v2.0.29: Encoder UI Fixes (2026-03-22)**
  - [x] Directories top padding; Configuration bottom alignment; progress bar no animation during idle/auto-scan.

- [x] **v2.0.28: Fail-safes (2026-03-21)**
  - [x] Media Organizer: disk space, writable, overlap, permissions, long paths.
  - [x] AI Scanner: corrupt image log, permission handling, skip large images.
  - [x] Encoder: FFmpeg check, disk space, existing output policy, partial cleanup.
  - [x] Cross-cutting: worker try/except.

- [x] **v2.0.27: Unified Queue Strategy (2026-03-21)**
  - [x] All three apps: queue (path, size), byte-weighted master progress.

- [x] **v2.0.26: Encoder Scan Before Guide (2026-03-21)**
  - [x] Guide stays on source until scan completes; Work Progress shows Scanning...; guide moves to target after queue populated.

- [x] **v2.0.25: Layout Fixes (2026-03-21)**
  - [x] Encoder: source/target input boxes match width.
  - [x] AI Scanner: Setup Models glow padding fix (no text jump).

- [x] **v2.0.24: Guide Glow on Buttons (2026-03-21)**
  - [x] Glow targets Browse, Setup Models, Photos (buttons user clicks), not input fields.

- [x] **v2.0.23: Guide Glow on Next-Missing Input (2026-03-21)**
  - [x] Pulsing red glow on the input that needs attention (not START button).
  - [x] Organizer: source path → Photos/media types → target (step by step).
  - [x] Encoder: source → target.
  - [x] Scanner: Setup Models → folder path.

- [x] **v2.0.22: START Gates, Model Path & Download Progress (2026-03-21)**
  - [x] Media Organizer, Mass AV1 Encoder, AI Media Scanner: START disabled until all required inputs set.
  - [x] Media Organizer: source valid, media types or extensions, target valid if specified.
  - [x] Mass AV1 Encoder: source and target directories both valid.
  - [x] AI Media Scanner: valid folder AND ready models; folder check was missing.
  - [x] Model storage: `platformdirs.user_data_dir` (~/.local/share/ChronoArchiver/models) for AUR write permission.
  - [x] Download progress bar updates during model setup; status "Downloading...".

- [x] **v2.0.21: STOP Button Styling (2026-03-21)**
  - [x] Media Organizer, AI Media Scanner: STOP grey when disabled; START grey during processing; STOP red when active.
  - [x] Re-enable START on stop.

- [x] **v2.0.20: Footer Metrics & Pre-req Checkmarks (2026-03-21)**
  - [x] Footer: metrics (CPU, GPU, RAM) on all panels; app-level metrics poll.
  - [x] Pre-req checkmarks: bright green (#10b981) for ✓, red for ✗ when missing.

- [x] **v2.0.19: Footer Restructure (2026-03-21)**
  - [x] Left: app activity (Idle, Encoding..., Organizing...).
  - [x] Center: pre-req status (FFmpeg ✓, OpenCV ✓, PySide6 ✓, Ready).
  - [x] Right: COPY CONSOLE, DEBUG, metrics unchanged.

- [x] **v2.0.18: Config Dropdown Overlay Fix (2026-03-21)**
  - [x] Shrink Preset/Threads dropdowns 4px to prevent overlay on Optimize Audio.

- [x] **v2.0.17: Code Audit Fixes (2026-03-21)**
  - [x] Scanner: face detection empty-array check.
  - [x] Organizer: indentation fix in RENAME FIX branch.

- [x] **v2.0.16: Fix Dropdowns & Options Alignment (2026-03-21)**
  - [x] Fix Preset/Threads dropdown popups (QAbstractItemView styled; no more oversized overlay).
  - [x] Options box expands to match Directories + Configuration height.

- [x] **v2.0.15: Config Dropdowns Vertical Alignment (2026-03-21)**
  - [x] Shrink Preset/Threads dropdowns vertically (16px height, reduced padding) to save vertical space.
  - [x] Directories + Configuration align with Options box; horizontal sizing unchanged.

- [x] **v2.0.14: Cross-Platform Model Path & Open Logs (2026-03-21)**
  - [x] Fix scanner._get_model_path for AUR install (parent-of-core logic for source and packaged layouts).
  - [x] Fix encoder_panel._open_logs for macOS (Darwin) via `open`; add exception handling.

- [x] **v2.0.13: Encoder Dropdowns & AI Scanner Model Gate (2026-03-21)**
  - [x] Mass AV1 Encoder: skinnier dropdowns; align Directories+Configuration with Options.
  - [x] AI Media Scanner: "AI Models Missing!"; disable Start until models verified.

- [x] **v2.0.12: Debug Log Filename & App-Wide Events (2026-03-21)**
  - [x] Debug log filename: date/time (app start) in name; keep last 3.
  - [x] Debug events: Media Organizer, AI Media Scanner, Model Manager, app startup.

- [x] **v2.0.11: Encoder .mp4 Output, Skip Logic & Debug (2026-03-21)**
  - [x] Remove Output dropdown; always output .mp4 as stem_av1.mp4.
  - [x] Skip files with _av1 before extension in scan.
  - [x] Delete source only when both checkboxes selected.
  - [x] Shrink Configuration; move Work Progress up.
  - [x] Increase debug log events for encoder.

- [x] **v2.0.10: Encoder Auto-Scan & Layout Refinements (2026-03-21)**
  - [x] Mass AV1 Encoder: remove Queue Preview; auto-scan on source change; queue auto-reset.
  - [x] Mass AV1 Encoder: smaller dropdowns; compact Options and Configuration boxes.
  - [x] AI Media Scanner: right-align Start/Stop; larger progress bar.

- [x] **v2.0.9: AI Scanner Compact Layout & Media Organizer Equal Heights (2026-03-21)**
  - [x] AI Media Scanner: smaller Directories, Options, Engine Status boxes; horizontal Scanning Progress strip.
  - [x] AI Media Scanner: image preview on Keep/Move item selection after scan.
  - [x] Media Organizer: Directories, Options, Execution Mode boxes same vertical height.

- [x] **v2.0.8: Debug Logging, Footer Buttons & Feature Additions (2026-03-21)**
  - [x] Debug logging: single file, timestamps, utility name, rotation (3 files).
  - [x] Footer: COPY CONSOLE, DEBUG (open debug folder).
  - [x] Media Organizer: target dir, extensions override, summary stats, ffprobe creation_time.
  - [x] Mass AV1 Encoder: queue preview, output format, CRF hints.
  - [x] AI Media Scanner: Keep/Move lists, Move Files, Keep Animals, confidence threshold, Export CSV.
  - [x] Panel renames: Mass AV1 Encoder, AI Media Scanner.

- [x] **v2.0.7: Updater Queue Fix & Code Cleanup (2026-03-21)**
  - [x] Updater: Replace Signal with queue + main-thread QTimer polling (resolves stuck "CHECKING...").
  - [x] Remove unused imports (pathlib, QSizePolicy, QProgressBar, etc.) and dead code (telemetry signal, REPO_URL).
  - [x] Fix bare `except:` → `except Exception:`/`except OSError:` in scanner and organizer.
  - [x] Remove concurrent.futures, _worker_lock, unused _slbl; correct AI Scanner hint (YuNet/SSD).

- [x] **v2.0.6: AI Encoder Options Layout & Updater Fix (2026-03-21)**
  - [x] Options box matches vertical height of Directories + Configuration columns.
  - [x] Fix overlapping dual-checkbox for "Delete Source on Success"; label on top, checkboxes right-aligned underneath.
  - [x] Fix updater button stuck on "CHECKING..."; use Qt Signal for thread-safe callback, add 15s watchdog.

- [x] **v2.0.5: Update & Restart Flow (2026-03-21)**
  - [x] Detect install method (git vs AUR).
  - [x] Windows: git pull, close, restart.
  - [x] Linux git: same flow.
  - [x] Arch AUR: paru/yay/pacman update, terminal for sudo.

- [x] **v2.0.4: AI Encoder Layout & Donate (2026-03-21)**
  - [x] Reorganize: Directories top, Configuration below, Options right (full height).
  - [x] Remove Metrics box; move CPU/GPU/RAM to footer (right-aligned, compact).
  - [x] Add "Buy me a coffee" donate button (PayPal $5 USD).

- [x] **v2.0.3: Layout Squish & Icon Fix (2026-03-21)**
  - [x] Squish top config boxes to content height (no vertical scaling).
  - [x] Make Console the only vertically scalable element.
  - [x] AI Scanner left unchanged.
  - [x] Linux icon: Install to hicolor (256x256, 48x48); add gtk-update-icon-cache post_install; pkgrel=2.

- [x] **v2.0.2: Code Audit Fixes (2026-03-21)**
  - [x] Fix `_job_speeds` list corruption in `AV1EncoderPanel` (QLabel overwritten with float).
  - [x] Fix `ModelManager` progress callback wrapper in `AIScannerPanel` for `Signal(str)` compatibility.
  - [x] Correct malformed docstrings (`""""` → `"""`) in UI modules and updater.
  - [x] Remove stray quote in `_on_telemetry` comment.
  - [x] Update `CHANGELOG.md`/`CONVERSATION_LOG.md`.

- [x] **v2.0.1: Migration Bug Fixes (2026-03-21)**
  - [x] Fix `ModelManager` path resolution for core modules.
  - [x] Correct `OrganizerEngine` progress callback signature.
  - [x] Fix engine control API mismatches (`cancel()` vs `stop()`).
  - [x] Prune heavy dependencies (`torch`, `torchvision`, `tqdm`) from `requirements.txt`.

- [x] **v2.0.0: PySide6 Migration (2026-03-21)**
  - [x] Port UI Layer to PySide6 with "Mass AV1 Encoder v12" aesthetic.
  - [x] Implement panel-based architecture using `QStackedWidget`.
  - [x] Rewrote headless updater for PySide6 integration.
  - [x] Deleted legacy CustomTkinter files and updated requirements.
  - [x] Initial v2.0.0 release on GitHub and AUR.

- [x] **v1.0.26: AV1 Tab Layout Optimization (2026-03-21)**
  - [x] Implement ultra-compact layout (strip ~150px).
  - [x] Move hints inline with checkboxes.
  - [x] Simplify ThreadSlot (remove VID/AUD info).

- [x] **v1.0.25: AV1 Tab UX Refinement (2026-03-21)**
  - [x] Implement high-density layout (strip <= 200px).
  - [x] Reduce checkbox sizes to 16x16px.
  - [x] Fix vertical overflow via grid weighting.

- [x] **v1.0.24: AV1 Tab UI Overhaul (2026-03-21)**
  - [x] Replace absolute positioning with frame rows for Browse buttons.
  - [x] Add "Optimize Audio" configuration and hints.
  - [x] Fix metrics loop capture bug.

- [x] **v1.0.23: Footprint Optimization (2026-03-21)**
  - [x] Move `python-opencv` to `optdepends` in `PKGBUILD` (saves 320MB).
  - [x] Implement runtime `OPENCV_AVAILABLE` check in `scanner.py`.

- [x] **v1.0.22: On-Demand Models Fix (2026-03-21)**
  - [x] Scrub binary models from repository (`git rm *.tflite *.onnx`).
  - [x] Add `.gitignore` to `src/core/models/`.

- [x] **v1.0.21: AUR Build Fix (2026-03-21)**
  - [x] Fix icon path mismatch in `PKGBUILD` (`src/assets` -> `src/ui/assets`).

- [x] **v1.0.20: Stability Hotfix & Asset Restoration (2026-03-21)**
  - [x] Fix startup crash (restore `__version__` in `version.py`).
  - [x] Fix asset paths (move to `src/ui/assets`) and update `app.py`.
  - [x] Fix malformed `.desktop` entry (remove redundant paths).
  - [x] Hardcode $5 USD donation links for PayPal and Venmo.
  - [x] Repair corrupted `CHANGELOG.md` formatting.

- [x] **v1.0.19: AV1 Encoder Power-User Features (2026-03-21)**
  - [x] Refactor top row into 4-column layout (Paths/Config/Options/Metrics).
  - [x] Implement Options: Shutdown, HW Accel, Skip Short, Delete Source.
  - [x] Implement Metrics: CPU, GPU, RAM polling.
  - [x] Implement Pause/Resume and Space Saved tracking.

- [x] **v1.0.18: UI Refinement & Layout Polish (2026-03-21)**
  - [x] Remove "Time to Archive!" catchline from log header.
  - [x] Relocate "Check for Updates" to global status footer.
  - [x] Implement custom split-aligned navbar (Media Organizer/Encoder/Scan Left, Donate Right).

- [x] **v1.0.17: Neon Green Branding & Layout (2026-03-21)**
  - [x] Update hourglass icon to Neon Green (Full-Bleed).
  - [x] Refine icon transparency and alpha edges.
  - [x] Align functional tabs to left, Donate to right as a tab.

- [x] **v1.0.16: GUI Fix & Icon Perfection (2026-03-21)**
  - [x] Fix `_tkinter.TclError`: Remove `width=100` from `pack()` in `av1_tab.py`.
  - [x] Refine Icon: Generate full-frame motif with rounded corners and zero padding.

- [x] **v1.0.15: Dependency & Icon Refinement (2026-03-21)**
  - [x] Fix AUR Dependency: Change `opencv` to `python-opencv` in `PKGBUILD`.
  - [x] Correct AUR Metadata: `pkgver=1.0.15` to trigger updates.
  - [x] Refine Icon: Pixel-perfect vertical scaling (256px height) and transparency.

- [x] **v1.0.14: Architecture & Branding Refresh (2026-03-21)**
  - [x] Fix Circular Import: Move constants to `ui.theme`.
  - [x] Refactor `ui.tabs.py` into `ui.tabs/__init__.py`.
  - [x] Refine Icon: Transparent background, maximized size within 256x256.

- [x] **v1.0.13: Brand Identity - Catchline (2026-03-21)**
  - [x] Integrate "Time to Archive!" into `app.py` UI (title and label).
  - [x] Update `README.md` with the new catchline.
  - [x] Update `PKGBUILD` and `.desktop` descriptions.

- [x] **v1.0.12: Premium Icon Branding (2026-03-21)**
  - [x] Research and generate a high-fidelity application icon.
  - [x] Convert generated asset to `icon.png` and `icon.ico`.
  - [x] Verify icon display in the `chronoarchiver.desktop` entry.

- [x] **v1.0.11: Linux Desktop Integration (2026-03-21)**
  - [x] Create `chronoarchiver.desktop` specification file.
  - [x] Update `PKGBUILD` to install desktop entry and application icon.
  - [x] Update version to 1.0.11 in `src/version.py`, `README.md`, and `CHANGELOG.md`.

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
  - [x] Release: Tag v1.0.4

- [x] **v1.0.3: Final Ship & Polish (2026-03-21)**
  - [x] Integrity: Fix `efficientdet_lite0.tflite` SHA-256 hash
  - [x] Cleanup: Remove stale comments in `tabs.py`
  - [x] Cleanup: Delete unused `use_gpu` in `tabs.py`
  - [x] Refactor: Move `hashlib` and `queue` imports to top level
  - [x] Release: v1.0.3

- [x] **v1.0.2: Regression Fixes & Refinement (2026-03-21)**
  - [x] Fix crash: `NameError: filename` in `av1_tab.py`
  - [x] Security: Update official face model hash
  - [x] UX: Fix swapped file counters in AI Scanner lists
  - [x] Cleanup: Remove redundant loops in `organizer.py`
  - [x] Consistency: Fix CRLF in `logger.py`
  - [x] Release: v1.0.2

- [x] **v1.0.1: Code Review & Stability Overhaul (2026-03-21)**
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
  - [x] **Verify & Final (1.0.1)**

- [x] **v1.0.0: Initial Release (2026-03-21)**
  - [x] Initialize project structure and artifacts
  - [x] Research source codebases
  - [x] Port `Media_Archive_Organizer` (Theme & Core)
  - [x] Port `Mass_AV1_Encoder` as a tab
  - [x] Implement LLM model check & download feature
  - [x] Verify merged application
