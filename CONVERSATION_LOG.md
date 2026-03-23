# CONVERSATION_LOG.md

---
## 2026-03-22 (Footer + Engine Status queue poll v3.2.19)
- Footer center and AI Scanner Engine Status stuck at "CHECKING…". Same root cause: QTimer.singleShot from worker thread unreliable.
- Fix: queue + main-thread poll for _refresh_footer and scanner _check_models. Engine Status labels all caps. SemVer: PATCH 3.2.19.

---
## 2026-03-22 (FFmpeg progress queue + footer caps v3.2.18)
- FFmpeg bar still stuck at 0%, "Checking..." in footer. QTimer.singleShot from worker thread unreliable for cross-thread UI updates.
- Fix: queue + main-thread QTimer poll (80ms) for FFmpeg progress, same pattern as updater. Worker puts (phase, pct, detail) in queue; poll timer drains and updates UI.
- Footer text: all caps (CHECKING…, FFMPEG, OPENCV, READY, IDLE) for visibility. SemVer: PATCH 3.2.18.

---
## 2026-03-22 (Startup hang during FFmpeg install v3.2.17)
- User: FFmpeg bar stuck at 0%, footer "Checking…", nothing moving, guide blinking. Log showed check_opencv_in_venv every ~500ms.
- Root cause: Scanner's _check_models ran at 500ms (QTimer), called check_opencv_in_venv (subprocess ~500ms) on main thread. Blocked event loop so FFmpeg progress callbacks never processed.
- Fix: (1) Defer scanner _check_models until step5 (prereqs done); app calls it explicitly. (2) _refresh_footer runs check_opencv_in_venv in thread, applies result via QTimer. (3) Scanner _check_models runs opencv check in thread, _apply on main thread. (4) _cached_cv_ok for _get_guide_target/_update_start_enabled. SemVer: PATCH 3.2.17.

---
## 2026-03-22 (OpenCV CUDA fix after restart v3.2.16)
- Continued OpenCV fix: cv2 import fails with libcufft/libcudnn when LD_LIBRARY_PATH not set.
- check_opencv_in_venv: call _add_nvidia_libs_to_ld_path() before subprocess; pass env=os.environ.copy() so child gets nvidia lib dirs.
- bootstrap.py: add_venv_to_path() before both execv calls so child process inherits LD_LIBRARY_PATH from start.
- Ensures footer/scanner show OpenCV ✓ after restart when CUDA wheel is installed. SemVer: PATCH 3.2.16.

---
## 2026-03-22 (FFmpeg footer download speed v3.2.15)
- User requested download speed next to FFmpeg progress bar in footer.
- ensure_ffmpeg_in_venv_with_progress(progress_callback) added: streams download in-process, computes bytes/sec, reports (phase, pct, detail) e.g. "2.3 MB/s". ensure_ffmpeg_in_venv delegates to it with None callback.
- app.py: _lbl_ffmpeg_speed QLabel next to _bar_ffmpeg; _install_ffmpeg_async uses new API and updates bar + speed. SemVer: PATCH 3.2.15.

---
## 2026-03-22 (GitPython for updater v3.2.14)
- Added GitPython to VENV_PACKAGES_BASE. _spawn_git_updater now runs a Python helper script that uses git.Repo().remotes.origin.pull() instead of shell + git pull. Removes system git dependency for git-clone updater. Fallback to subprocess git pull if ImportError. SemVer: PATCH 3.2.14.

---
## 2026-03-22 (FFmpeg venv auto-install v3.2.13)
- User requested FFmpeg in venv, auto-install when missing, tiny progress bar with % in left footer.
- Added static-ffmpeg to VENV_PACKAGES_BASE. check_ffmpeg_in_venv (crumb check), ensure_ffmpeg_in_venv (get_or_fetch in thread), add_ffmpeg_to_path (static_ffmpeg.add_paths).
- app.py: _bar_ffmpeg (72x12, % format) in status bar; _check_prereqs runs ensure in thread when FFmpeg missing, simulated progress 0→95→100, then add_ffmpeg_to_path.
- PKGBUILD: removed ffmpeg from depends. SemVer: PATCH 3.2.13.

---
## 2026-03-22 (nvidia-cufft in CUDA stack v3.2.12)
- Added nvidia-cufft to NVIDIA_CUDA_CUDNN_PIP_PACKAGES. OpenCV CUDA wheel requires libcufft.so.12; nvidia-cublas/cudnn did not provide it, causing cv2 import to fail after install/restart.
- Components list: nvidia-cufft (~25 MB) between cublas and cudnn. Uninstall list, scanner dialog, GPU_ACCELERATION.md updated. SemVer: PATCH 3.2.12.

---
## 2026-03-22 (RESTART button width + OpenCV libcufft + venv clean)
- RESTART button too wide: cut into Engine Status 1px border. Fix: setFixedWidth(90) when RESTART, 165 when Install OpenCV.
- After restart, OpenCV showed yellow dash and "Not installed" with red guide pulse. Debug log: check_opencv_in_venv returncode=1. Venv has opencv-contrib-python 4.13.0.90 + nvidia-*. Root cause: cv2 import fails with `ImportError: libcufft.so.12: cannot open shared object file`. CUDA OpenCV wheel requires libcufft.so.12; nvidia-cublas/cudnn do not provide it. Future fix: add nvidia-cufft-cu13 or switch to OpenCL build.
- Cleaned venv for next test: uninstall opencv, nvidia packages, remove nvidia/ from site-packages.

---
## 2026-03-22 (Green RESTART button after OpenCV install v3.2.10)
- User reported: Install OpenCV did not turn into green glowing RESTART button after successful install. cv2 import fails with libcufft.so.12, so check_opencv_in_venv stays False and _check_models kept showing "Install OpenCV".
- Fix: Add _opencv_just_installed flag. When install succeeds (ok=True), set flag before _check_models. In _check_models, when flag is True: show "Restart required", btn "RESTART" with green base style, guide pulse uses green glow (#34d399 border). _get_guide_target returns _btn_install_cv when flag set. _on_install_opencv: if flag, call restart_app() and QApplication.quit(). Added restart_app() to core/updater.py (spawns helper to relaunch after exit). Uninstall clears flag. SemVer: PATCH 3.2.10.
- Also cleaned venv for re-test per user request.

---
## 2026-03-22 (Signal type fix + intensive debug v3.2.9)
- Log showed install_opencv SUCCESS but popup DONE ok=False. Root cause: setup_complete = Signal(bool) but we emit (ok, err) tuple; type mismatch caused slot to receive wrong data.
- Fix: Signal(object) so we can emit (ok, err) or bool; uninstall venv-fail path now emits (False, msg).
- Added intensive debug: _task start/return/emit, _on_done RECV (type+value), check_opencv_in_venv result, _check_models cv_ok. SemVer: PATCH 3.2.9.

---
## 2026-03-22 (Wheel filename fix v3.2.8)
- Log error: "Invalid wheel filename (wrong number of parts): 'tmpza6jh2d2'". Pip expects PEP 427 names.
- _download_wheel_with_progress: save to tempdir with proper filename via _get_wheel_filename() (Content-Disposition or URL path). SemVer: PATCH 3.2.8.

---
## 2026-03-22 (Install debug logging + venv clean v3.2.7)
- Log analysis: CUDA wheel downloaded OK; pip install of wheel failed; OpenCL fallback also failed. Pip stderr was not in log.
- Added debug() throughout: install_opencv (each phase, pip stderr on fail), _install_cuda_cudnn_venv, uninstall_opencv, Model setup popup/download_models, OpenCV install popup completion.
- New constants: UTILITY_OPENCV_INSTALL, UTILITY_MODEL_SETUP. Model manager uses UTILITY_MODEL_SETUP.
- CUDA install progress: "Downloading ~750 MB (may take 2–5 min)..." so user knows step is active (not frozen).
- Cleaned venv: removed nvidia packages and leftover nvidia/ folder for re-test. SemVer: PATCH 3.2.7.

---
## 2026-03-22 (nvidia-cublas in CUDA stack v3.2.6)
- `NVIDIA_CUDA_CUDNN_PIP_PACKAGES`: added `nvidia-cublas` (explicit install + components list ~384 MB).
- Install dialog order: cuda-runtime, cublas, cudnn, opencv wheel. Scanner panel text updated.
- `docs/GPU_ACCELERATION.md`: venv pip stack documented. SemVer: PATCH 3.2.6.

---
## 2026-03-22 (CUDA/cuDNN venv-only, no sudo v3.2.5)
- Replaced system CUDA/cuDNN install (pacman + pkexec/sudo) with pip packages in app venv.
- `_install_cuda_cudnn_venv()`: pip install nvidia-cuda-runtime nvidia-cudnn-cu13 into venv. No sudo.
- `_is_cuda_cudnn_installed()`: checks `pip show nvidia-cudnn-cu13` in venv.
- Components: nvidia-cuda-runtime (~2.2 MB), nvidia-cudnn-cu13 (~366 MB), opencv wheel (~483 MB).
- `uninstall_opencv()`: also removes nvidia-cudnn-cu13, nvidia-cuda-runtime, nvidia-cublas.
- Scanner panel dialog: "CUDA runtime and cuDNN install via pip into venv (no sudo)". SemVer: PATCH 3.2.5.

---
## 2026-03-22 (CUDA/cuDNN auto-install v3.2.4)
- CUDA Toolkit and cuDNN added back to components list (~2.2 GB + ~314 MB).
- On Arch/Arch-based Linux with NVIDIA GPU, install_opencv now runs pacman -S cuda cudnn (via pkexec/sudo) before downloading the OpenCV wheel, if not already installed. Prompts for password.
- _is_cuda_cudnn_installed() checks ldconfig or pacman -Q. _install_cuda_cudnn_system() for Arch. SemVer: PATCH 3.2.4.

---
## 2026-03-22 (OpenCV progress UX v3.2.3)
- Download progress: show speed (MB/s) during download; throttle updates every 0.2s.
- At 100% download, phase changes to "Installing..." / "Setting up wheel (this may take a minute)" so UI doesn't appear frozen during pip install.
- Components dialog shows only what we download (~483 MB for CUDA wheel); matches actual download. SemVer: PATCH 3.2.3.

---
## 2026-03-22 (OpenCV install fix v3.2.2)
- CUDA components: removed CUDA Toolkit/cuDNN from download total (we don't download them). Dialog now shows only wheel ~483 MB.
- install_opencv returns (bool, str|None) for error propagation; pip stderr shown in console on failure.
- CUDA wheel failure fallback: if pip install fails for CUDA variant, automatically try OpenCL build. Note added to dialog: "Requires CUDA 13.1 and cuDNN 9.17.1 installed separately. If missing, install will try OpenCL build instead." SemVer: PATCH 3.2.2.

---
## 2026-03-22 (Remove Media Converter v3.2.1)
- Media Converter panel and engine removed; all related code stripped. SemVer: PATCH 3.2.1.

---
## 2026-03-22 (Media Converter, layout, CUDA components v3.2.0)
- **Install OpenCV layout**: Fixed Engine Status box stretch when Install button text changed. Button fixed width 165px, label always "Install OpenCV", variant in tooltip. Directories stretch 10→8, Engine Status 3→4; grp_mod setMinimumWidth(260).
- **CUDA components**: get_opencv_install_components for cuda variant now lists NVIDIA CUDA Toolkit (~3.5 GB), cuDNN (~800 MB), opencv-contrib-python (CUDA). Removed "Requires... install separately" message.
- **Media Converter**: New 4th panel. Source/target folders, output format (jpg/png/webp/bmp/tiff/mp4/webm/mkv/avi), Photos/Videos/Recursive, crop (x,y,w,h), scale (w×h or %), rotate (0/90/180/270°), transparency for PNG/WebP, quality. FFmpeg for video, PIL for images. Guide, console, START/STOP. SemVer: MINOR 3.2.0.

---
## 2026-03-21 (GPU-specific OpenCV variants v3.1.0)
- **OpenCV variant by GPU**: `detect_gpu()` extended to return `nvidia`|`amd`|`intel`|`''` (Intel via /sys/class/drm vendor 0x8086 or lspci). `get_opencv_variant()` returns `cuda`|`opencl_amd`|`opencl_intel`|`opencl`. Install flow uses variant: NVIDIA→cudawarped wheel; AMD/Intel/integrated→opencv-python (OpenCL, cv2.UMat). Labels: "OpenCV (CUDA)", "OpenCV (OpenCL — AMD Radeon)", "OpenCV (OpenCL — Intel)", "OpenCV (OpenCL)". Uninstall list includes opencv-openvino-contrib-python. Engine Status button shows "Install {variant}" when OpenCV missing. SemVer: MINOR 3.1.0.

---
## 2026-03-21 (OpenCV fixed progress bar v3.0.10)
- OpenCV install: download wheel with requests (stream), report downloaded/total bytes; fixed progress bar 0–100% based on size; detail shows "X.X / Y.Y MB". CUDA and standard paths both download wheel first, then pip install from file. Fallback to pip install when PyPI wheel URL unavailable.
- Install confirmation: added get_opencv_install_components(); dialog lists components (e.g. "opencv-contrib-python (CUDA, Linux): 482.7 MB"), total download, and CUDA/cuDNN requirement note. SemVer: PATCH 3.0.10.

---
## 2026-03-21 (OpenCV no auto-reinstall v3.0.9)
- Bootstrap used is_venv_ready() which required cv2; when user uninstalled OpenCV, is_venv_ready failed → ensure_venv ran → OpenCV reinstalled. Added is_venv_runnable() (PySide6, PIL, requests only); bootstrap uses it. Venv without OpenCV is now considered runnable; no ensure_venv, no reinstall. SemVer: PATCH 3.0.9.

---
## 2026-03-21 (Models UX, footer refresh v3.0.8)
- Models row: when missing, only Setup Models (like OpenCV). When installed, Uninstall Models. Renamed Remove Models → Uninstall Models.
- Footer: added prereqs_changed signal; scanner emits on OpenCV/models install/uninstall; app._refresh_footer() updates lbl_prereq. SemVer: PATCH 3.0.8.

---
## 2026-03-21 (OpenCV status, uninstall, layout v3.0.7)
- **Runtime OpenCV check**: Added `check_opencv_in_venv()` to venv_manager — runs venv python -c "import cv2" for current state. Scanner panel and footer now use this instead of import-time OPENCV_AVAILABLE. Fixes stale green checkmark when user manually uninstalled OpenCV; footer and Engine Status now reflect actual venv state.
- **Uninstall OpenCV**: Runs in background thread; UI refreshes immediately after; _check_models() uses runtime check so status updates without restart. Previously appeared to "do nothing" because OPENCV_AVAILABLE was cached and UI never refreshed.
- **Layout**: Options box stacked vertically (Recursive, Keep Animals, Conf %); Directories, Options, Engine Status all use same height (100px). SemVer: PATCH 3.0.7.

---
## 2026-03-21 (code audit fixes v3.0.6)
- **OpenCVSetupDialog thread-safety**: Progress callback previously updated Qt widgets from worker thread (undefined behavior). Added `phase_update` Signal to dialog; `_prog` now emits signal; slot updates labels on main thread.
- **venv_manager uninstall coverage**: Added `opencv-contrib-python-headless` to uninstall lists in `install_opencv` and `uninstall_opencv` so cudawarped CUDA wheel and headless variants are fully removed.
- **Error message**: "No Linux wheel" → "No matching CUDA wheel for this platform" for non-x86/ARM clarity.
- SemVer: PATCH 3.0.6.

---
## 2026-03-22 (revert food, GPU v3.0.5)
- Revert food detection: Keep People (default) + Keep Animals (checkbox). Food always to Move/others.
- venv_manager: detect_gpu(), get_opencv_package(); docs/GPU_ACCELERATION.md for CUDA build.

---
## 2026-03-22 (GPU metric v3.0.4)
- Footer: utilization.encoder → utilization.gpu so AI scan shows GPU usage.
- Scanner: _get_dnn_backend_target() tries CUDA, OpenCL, CPU; animal detector uses backend too.

---
## 2026-03-22 (scanner EXIF orientation v3.0.3)
- _apply_move_copy: use PIL ImageOps.exif_transpose for images; save right-side up when Move/Copy to target.
- Supported: jpg, jpeg, png, webp, tiff, bmp, heic; fallback to shutil for non-images.

---
## 2026-03-22 (scanner UX fixes v3.0.2)
- Progress bar: show %p% during scan; set "Scanning..." label; reset to Ready 2s after complete.
- Preview: separate _on_keep_selection_changed / _on_move_selection_changed; clear other list on select so Move preview works.
- Label: _lbl_move_copy updates with combo (Move/Copy (others)).

---
## 2026-03-22 (model download UX)
- At 99% for tar models, switch status to "Extracting... please wait..." so UI doesn't show 100% during extraction.

---
## 2026-03-21 (v3.0.0 audit + footer fix)
- Full code audit: import order, venv paths, Setup/Remove Models flow OK.
- Footer now uses OPENCV_AVAILABLE from core.scanner (single source of truth); removed redundant step3 cv2 import.
- Scanner message: "OpenCV (python-opencv) required" → "OpenCV required — click Setup Models".
- Model files: live in ~/.local/share/ChronoArchiver/models; venv in .../venv; no need to delete or re-download.
- Footer green when cv2 importable: with v3.0 bootstrap, ensure_venv installs opencv-python on first run.

---
## 2026-03-21 (v3.0.0 implemented)
- **Done**: Launcher runs bootstrap.py; PKGBUILD deps reduced to python+ffmpeg. Scanner Setup Models and Remove Models use venv_manager. App uses add_venv_to_path. Version check uses get_pip_exe() for opencv outdated. Bump 3.0.0.

---
## 2026-03-22 (v3.0.0 — Venv internalization, MAJOR)
- **Scope**: Run ChronoArchiver from app-private venv with all Python deps; no sudo required.
- **Plan**: (1) core/venv_manager.py — ensure_venv(), install_packages(), progress callback. (2) App startup: if venv exists, exec into venv python; if not, show SetupDialog, create venv, pip install all deps, exec. (3) Launcher runs app.py only. (4) Scanner Setup Models uses venv_manager. (5) PKGBUILD minimal deps: python, ffmpeg (venv has rest) or keep pyside6 for bootstrap UI. (6) SemVer: MAJOR 3.0.0 for architectural shift.
- **Other functions**: Model downloads use requests (in venv). Organizer/Encoder use piexif, PIL, ffmpeg (ffmpeg stays system). Only OpenCV needed venv before; now all Python deps in venv.

---
## 2026-03-22 (v2.0.62 OpenCV app-private venv, no sudo)
- On Linux when pip --user fails (externally-managed-environment): create venv at ~/.local/share/ChronoArchiver/venv, pip install opencv-python; app adds venv site-packages to sys.path at startup (app.py before imports).
- Remove Models: delete venv with shutil.rmtree; also pip uninstall for Windows.
- chronoarchiver.install docs: venv removed on uninstall. Bump 2.0.62.

---
## 2026-03-22 (v2.0.61 Setup Models OpenCV progress + Arch hint)
- Setup Models: pip runs with Popen, streams output to dialog (lbl_detail); indeterminate bar during OpenCV install.
- On externally-managed-environment (Arch): show "On Arch Linux run: sudo pacman -S python-opencv"; 3s delay before close.
- Log showed OpenCV pip failed with externally-managed-environment. Bump 2.0.61.

---
## 2026-03-22 (v2.0.60 Guide on Setup when OpenCV missing)
- Guide targets Setup Models when OpenCV missing (even if models installed); click installs OpenCV. Bump 2.0.60.

---
## 2026-03-22 (v2.0.59 Remove Models + Update! button)
- Engine Status: Remove Models button always visible; deletes model files, uninstalls opencv-python via pip; confirmation dialog.
- Update! button appears next to "All Models Ready!" only when _model_update_available or _opencv_update_available (from pre-check); version check extended to pip list --outdated for OpenCV.
- Signal version_check_done(bool, bool); box layout: label+Update row, Setup+Remove row; same _strip_h. Bump 2.0.59.

---
## 2026-03-22 (v2.0.58 Footer + Setup Models + Uninstall)
- Footer: OpenCV and AI Models as separate entries; OpenCV checks cv2 only; AI Models checks model_mgr.is_up_to_date(). Pre-check steps include "Checking AI Models…".
- Setup Models: When OPENCV_AVAILABLE is False, runs `pip install --user opencv-python` first, then downloads models; prompts restart; shows "Installing OpenCV..." in dialog.
- Uninstall: chronoarchiver.install comment documents clean removal (models, config, logs); OpenCV not auto-removed. Bump 2.0.58.

---
## 2026-03-22 (v2.0.57 AI Scanner OpenCV gate fix)
- Log showed "ERROR: OpenCV not installed" when running Start AI Scan; footer incorrectly displayed OpenCV ✓ when cv2 import failed but model files existed (`opencv_ok = opencv_ok or models_ready`).
- Fix: Footer OpenCV status reflects only cv2 import; removed `models_ready` override. Scanner panel gates START on OPENCV_AVAILABLE; shows "OpenCV (python-opencv) required" when cv2 unavailable; _get_guide_target returns None when OpenCV missing. Bump 2.0.57.

---
## 2026-03-22 (v2.0.49 AI Scanner Setup Models fix)
- Setup Models: was stuck (downloading, nothing happened). Root cause: QTimer.singleShot from daemon thread unreliable for main-thread callback.
- Fix: ModelSetupDialog popup with URL, model name, fixed progress bar; progress via Qt Signal (thread-safe); setup_complete Signal for _done.
- ModelManager: added approx_size, get_total_download_size, check_model_update_available; progress callback includes overall, label, url.
- Engine Status: yellow "Updated models available" when optional newer models; green "Models Ready"; red "AI Models Missing".
- Refresh _check_models on showEvent; docs/models_version.txt for version manifest. Bump 2.0.49.

---
## 2026-03-22 (v2.0.48 Hardening + 25–50 researched issues)
- Organizer: piexif + EXIF decode wrapped; date formats YYYY:MM:DD and YYYY-MM-DD; Exception/MemoryError; debug() not print.
- Model manager: HTTPS URL; timeout; content-length try/except; tar KeyError.
- Updater: no unlink before exec; GitHub retry 429/503; mkstemp fd close in finally.
- AV1 settings: UTF-8 encoding.
- App: webbrowser.open try/except.
- Encoder: Windows long-path (>200 chars) warning.
- docs/KNOWN_ISSUES_AND_MITIGATIONS.md added. Bump 2.0.48; push git + AUR.

---
## 2026-03-22 (v2.0.47 Config + edge-case hardening)
- AV1 settings: sanitize after JSON merge — concurrent_jobs → 1/2/4 (prevents 0 workers / stuck encode), quality 0–63, rejects bounded, existing_output/preset validated; debug log instead of print on load/save errors.
- Encoder: int() + clamp 1–8 for worker count; _on_jobs_changed index bounds.
- Scanner: progress emit min(1.0, c/max(t,1)).
- Updater: Accept application/vnd.github+json. Bump 2.0.47; push git + AUR.

---
## 2026-03-22 (v2.0.46 Minor robustness fixes)
- Updater: docstring (releases→tags); guard when API returns non-list JSON; log failures via debug instead of print.
- App: when update check fails (latest=None), show "UPDATE CHECK UNAVAILABLE" instead of "up to date".
- Encoder: wrap commonpath in try/except ValueError for Windows mixed-drive paths. Bump 2.0.46; push git + AUR.

---
## 2026-03-22 (v2.0.45 Update check fix)
- In-app update checker used releases/latest which 404s when no GitHub Releases exist (only tags pushed). AUR users on 2.0.43 saw "up to date" despite 2.0.44 on AUR. Switched to tags API: fetch tags, find max version by comparison. Bump 2.0.45; push git + AUR.

---
## 2026-03-22 (v2.0.44 Auto-stop + Source folder note)
- Encoder: auto-stop when batch complete — user had to click STOP to get final console message. Added batch_complete signal from worker's finally block; _on_batch_complete calls _finalize_batch_complete() to transition UI (idle, ENCODING COMPLETE). Removed duplicate scan_done signal in _Signals.
- Target Source folder: encoder never copies files or creates a Source folder. A Source folder in target was from pre-2.0.43 logic (relpath from user src included Source). v2.0.43 fix uses common parent of queued files, so output goes to target/2011-03/ etc. If user ran before and after fix, they may see both layouts (duplicates).
- Bump 2.0.44; push git + AUR.

---
## 2026-03-22 (v2.0.43 Encoder structure root fix)
- Encoder was creating a top-level "Source" folder inside the target when mirroring — the user selected a parent dir (e.g. test_video_files) and files lived under test_video_files/Source/2011-03/, so relpath from src included "Source".
- Fix: use the common parent of all queued file paths as the structure root instead of the user-selected source. So we mirror only meaningful subdirs (e.g. 2011-03), not wrapper folders like "Source". structure_root = os.path.commonpath([os.path.dirname(p) for p, _ in queue]). Pass structure_root to _job_worker; use it for relpath when maintain_structure.
- Bump 2.0.43; push git + AUR.

---
## 2026-03-22 (v2.0.42 Master bar + ETA on file complete)
- Master bar and ETA stayed at 0/54 and --:--:-- because _on_progress (FFmpeg time= parse) never fired for short encodes.
- Fix: update master bar + ETA in _on_encode_finished on every file completion.
- Added out_time_ms parsing fallback in engine.
- Bump 2.0.42; push git + AUR.

---
## 2026-03-22 (v2.0.41 AMD HW encode, Footer activity, Encoder fixes)
- AMD HW encoding: av1_vaapi (Linux), av1_amf (Windows) when CUDA unavailable.
- NVIDIA: -hwaccel_output_format cuda for full GPU pipeline.
- Footer: activity with animated dots (Encoding..., Organizing..., Scanning...); status_callback.
- Encoder: FFmpeg progress parse \\r, out_time=, -stats_period; I/O MB/s; ETA; master bar; fps/speed.
- Bump 2.0.41; push git + AUR.

---
## 2026-03-22 (v2.0.40 Browse-dst + Footer Colors)
- Encoder: _browse_dst blocked textChanged so _update_start_enabled never ran → START stayed disabled when target picked via Browse. Added _update_start_enabled() after setText.
- Footer: optional/skip now yellow (#eab308); green ✓ success, red ✗ failed.
- 2 log files: expected when app launched twice (one per session); prune keeps max 3.
- Bump 2.0.40; push git + AUR.

---
## 2026-03-22 (v2.0.39 Guide to START)
- Guide glow: when all inputs ready (src+target for encoder; path+exts for organizer; models+path for scanner), guide now pulses on START button as 3rd step instead of disappearing.
- All three panels: _get_guide_target returns _btn_start when can_start; _update_start_enabled no longer stops guide when ready; _clear_guide_glow + pulse handle START styling.
- Bump 2.0.39; push git + AUR.

---
## 2026-03-22 (v2.0.38 Log Fix)
- Single log file per session; prune after create to cap at 3 total in log folder.
- All entries identify internal app; av1_engine -> ChronoArchiver.Encoder, model_manager -> ChronoArchiver.Scanner.
- Bump 2.0.38; push git + AUR.

---
## 2026-03-22 (v2.0.35 Single Log)
- One log file: chronoarchiver_YYYY-MM-DD_HH-MM-SS.log at startup.
- Logger and debug_logger both write to same file; removed chronoarchiver.log.
- Log level DEBUG; added verbose logging (scan, encode, panel switch, pre-reqs).
- Bump 2.0.35; push git + AUR.

---
## 2026-03-22 (v2.0.34 Scanner Fix)
- Scanner: emit first 25 then every 100ms (was 10/50ms); remove processEvents.
- Engine: catch all Exception in getsize; os.walk onerror to skip bad dirs.
- Panel: try/except guards in _done; log scan errors to console.
- Bump 2.0.34; push git + AUR.

---
## 2026-03-22 (v2.0.33 Scan Bar)
- Scan dialog: restore setRange(0,0) indeterminate bar; emit for count<=10 or every 50ms; processEvents in update_progress.
- Bump 2.0.33; push git + AUR.

---
## 2026-03-22 (v2.0.32 Encoder Fixes)
- Don't save source/target folders; init with empty; blockSignals when Browse setText.
- Scan dialog: use scan_progress signal (thread-safe) instead of QTimer.singleShot; fix 0 files/0 B; static bar not indeterminate.
- Bump 2.0.32; push git + AUR.

---
## 2026-03-22 (v2.0.31 Scan on User Action Only)
- Removed QTimer.singleShot(300, _auto_scan) on init; scan dialog only when user selects source (Browse or text input).

---
## 2026-03-22 (v2.0.30 Encoder Scan Dialog)
- Auto-scan: separate ScanProgressDialog window with file count + total size; throttled updates; main bar untouched.
- Main bar: only for encoding (4 threads + total); set when Start clicked; reset to 0/0 when encoding complete.
- Bump 2.0.30; push git + AUR.

---
## 2026-03-22 (v2.0.29 Encoder UI)
- Directories: top margin 2->8 to align source input with Options.
- Configuration: addStretch + Expanding + rowStretch(1,1) to align bottom with Options.
- Progress bar: removed setRange(0,0) during auto-scan — keep static 0/0 Files until scan completes (no indeterminate animation when guide at first checkpoint).
- Bump 2.0.29; push git + AUR.

---
## 2026-03-21 (v2.0.28 Fail-safes)
- Media Organizer: disk space check (base_dir), writable check, overlap validation, permission handling, long path warning. disk_usage(base_dir) for target.
- AI Scanner: log corrupt images (cv2.imread None), PermissionError, skip >100MB images. Thread try/except in panel.
- Encoder: FFmpeg check at start, disk space check, existing output policy (overwrite/skip/rename), partial output cleanup on failure. Thread try/except in worker.
- Organizer/Scanner/Encoder panels: worker try/except with log_msg emit.
- Bump 2.0.28; push git + AUR.

---
## 2026-03-21 (v2.0.27 Unified Queue Strategy)
- All three apps: queue of (path, size), byte-weighted master progress.
- Organizer: pre-scan builds queue_list; progress_callback(bytes_done, total_bytes, files_done, total_files, filename).
- Scanner: all_files = [(path, size)]; _report_progress(bytes_done, total_bytes, ...).
- Encoder: already had (path, size) and byte-weighted progress.
- Bump 2.0.27; push git + AUR.

---
## 2026-03-21 (v2.0.26 Encoder Scan Before Guide)
- Encoder: guide stays on source Browse until scan completes; Work Progress shows "Scanning source..." + indeterminate bar; guide moves to target only after _apply_scan_result.
- Added _source_scanned, _is_scanning; _get_guide_target checks _source_scanned before advancing to target.
- Bump 2.0.26; push git + AUR.

---
## 2026-03-21 (v2.0.25 Layout Fixes)
- Encoder: source/target input boxes match width (min 150, max 600).
- AI Scanner: Setup Models glow no longer shifts "AI Models Missing"; guide buttons use border:2px solid transparent when idle.
- Bump 2.0.25; push git + AUR.

---
## 2026-03-21 (v2.0.24 Guide Glow on Buttons)
- Glow now targets the *buttons* user clicks (Browse, Setup Models, Photos checkbox) instead of input fields.
- Bump 2.0.24; push git + AUR.

---
## 2026-03-21 (v2.0.23 Guide Glow on Next-Missing Input)
- Pulsing red glow now targets the *input* that needs user attention, not the START button. Moves step-by-step: Organizer (source → media types → target), Encoder (source → target), Scanner (Setup Models → folder).
- Bump 2.0.23; push git + AUR.

---
## 2026-03-21 (v2.0.22 START Gates, Model Path, Download Progress)
- **Media Organizer**: START disabled until source path valid, at least one media type (Photos/Videos) or extensions override, target valid if specified. Wired _edit_path, _edit_target, _chk_photos, _chk_videos, _edit_exts to _update_start_enabled.
- **Mass AV1 Encoder**: START disabled until source and target directories both valid. Wired _edit_src, _edit_dst textChanged; _update_start_enabled in _apply_scan_result and _stop_encoding.
- **AI Media Scanner**: START requires valid folder AND ready models. _update_start_enabled checks both; wired _edit_path.textChanged. Folder check was previously missing.
- **Model storage**: Switched from install dir to `platformdirs.user_data_dir("ChronoArchiver","UnDadFeated")/models`. Fixes AUR permission (root-owned /usr/share). ScannerEngine accepts optional model_dir; scanner_panel passes it.
- **Download progress**: Model download now emits progress to Scanning Progress bar; status "Downloading..." during setup. Progress callback emits 0-1 for _bar.
- Bump 2.0.22; push git + AUR.

---
## 2026-03-21 (v2.0.19 Footer Restructure)
- Footer: Left = app activity (Idle, Encoding..., Organizing...); Center = pre-req status (FFmpeg ✓, OpenCV ✓, PySide6 ✓, Ready); Right = COPY CONSOLE, DEBUG, metrics. Pre-req check runs on 100ms timer. Bump 2.0.19.

---
## 2026-03-21 (v2.0.17 Code Audit)
- Full codebase audit: scanner face detection fixed (empty numpy array was treated as "has faces"); organizer indentation fix. No mutable defaults, no bare except, threads daemon. Bump 2.0.17.

---
## 2026-03-21 (v2.0.16 Dropdown Fix & Options Align)
- Preset/Threads dropdowns: Previous combo style (min-height 14px, max-height 16px) broke popup — rendered as massive overlay. Fixed with explicit QComboBox QAbstractItemView { min-height: 80px; max-height: 160px }; combo height 20px.
- Options box: Changed to QSizePolicy.Expanding + addStretch() so it fills height of Directories + Configuration. Bump 2.0.16.

---
## 2026-03-21 (v2.0.15 Config Dropdowns)
- Mass AV1 Encoder: Shrunk Preset/Threads combos vertically (FixedHeight 16px, min/max-height 14–16px, padding 0 3px). Horizontal sizing reverted to original. Directories + Configuration align with Options box.

---
## 2026-03-21 (v2.0.14 Cross-Platform)
- **scanner._get_model_path**: Was using 3x dirname + 'src/core/models', which broke AUR install (models at /usr/share/chronoarchiver/core/models). Fixed to 2x dirname (parent of core/) + 'core/models' — works for both source and AUR.
- **encoder_panel._open_logs**: Added Darwin support (macOS) via `open` command; wrapped in try/except for robustness. Matches app.py _open_debug_folder pattern.
- Verified updater (Windows batch vs Linux shell), shutdown commands, platformdirs, os.path usage. All cross-platform safe.
- Bump to 2.0.14; push git + AUR.

---
## 2026-03-21 (v2.0.8 Release)
- Debug logging: single file (`chronoarchiver_debug.log`), timestamps, utility name, rotation (3 files).
- Footer: COPY CONSOLE, DEBUG (opens debug folder).
- Media Organizer: target dir, extensions override, summary stats, ffprobe creation_time.
- Mass AV1 Encoder: queue preview, output format, CRF hints.
- AI Media Scanner: Keep/Move lists, Move Files, Keep Animals, confidence threshold, Export CSV.
- Panel renames: Mass AV1 Encoder, AI Media Scanner.
- Bump to 2.0.8; CHANGELOG, README, PKGBUILD updated.

---
## 2026-03-21 (v2.0.7 Release)
- Updater: queue + QTimer polling for main-thread delivery (Signal approach still stuck on some systems).
- Code cleanup pass: unused imports, dead code, bare except fixes, model hint correction.
- Bump to 2.0.7; push to GitHub and AUR.

---
## 2026-03-21 (v2.0.6 Release — GitHub + AUR)
- Pushed v2.0.6 to GitHub: encoder layout, Delete Source checkbox fix, updater button fix.
- Tagged v2.0.6, pushed to origin.
- AUR: Bumped PKGBUILD to 2.0.6, regenerated .SRCINFO, pushed to aur.archlinux.org.

---
## 2026-03-21 (AI Encoder Options Layout v2.0.6)
- Options box: Changed `QSizePolicy.Maximum` to `QSizePolicy.Expanding` so it matches the combined vertical height of Directories + Configuration.
- Delete Source on Success: Fixed overlapping dual checkboxes. Moved label to top line; placed both checkboxes on second line, right-aligned. Added bottom stretch to keep content at top when Options box expands.
- Bumped to v2.0.6 (PATCH for UI polish).

---
## 2026-03-21 (AUR Push v2.0.5)
- Cloned AUR repo (`ssh://aur@aur.archlinux.org/chronoarchiver.git`), copied PKGBUILD and chronoarchiver.install, regenerated .SRCINFO with makepkg, committed and pushed.
- AUR package updated from v2.0.4 to v2.0.5.

---
## 2026-03-21 (Updater: Perform Update & Restart)
- **v2.0.5**: Implemented full update-and-restart flow.
- Detects install method: git (Windows/Linux) or AUR (Arch). Spawns detached helper that waits for app exit, runs update, restarts app.
- Windows: batch script with git pull, then start new process.
- Linux git: shell script with sleep 2, git pull, exec.
- Arch AUR: paru/yay -Syu chronoarchiver or pkexec pacman; uses gnome-terminal/konsole/xterm when available for interactive sudo.

---
## 2026-03-21 01:35 PM
- **UI Refinement & Metrics Relocation (v2.0.4)**:
    - Reorganized AI Encoder panel using `QGridLayout` for better space utilization.
    - Moved system metrics (CPU/GPU/RAM) from a dedicated box to the global status bar.
    - Added "Buy me a coffee" donation button to the navigation bar.
    - Synchronized v2.0.4 to GitHub and AUR.

## 2026-03-21 (AI Encoder Layout & Donate)
- **v2.0.4**: Reorganized AI Encoder config per user request.
- Layout: Directories top-left, Configuration bottom-left, Options right (spanning both rows). Removed Metrics box.
- Metrics (CPU, GPU, RAM) moved to global footer, right-aligned, labels + % only. Visible when on AI Encoder panel.
- Added "☕ Buy me a coffee" donate button in nav bar; links to PayPal $5 USD (jscheema@gmail.com, en_US).

---
## 2026-03-21 (Icon Fix for Arch/CachyOS)
- **Linux icon not updating**: User reported old purple icon (from 1.0.0) still showing after reinstall on CachyOS.
- Root cause: PKGBUILD only installed to `/usr/share/pixmaps/`. Modern DEs (GNOME/KDE) prefer `/usr/share/icons/hicolor/<size>/apps/` and may cache aggressively.
- Fix: Install icon to hicolor 256x256 and 48x48; add `chronoarchiver.install` with post_install hook running `gtk-update-icon-cache`; bump pkgrel to 2.

---
## 2026-03-21 01:10 PM
- **UI Layout Refinement (v2.0.3)**: Optimized vertical space usage in Organizer and Encoder panels.
- Applied `QSizePolicy.Maximum` to configuration group boxes to prevent vertical scaling.
- Configured consoles to expand and fill all remaining window space (`root.addWidget(grp_log, 1)`).
- Synchronized v2.0.3 to GitHub and AUR.

## 2026-03-21 (Layout Squish)
- **v2.0.3**: Vertically squished Media Organizer and AI Encoder panels per user screenshots.
- Media Organizer: Removed `addStretch` from Options and Execution Mode; set `QSizePolicy.Maximum` on vertical axis for all three top group boxes and the progress group; removed fixed height from Console; gave Console stretch factor 1.
- AI Encoder: Same approach—removed stretches from Configuration/Options; set `QSizePolicy.Maximum` on all four top boxes and Work Progress; removed fixed height from Console; Console gets stretch 1.
- AI Scanner left unchanged (sample photo scaling use case).

---
## 2026-03-21 (Scan & Fix)
- **Code audit fixes (v2.0.2)**: Scanned codebase for errors and applied targeted fixes.
- Fixed `encoder_panel.py`: `self._job_speeds[job_id] = p.speed` was overwriting QLabel widget references with floats, corrupting the list and causing subsequent `.setText()` calls to fail.
- Fixed `scanner_panel.py`: `ModelManager.download_models` expects `progress_callback(downloaded, total_size, filename)` but was passed `log_msg.emit` which expects a single string; added wrapper to format progress for log.
- Corrected malformed docstrings (`""""` instead of `"""`) in `app.py`, `scanner_panel.py`, `organizer_panel.py`, `encoder_panel.py`, `updater.py`.
- Removed stray quote in `_on_telemetry` comment.
- Bumped version to 2.0.2 (PATCH).

---
## 2026-03-21 12:55 PM
- **Migration Bug Fixes (v2.0.1)**: Addressed critical feedback on the PySide6 port.
- Fixed `ModelManager` initialization with absolute path resolution.
- Corrected callback signatures for `OrganizerEngine` and `ScannerEngine`.
- Streamlined `requirements.txt` (removed AI training dependencies like `torch`).
- Synchronized v2.0.1 to GitHub and the AUR with tags.

## 2026-03-21 12:40 PM
- **PySide6 Migration (v2.0.0)**: Completed the full architectural shift from CustomTkinter to PySide6.
- Implemented a panel-based UI with `QStackedWidget` for Media Organizer, AI Encoder, and AI Scanner.
- Replicated the high-density "Mass AV1 Encoder v12" visual style using custom QSS.
- Rewrote `updater.py` as a headless/callback-based component for UI independence.
- Ported `MediaOrganizerPanel` autonomously to resolve a duplicate content issue in the migration source.
- Removed all legacy CustomTkinter components and updated `requirements.txt`.
- Bumped project version to v2.0.0.

## 2026-03-21 05:50 AM
- **AUR Stability Fix (v1.0.21)**: Resolved a critical build failure in the AUR by correcting the icon path in `PKGBUILD`. Bumped version to 1.0.21.

## 2026-03-21 05:45 AM
---
## 2026-03-21 05:07 AM
Major UI Modernization and Feature Parity Update (v1.0.17).
- Renamed "Archival Core" to "Media Organizer" and "Transcoding Dashboard" to "Mass AI Encoder".
- Reordered tabs: Media Organizer, Mass AI Encoder, AI Scan, Donate.
- Implemented global status footer with Left/Center/Right alignment for app status and background tracking.
- Ported advanced multi-threaded job slots from Mass AV1 Encoder into the encoder tab.
- Added stacked Vid/Aud codec info, real-time speeds, ETA calculation, and a running timer.
- Re-generated the application icon: vibrant neon green hourglass, "full-bleed" vertical fit, with 10% rounded corners and alpha transparency.
- Synchronized v1.0.17 globally to GitHub and the AUR.
## 2026-03-21 04:14 AM
Integrated official brand catchline: "Time to Archive!".
- Updated `app.py` window title and added a specialized branding label.
- Synchronized catchline across `README.md`, `PKGBUILD`, and `chronoarchiver.desktop`.
- Bumped version to v1.0.13.
## 2026-03-21 04:12 AM
Finalized Git and AUR Release Synchronization for v1.0.12.
- Synchronized all `v1.0.11` (Launcher) and `v1.0.12` (Branding) changes to GitHub.
- Tagged `v1.0.12` and pushed to `origin/main`.
- Successfully pushed the updated `PKGBUILD` and `.SRCINFO` to the AUR repository (`ssh://aur@aur.archlinux.org/chronoarchiver.git`).
- Project is now globally available and branded.
## 2026-03-21 04:06 AM
User requested a dedicated application icon.
- Designing a premium branding suite for ChronoArchiver.
- Generating a 256x256 high-resolution icon representing Time and Archiving.
- Bumping version to v1.0.12 to accommodate the new asset release.
## 2026-03-21 04:05 AM
Identified missing application launcher entry on Linux/AUR.
- Resolved "Missing Desktop Entry" issue by generating `chronoarchiver.desktop`.
- Updated `PKGBUILD` to include installation of the desktop file to `/usr/share/applications` and the icon to `/usr/share/pixmaps`.
- Bumped version to v1.0.11.
## 2026-03-21 03:51 AM
Completed v1.0.10 Polish Release.
- Audited the `tarfile.extract()` routine to include Python 3.12+'s deprecation-silencing `filter='data'` parameter.
- Removed dead branch logic surrounding the SSD MobileNet frozen graph paths in `scanner.py`.
- Refined `ModelManager` to correctly log "Extracting..." when extracting payload tarballs rather than incorrectly mirroring `.pb` download strings.
## 2026-03-21 03:45 AM
Completed v1.0.9 release.
- Replaced outdated `MediaArchiveOrganizer` repository references with `ChronoArchiver` in `updater.py`.
- Added a `winfo_exists` safeguard before executing `dialog.destroy()` in the model download thread to prevent random `TclError`s.
- Switched the animal detection engine from a quantized TFLite model (which caused a C++ `UINT8` parsing crash in OpenCV) to the standard float32 COCO Frozen Graph (`frozen_inference_graph.pb` and `.pbtxt`).
- Implemented `.tar.gz` on-the-fly model extraction in `ModelManager`.

---
## 2026-03-21 03:32 AM
Completed v1.0.8 Hotfix.
- Fixed `_detect_animal` parsing to handle the 4 tensors (boxes, class_ids, scores, num_dets) from the TF Task Library SSD model.
- Fixed post-download freeze by executing `self._init_model_check` in a background thread.

---
## 2026-03-21 03:30 AM
Completed v1.0.7 "Logic Hardening & UX".
- Replaced EfficientDet with SSD MobileNet V1 for accurate animal detection.
- Implemented `ModelDownloadDialog` for professional download progress tracking.
- Threaded `_init_model_check` to eliminate startup UI freezing.
- Tagged v1.0.7 and updated AUR.

---
## 2026-03-21 03:00 AM
Completed v1.0.6 "Architectural Optimization".
- Replaced MediaPipe with OpenCV DNN for the AI Scanner.
- Transitioned to manual model downloads.
- Cleaned up unused dependencies.
- Tagged v1.0.6 and updated AUR.

---
## 2026-03-21 02:54 AM
Final README badge refinement: Swapped AUR badge for Platforms (Windows | Linux).
---
<HISTORY_RESERVED_DO_NOT_REMOVE>
---
## 2026-03-21 02:52 AM
Completed v1.0.5 "Stable Release".
- Resolved primary "Publish Blocker": Synchronized README version badge to 1.0.5.
- Implemented "Immediate Cancellation" in AV1 Encoder: Real-time ffmpeg termination via `active_worker_engines` set and `worker_lock`.
- Verified `ModelManager` SHA-256 integrity check on launch.
- Synchronized GitHub tags and AUR package.
- Project is now logically and technically complete.
---
## 2026-03-21 02:52 AM
Completed v1.0.5 "Stable Release".
- Resolved primary "Publish Blocker": Synchronized README version badge to 1.0.5.
- Implemented "Immediate Cancellation" in AV1 Encoder: Real-time ffmpeg termination via `active_worker_engines` set and `worker_lock`.
- Verified `ModelManager` SHA-256 integrity check on launch.
- Synchronized GitHub tags and AUR package.
- Project is now logically and technically complete.
---
## 2026-03-21 01:50 AM
Initializing ChronoArchiver V1.0. Starting a new journey by merging Media Archive Organizer and Mass AV1 Encoder.
