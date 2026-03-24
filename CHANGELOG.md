# Changelog

## [3.8.0] - 2026-03-24
### Added
- **Windows setup**: Right-hand **Setup output** pane streams **pip** and **FFmpeg** subprocess lines live; when detailed install logging is enabled, the same lines are prefixed with `[setup-output]` in `ChronoArchiver_installer.log`.
- **`core/subprocess_tee`**: Optional tee of pip/FFmpeg lines to the app UI; **Windows** `CREATE_NO_WINDOW` on venv subprocesses to stop brief **console flashes** (including `nvidia-smi` in the footer metrics loop).
- **Media Organizer / AI Scanner consoles**: Subprocess output from first-run FFmpeg/pip and from **AI Scanner** pip work (OpenCV install, `pip list --outdated`) is shown in the **Organizer** console on startup (`organizer` channel) and in the **Scanner** console when those operations run with the `scanner` channel.

### Changed
- Semver **3.8.0** (installers, PKGBUILD, PyPI metadata).
- **Windows setup — Setup output pane**: Each line is prefixed with **`[HH:MM:SS]`**; the view **autoscrolls** while you are at the bottom and stops jumping if you scroll up to read history.
- **Mass AV1 Encoder — Directories**: Source/target paths use a **grid** so both **Browse** buttons share one column (aligned with each other and vertically centered to the line edits). **Guide pulse** styles use the same fixed **min/max width and height** as idle so the highlight does not reflow the row.
- **AI Media Scanner — command strip**: **Directories**, **Options**, and **Engine Status** use a **shorter fixed height**, **tighter bottom margins**, and **no bottom stretch** in Options. **Engine Status** actions (**Install/Uninstall OpenCV**, **Setup Models**, **Update!**, **Uninstall Models**) are **smaller** (narrower/shorter, 7px label font) with **fixed QSS boxes** so **guide pulse** does not shift layout; **Browse** uses the same fixed-box pattern.

## [3.7.11] - 2026-03-24
### Added
- **Windows / macOS — FFmpeg during setup**: After `pip` completes, the installer downloads **static-ffmpeg** binaries (same mechanism as the app) so first launch does not open the FFmpeg pre-req dialog. **Quick-launch** (when source already matches the setup version) also ensures FFmpeg before starting the app.
- **Component manifest**: `docs/components_manifest.json` on `main` defines `ffmpeg_revision`; the app and installer compare it to `Settings/ffmpeg_revision.txt` and only re-fetch FFmpeg when the published revision increases (no redundant re-download on every app update). Offline installs seed revision `1` when FFmpeg is already present.
- **Updates**: After a successful GitHub connectivity check from the in-app updater, setup-type installs refresh bundled FFmpeg when the manifest revision changes.

### Changed
- **Windows / macOS setup**: Optional `ChronoArchiver_installer.log` **appends** each run (session separator + header) instead of replacing the file, so troubleshooting history is preserved.
- **Windows / macOS setup**: Welcome screen shows the **hourglass logo** (PNG, ~half the README inline width, proportional) above the title; setup window uses bundled **icon.ico** / **icon.png** for the taskbar/dock when available.

### Fixed
- **Setup — FFmpeg skipped on fresh install**: FFmpeg fetch now runs **inside** `_run_setup_bootstrap` (after pip and import verification) for both the full install and the “sync existing venv” path, so the PyInstaller setup exe always installs FFmpeg even if its bundled `task()` UI step is stale. Log lines: `bootstrap: FFmpeg (static-ffmpeg) starting` / `bootstrap: FFmpeg OK` or `FFmpeg FAILED`.
- **Windows — Installed Apps uninstall**: Uninstaller script **`Uninstall_ChronoArchiver.cmd`**; **`UninstallString`** via **`winreg`**; **`%SystemRoot%\System32\cmd.exe`** in the command line. On **every** setup run (including **quick-launch** when source already matches), the installer **deletes then recreates** `HKCU\…\Uninstall\ChronoArchiver` so Settings → Apps is not left with a stale entry after reinstall. Uninstaller **terminates** `pythonw.exe` / `python.exe` processes whose **command line** includes the install path before deleting folders. Uninstall removes install dir, **UnDadFeated** models path, shortcuts, Start Menu folder, then registry. **GitHub Actions**: existing **release** for that tag is **deleted** before upload to avoid stale assets.

## [3.7.10] - 2026-03-24
### Changed
- **UI**: Application uses the Fusion style for consistent themed controls on all platforms.
- **UI — Media Organizer**: Path fields fixed to 28px height with spacing between rows; Browse buttons use fixed size policy so they stay aligned with line edits; Folder structure / Action / Dup dropdown label and text sizes increased slightly; Photos and Videos checkboxes no longer use a bordered frame; global checkbox indicator styling improves checked-state contrast (teal fill vs grey-on-blue).
- **UI — Mass AV1 Encoder**: Source and target directory rows use matching fixed line-edit height and vertical spacing between rows; Browse buttons no longer stretch taller than their row.
- **UI — AI Media Scanner**: Library path row vertically centers line edit and Browse; confidence label text slightly larger; confidence spin box widened so the “%” suffix is not clipped.

## [3.7.9] - 2026-03-24
### Changed
- **Windows / macOS setup (bootstrap)**: Updates no longer delete the entire install directory. The source zip is **merged** over the existing tree: `venv/` is never removed, and files whose size already matches the archive entry are **not rewritten** (faster re-runs and upgrades).
- **Setup**: If `src/version.py`, `chronoarchiver.pyw`, and `requirements.txt` already match this setup’s version, the **source zip is not downloaded** again.
- **Setup**: When a working venv already exists, setup runs **`pip install -r requirements.txt`** so new or changed dependencies are applied; it no longer exits early without syncing after an app upgrade.
- **Mass AV1 Encoder settings**: `av1_config.json` now lives under `<install root>/Settings` for setup-installed Windows/macOS (next to `Logs`, `src`, `venv`), instead of a nested `%LOCALAPPDATA%\\ChronoArchiver\\ChronoArchiver` folder. Other installs use `user_config_dir` with no duplicate app segment. Existing files are migrated once from the legacy path.

### Fixed
- **Windows in-app update**: Replaced invalid `subprocess.CREATE_NEW_PROCESS` with `CREATE_NEW_PROCESS_GROUP` when spawning the post-exit installer helper (Python has no `CREATE_NEW_PROCESS`). Same correction for git-update and setup launcher app spawn. If installer spawn fails, the app no longer quits immediately after the error dialog.
- **Setup quick-launch**: Running the setup exe no longer skips install/update when `version.txt` matches the bundle but `src/version.py` is still older (e.g. stuck on 3.7.7). Quick-launch now requires the same checks as “skip source zip” (`src/version.py`, launcher, `requirements.txt`).
- **Setup merge extract**: Skips overwriting a file only when **MD5 matches** the zip entry, not merely the same file size (so e.g. `3.7.7` → `3.7.9` in `src/version.py` always refreshes). Clears `src/**/__pycache__` after extract to avoid stale bytecode.
- **Setup UX**: Welcome screen before install; optional **detailed install log** (`ChronoArchiver_installer.log`, off by default) written next to the setup executable for debugging.
- **Setup install log**: Full GitHub asset URL; download traceback on failure; full `pip install -r` / per-package pip tails on failure; venv create stderr; import-verify output; **`INSTALLER RESULT: SUCCESS|FAILURE`** footer with reason for quick tail checks.

### Added
- **GitHub Actions**: Manual **Run workflow** on `release-installers.yml` to rebuild Windows/macOS setup artifacts for a chosen version (e.g. `3.7.9`) and upload them to the matching release tag.

### Note
- The **in-app updater** still downloads the small **Setup** executable (~6 MB) for each upgrade; that is separate from the large **source** zip, which setup now reuses or merges as above.

## [3.7.8] - 2026-03-24
### Changed
- **UI**: Taller path rows and Browse buttons (28px, 60px wide) aligned across Media Organizer, Mass AV1 Encoder, and AI Media Scanner; checkbox and option labels slightly larger; scanner Engine Status buttons match Browse height.
- **Header / footer**: Update status and donate link use 9px; footer bar taller with vertically centered content and slightly larger prerequisite and metrics text; global `QCheckBox` stylesheet at 9px.
- **Donate**: Link text is now “Support development of our products” with a heart (♥) prefix; PayPal tooltip unchanged.
- **Guide pulse**: Border-only highlight strings updated for new control metrics so layout does not shift.

### Fixed
- **Mass AV1 Encoder**: “Delete source on success” uses two full-width labeled checkboxes and a word-wrapped hint so controls no longer overlap the Options panel edge.
- **Mass AV1 Encoder**: Removed redundant **LOGS** button (footer **DEBUG** opens the log folder).

## [3.7.7] - 2026-03-24
### Changed
- **README**: Uninstall instructions updated for Windows Installed Apps and macOS `Uninstall ChronoArchiver.app`; troubleshooting log paths clarified for setup vs source installs.
- **Windows Installed Apps**: Registry uninstall entry now includes `InstallDate` (`YYYYMMDD`) for clearer listing in Settings.

## [3.7.6] - 2026-03-24
### Fixed
- **Windows setup init.tcl error**: PyInstaller spec collects tkinter Tcl/Tk data via `collect_all("tkinter")` so bundled setup exe finds init.tcl.
- **numpy ModuleNotFoundError**: Added numpy to requirements.txt and VENV_PACKAGES_BASE; is_venv_runnable verifies numpy.
- **Setup creates shortcut before deps installed**: Setup now installs all packages with per-package progress, verifies imports, and only creates shortcuts after success.
- **Windows Python detection**: Setup now detects Python via `py -3.13/-3.12/-3.11` launcher in addition to `python/python3`, so installs succeed when Python is installed but not on PATH.
- **Setup failure diagnostics**: Error popup now includes the actual failing stage/message instead of a generic failure.
- **Windows console popup after install**: App launch now uses venv `pythonw.exe` path to avoid leftover black console window.
- **Logs path for installer users**: Logs now live under install root (`ChronoArchiver/Logs`) instead of publisher-based user log path.

### Changed
- **Setup installs all deps during setup**: Pip install moved from deferred "first-time setup" to setup.exe. Installer shows determinate progress bar, %, download speed, and component checklist. No second setup window on first launch.
- **Bootstrap progress**: First-time setup (fallback) uses determinate progress bar with package X of N.
- **Installer UX**: Added dual progress bars (current component + overall) and a live component checklist (download, extract, env, deps, verify, shortcuts).
- **Windows launcher/uninstall flow**: Removed `.vbs` launcher path; shortcuts point directly to `pythonw.exe` + launcher script. Added OS-native uninstall registration in Windows Installed Apps (HKCU).
- **macOS uninstall UX**: Added `Uninstall ChronoArchiver.app` in install root alongside command-based uninstaller.

### Fixed
- **Windows setup crash dialog**: `tk.messagebox` attribute error fixed by importing and using `from tkinter import messagebox` in setup launcher and bootstrap error popup paths.

## [3.7.2] - 2026-03-24
### Fixed
- **Windows .pyw silent launch**: Launcher now calls `bootstrap.main()` (was never invoked). Bootstrap uses setup UI on Windows/macOS instead of headless-only (DISPLAY check). Errors shown via MessageBox when running under pythonw (no console).

### Changed
- **Install path simplified**: Windows `%LOCALAPPDATA%\ChronoArchiver\app` → `%LOCALAPPDATA%\ChronoArchiver`. macOS `~/Library/Application Support/ChronoArchiver/app` → `~/Library/Application Support/ChronoArchiver`. No nested `app` or `ChronoArchiver` subfolders.

## [3.7.1] - 2026-03-24
### Changed
- **Windows**: Desktop shortcut (no command prompt); launcher.vbs runs pythonw from app venv; Uninstall ChronoArchiver.vbs with confirmation dialog.
- **Setup**: Creates venv during install so shortcut uses app-internal pythonw; fallback to system pythonw if venv creation fails.
- **macOS**: Launcher prefers venv/bin/python; fallback to python3/python.

## [3.7.0] - 2026-03-24
### Changed
- **Python-based install**: Windows and macOS setup no longer install compiled binaries. App runs as `.pyw` via `pythonw`, eliminating 3–4 minute startup delays caused by PyInstaller extraction on Windows.
- **Setup payload**: Downloads `ChronoArchiver-{ver}-src.zip` (Python source); creates venv on first run. Fast startup; venv lives in install dir for clean uninstall.
- **Uninstallers**: Windows: "Uninstall ChronoArchiver.bat" in Start Menu. macOS: "Uninstall ChronoArchiver.command" in app bundle.

### Removed
- PyInstaller full-app build (`chronoarchiver.spec`), Inno Setup (`ChronoArchiver.iss`). Setup launcher (~6MB) retained.

## [3.6.0] - 2026-03-23
### Added
- **Small setup launcher (~6MB)**: Windows and macOS installers are now minimal bootstrap executables. On first run, a progress window downloads the full app (component name, download speed MB/s, % progress bar), extracts it, then launches. Subsequent runs start instantly.

### Changed
- **Release format**: `ChronoArchiver-Setup-3.6.0-win64.exe` (small) and `ChronoArchiver-Setup-3.6.0-mac64.zip` replace the previous 70MB+ installers. Full app zips are downloaded on demand.
- **In-app updater**: Fetches the setup launcher; running it performs the update.

## [3.5.6] - 2026-03-23
### Fixed
- **Windows crash on launch**: QSS f-string parsed CSS braces as Python expressions (`NameError: name 'border' is not defined`). Switched to `.format()` with escaped braces.

### Changed
- **README**: Added Troubleshooting section (first-startup delay, debug log paths).

## [3.5.5] - 2026-03-23
### Added
- **In-app installer updates (Windows & macOS)**: Frozen .exe/.app can now update without visiting the Releases page. Download progress popup (file, size, MB/s), then app quits, runs installer, restarts. FFmpeg-style UX.

### Changed
- **UI alignment**: Input bars and Browse buttons unified across all three panels (24px height, 56×24px buttons). Organizer, Encoder, Scanner now consistent.
- **Guide pulse**: Blinking red guide no longer warps layout; uses consistent border colors instead of transparent/red toggle.

### Fixed
- **Inno Setup**: `CloseApplications` for clean in-place upgrades when running installer over existing install.

## [3.5.4] - 2026-03-24
### Added
- **Single-instance lock**: Only one ChronoArchiver instance can run; second launch shows a message and exits.
- **Prerequisites popup**: FFmpeg download moved to manual popup. App boots immediately; user clicks "Download" when ready. Progress bar shows % and MB/s (OpenCV-style).
- **Bundled Inter font**: Packed for consistent rendering on Windows. Windows font stack: Segoe UI, Consolas.

### Changed
- **Boot speed**: No more auto-download blocking startup. GUI shows instantly; pre-req popup lets user download when ready.
- **Fonts**: Platform-specific stacks for readability (Segoe UI/Consolas on Windows).

## [3.5.3] - 2026-03-24
### Fixed
- **Mass AV1 Encoder**: On FFmpeg return codes 183 or 218 (hw decode failure, input issues), retry once with software decode. Common when source/target on NAS. Log FFmpeg stderr on failure. Console hint when both paths on network.

## [3.5.2] - 2026-03-24
### Fixed
- **Windows uninstaller**: Add `[UninstallDelete]` to remove entire install dir, including runtime-created `static_ffmpeg` files (win32.zip, bin/win32/).

## [3.5.1] - 2026-03-24
### Fixed
- **PyInstaller / Windows & macOS**: Frozen app failed on launch (`runpy` could not load `__main__` from bundled `app.py`). Bootstrap now resolves `src/ui/app.py` under `sys._MEIPASS` and loads the GUI with `importlib` so the installed `.exe` / `.app` starts correctly.

### Changed
- **UI**: Browse buttons unified to 48×22 px (AI Scanner reference) on Media Organizer and Mass AV1 Encoder. Encoder directory rows use full horizontal stretch (no max-width cap), 6 px spacing, line edits aligned with Organizer styling.
- **Console**: Shared `PANEL_CONSOLE_TEXTEDIT_STYLE` on all three internal apps for consistent monospace and colors with Organizer.

## [3.5.0] - 2026-03-24
### Added
- **Professional installers**: Windows x64 (Inno Setup) and macOS (DMG) installers built via GitHub Actions on release tag push. User-selectable install path. Artifacts: `ChronoArchiver-3.5.0-win64.exe`, `ChronoArchiver-3.5.0-mac64.dmg` on Releases page.

### Changed
- **Milestone release**: Cross-platform audit (Windows, Linux, Arch, macOS). README refreshed: encoding backends (NVENC, VAAPI, AMF, SVT-AV1), I/O throughput, uninstall paths for all platforms. All modules verified; no breaking changes.

## [3.3.31] - 2026-03-24
### Fixed
- **Mass AV1 Encoder Work Progress**: I/O throughput now updates in telemetry poll so it stays current even when ffmpeg progress callbacks are sparse.

## [3.3.30] - 2026-03-24
### Changed
- **Console (all panels)**: Path separators (/, \\) bright pink instead of gray.

## [3.3.29] - 2026-03-24
### Fixed
- **Updater changelog popup**: Show changelog newest-first (top-down), matching CHANGELOG.md format.

## [3.3.28] - 2026-03-24
### Changed
- **Main window**: Use green hourglass app icon in window title bar instead of default placeholder.

## [3.3.27] - 2026-03-24
### Changed
- **Console (all panels)**: Inside quoted paths, path separators (`/`, `\\`) and folder segments use distinct colors; file basename and extension stay bright white. Shared `console_style._quoted_path_content_to_html`.

## [3.3.26] - 2026-03-24
### Fixed
- **AUR updater**: App now restarts after update. Use `/usr/bin/chronoarchiver` absolute path; sleep 3s before script exit so app can connect to display before terminal closes (removed parent-kill logic).

## [3.3.25] - 2026-03-24
### Changed
- **Console (all panels)**: Token-level HTML coloring for improved readability. Filenames and paths (inside quotes) always bright white (#f8f8f2). Tags: [DRY RUN] amber, [MOVE]/[COPY]/[LINK] green, [SKIP]/[DUPLICATE] purple, [RENAME FIX] pink. Arrows (->) cyan, quotes muted. Replaced QListWidget with QTextEdit for rich formatting. Dracula-inspired palette; consistent across Organizer, Encoder, Scanner.

## [3.3.24] - 2026-03-24
### Fixed
- **AUR updater**: App now restarts after update. Use `setsid` + `disown` for robust detach; increase kill delay to 2.5s so app can connect to display before terminal closes.

### Changed
- **Console (all panels)**: Bright white base text (#e5e7eb); semantic coloring: errors red, warnings amber, success/done green, action tags ([MOVE], [COPY]) green, skip/duplicate slate, scanning/starting blue. Shared `console_style.py` helper.

## [3.3.23] - 2026-03-24
### Changed
- **Code audit**: Ruff + Bandit. Fixed unused imports/vars; MD5 usedforsecurity=False for dedup; pyproject.toml ruff config; nosec for updater chmod/urlopen.

## [3.3.22] - 2026-03-23
### Changed
- **Update changelog popup**: Shows all changelog entries since current version (e.g. v3.3.19 through v3.3.21 if updating from 3.3.18). Text area has fixed max height with scrolling.

## [3.3.21] - 2026-03-23
### Changed
- **Update flow**: When user clicks the blinking update button, show a popup with the new version's changelog; user must acknowledge before the update process (terminal/bash) starts.

## [3.3.20] - 2026-03-23
### Changed
- **Media Organizer**: Rename on collision now uses _1, _2, … instead of timestamp suffix.

## [3.3.19] - 2026-03-23
### Changed
- **Media Organizer**: Duplicate policy split into "Overwrite if same name" (replace any) and "Overwrite if same name+size" (replace only when size matches, else rename). Execution Mode box widened to 260px.

## [3.3.18] - 2026-03-23
### Fixed
- **AUR updater**: Auto-close terminal on success using a safer approach — kills only the script's parent shell ($PPID) via a detached background job, avoiding the previous grandparent kill that may have caused instability.

## [3.3.17] - 2026-03-23
### Changed
- **Media Organizer**: "Organize:" label; Photos/Videos row right-aligned in Paths box.

## [3.3.16] - 2026-03-23
### Changed
- **Media Organizer**: Swapped rows — "Date from EXIF/ffprobe" hint now above; "Content to organize:" label + Photos/Videos checkboxes below.

## [3.3.15] - 2026-03-23
### Fixed
- **AUR updater**: Removed terminal kill after update — was potentially causing system instability on CachyOS. Terminal now stays open with "Update complete. Press Enter." On failure, still shows "Update failed. Press Enter."
- **Debug logging**: Update flow (initiated, spawn, quit) logged to debug file for post-crash diagnosis.

## [3.3.14] - 2026-03-23
### Changed
- **Media Organizer**: Execution Mode box shrunk horizontally (max 220px). Paths box stretches to fill; Source and Target inputs matched width with aligned Browse buttons. Photos/Videos moved below Target row, right aligned.

## [3.3.13] - 2026-03-23
### Fixed
- **AUR updater**: Only close terminal when update succeeds; on failure show message and wait for Enter so user sees error. Add 0.5s delay before close.

## [3.3.12] - 2026-03-23
### Fixed
- **AUR updater**: Explicitly close terminal after update when launched from one; fixes console staying open on CachyOS/gnome-terminal.

## [3.3.11] - 2026-03-23
### Fixed
- **Multi-GPU**: nvidia-smi parsing uses first line only; fixes 0% display on multi-GPU systems.
- **FFmpeg install lock**: On lock timeout, return False instead of proceeding; only release lock when acquired.
- **Venv pip install**: On timeout, kill process and return False; avoid orphan pip processes.
- **Scanner**: Handle grayscale images (convert to BGR); add null check in face detection; remove dead no-op block.
- **Model download**: Use requests context manager for proper connection cleanup.
- **av1_engine**: Catch OSError instead of Exception for getsize failures.
- **Scanner copy/move**: Add .gif, .heif to IMAGE_EXTS for EXIF correction.
- **Footer metrics**: Restore right-aligned position; text aligned right within label.

## [3.3.10] - 2026-03-23
### Fixed
- **AUR updater**: Launch app in background with nohup and exit script so the terminal closes after update; no longer leaves console open.
- **Update button**: Flash green text when update available (like guide pulse).

## [3.3.9] - 2026-03-22
### Fixed
- **Footer metrics**: Moved CPU/GPU/RAM to left (no extra gap). Use monospace font so 1/10/100% changes do not cause bounce.

## [3.3.8] - 2026-03-22
### Changed
- **Media Organizer**: Merged Directories and Options into a single Paths box. Source/Target rows with Photos/Videos checkboxes inline. Consistent Browse button size (52×22). Reduced vertical padding and removed stretch waste.

## [3.3.7] - 2026-03-22
### Fixed
- **AUR updater**: Use `-Sy` instead of `-Syu` so only chronoarchiver is updated; avoids full system upgrade and unrelated package conflicts (e.g. vlc-plugin-lua).

## [3.3.6] - 2026-03-22
### Removed
- **Media Organizer**: Export Log button (use Copy Console in footer instead).
- **Media Organizer**: Extensions input — Photos/Videos checkboxes now process all supported extensions automatically (PHOTO_EXTS: jpg, png, heic, raw, etc.; VIDEO_EXTS: mp4, mov, mkv, etc.).
- **Media Organizer**: Exclude dirs input — .trash, @Recently Deleted, .thumbnails, etc. excluded by default.
- **Media Organizer**: Sidecars checkbox — sidecars no longer moved with main files.

### Changed
- **Media Organizer**: Photos and Videos checkboxes stacked vertically; Directories group extends to fill available space.

## [3.3.5] - 2026-03-22
### Added
- **Media Organizer**: Action (Move/Copy/Symlink); Move sidecars (.xmp, .xml, .aae, .json); Exclude dirs (comma-separated + default .trash, @Recently Deleted, etc.); Duplicate policy (Rename/Skip/Keep newer/Overwrite if same); Export Log button.
- **Date resolution**: Stream-level FFprobe creation_time fallback for videos; parent folder date fallback (YYYY-MM-DD in dir name).
### Fixed
- **Guide glow**: All panels use `border:2px solid` (transparent/colored) and consistent min-height so pulsing does not warp text or change button sizes.

## [3.3.4] - 2026-03-22
### Added
- **Media Organizer**: Folder structure dropdown with four options: YYYY/YYYY-MM (nested), YYYY-MM (flat month), YYYY-MM-DD (flat day), YYYY/YYYY-MM/YYYY-MM-DD (nested by day).
### Changed
- **Date resolution**: Videos now prefer FFprobe `creation_time` before filename (container metadata often more accurate). Images unchanged: EXIF → filename → mtime.
- **Minimum year**: Rejected dates changed from before 1980 to before 1957 (first digital photo).

## [3.3.3] - 2026-03-21
### Added
- **AI Scanner list cap**: When Keep or Others list reaches 100,000 entries, a dialog asks whether to raise the cap for this session. User can enter a higher value; cap reverts to 100,000 on next app start.

## [3.3.2] - 2026-03-21
### Security
- **Organizer**: Reject path-traversal filenames (`..`, absolute paths); validate resolved target stays under base directory.
- **Encoder**: Validate output path under destination when mirroring structure; reject `relpath` results containing `..`.
- **Updater**: Reject `src_dir` containing quotes or newlines to avoid shell script injection.
### Fixed
- **Shutdown on finish**: Replace `os.system("shutdown ...")` with `subprocess.run()` to avoid shell injection.
### Changed
- **Organizer/Scanner**: Validate empty or whitespace-only source/directory paths; normalize target_dir.
- **AI Scanner**: Cap `keep_list` and `others_list` at 100,000 entries to prevent unbounded memory on very large scans.

## [3.3.1] - 2026-03-23
### Fixed
- **Metrics display**: Reserve 3-digit width for CPU, GPU, RAM (e.g. `  5%`, ` 99%`, `100%`) to prevent layout bounce when values change.
- **AV1 Encoder scan**: Clamp total_bytes to non-negative; throttle progress updates (every 25 files or 150ms) to avoid negative/messed size display when scanning very fast.

## [3.3.0] - 2026-03-23
### Added
- **AI Scanner: YOLOv8-nano** — Replaced SSD MobileNet V1 with YOLOv8-nano ONNX for person and animal detection. Better accuracy, smaller download (~12 MB vs ~76 MB). Detects full-body person (COCO class 0) and animals (15–24).
### Removed
- **AI Scanner: SSD MobileNet** — Removed ssd_mobilenet_v1_coco.pb and .pbtxt. Run Setup Models to download YOLOv8.

## [3.2.25] - 2026-03-23
### Fixed
- **model_manager**: Initialize `dl_dest` before try and use explicit `is not None` check for cleanup on exception.
- **bootstrap**: Catch `OSError` around `os.execv` and exit with message instead of crash.
- **organizer**: Use `os.path.normcase` for source/target path comparison (Windows case-insensitivity).
### Changed
- **venv_manager**: Simplify `get_opencv_package`; remove redundant `shutil` import in `remove_venv`.
- **av1_engine**: Remove dead `vf_before` block.
- **app.py**: Update docstring.

## [3.2.24] - 2026-03-23
### Changed
- **AUR package**: Install CHANGELOG.md to `/usr/share/doc/chronoarchiver/` so users can read release notes locally.

## [3.2.23] - 2026-03-23
### Fixed
- **Model setup size estimate**: SSD model `approx_size` was ~30 MB (extracted .pb) but the actual download is the tar.gz (~73 MB). Updated to 76.5 MB so the "Approximate download size" dialog matches reality.

## [3.2.22] - 2026-03-23
### Fixed
- **Model download log spam**: Progress callback logged every 8KB chunk (~9,500 lines for 76MB model). Now logs only when percentage changes (0–100), reducing log size from ~880KB to ~1KB for model downloads.

## [3.2.21] - 2026-03-23
### Changed
- **OpenCV no longer auto-installed at startup**: Bootstrap/ensure_venv uses `skip_opencv=True`. User installs OpenCV via Install OpenCV button in AI Scanner module.
- **Engine Status buttons**: All buttons (Install/Uninstall OpenCV, Setup/Uninstall Models, Update!) use fixed width 100px. Guide glow no longer changes button size or shifts layout — pulse uses same font-size (7px) and all buttons have `border:2px solid` (transparent or colored).

## [3.2.20] - 2026-03-22
### Changed
- **AI Scanner Engine Status**: Install OpenCV button width reduced (165px → 100px). Fixed layout shift when guide pulse blinks — status labels have min-width, buttons use consistent 2px border (transparent/colored).

## [3.2.19] - 2026-03-22
### Fixed
- **Footer "CHECKING…" stuck**: `_refresh_footer` and scanner `_check_models` now use queue + main-thread poll (same pattern as FFmpeg) instead of `QTimer.singleShot` from worker thread. Center footer and Engine Status (OpenCV, Models) now update correctly.
### Changed
- **AI Scanner Engine Status**: Labels use all caps (CHECKING…, READY, MISSING, NOT INSTALLED, RESTART REQUIRED) for visibility.

## [3.2.18] - 2026-03-22
### Fixed
- **FFmpeg progress bar stuck at 0%**: Switched from `QTimer.singleShot` (worker thread) to queue + main-thread poll (80ms), matching updater pattern. Progress updates now reliably reach the UI.
- **Footer "CHECKING…" stuck**: Same fix — queue-based delivery ensures completion callback is processed.
### Changed
- **Footer text**: All caps (CHECKING…, FFMPEG, OPENCV, AI MODELS, READY, IDLE, etc.) for better visibility.

## [3.2.17] - 2026-03-22
### Fixed
- **Startup hang during FFmpeg install**: Scanner panel's `_check_models` (which called `check_opencv_in_venv` and blocked ~500ms) ran at 500ms via timer, blocking the main thread and preventing FFmpeg progress callbacks from running. Deferred until prereqs complete; `check_opencv_in_venv` now runs off main thread in both footer refresh and scanner status.
- **Footer "Checking…" stuck**: Same root cause — main thread blocked by OpenCV subprocess, so FFmpeg progress and footer update never processed.

## [3.2.16] - 2026-03-22
### Fixed
- **OpenCV CUDA import after restart**: `check_opencv_in_venv` subprocess now receives `LD_LIBRARY_PATH` with nvidia lib dirs (cu13, cudnn) so cv2 import succeeds. Bootstrap calls `add_venv_to_path()` before execv so child process starts with correct library path.

## [3.2.15] - 2026-03-22
### Added
- **FFmpeg download speed**: Download speed (e.g. "2.3 MB/s") shown next to the footer progress bar during FFmpeg install. Uses in-process streaming fetch with real progress and speed calculation.

## [3.2.14] - 2026-03-22
### Changed
- **Updater**: Git pull now uses GitPython (from venv) instead of system git. Removes system git dependency for git-clone installs when updating in-app. Falls back to system git if GitPython unavailable.

## [3.2.13] - 2026-03-22
### Added
- **FFmpeg in venv**: FFmpeg and ffprobe are now provided by `static-ffmpeg` in the app venv. Auto-installed on first run when missing. Always uses venv FFmpeg; system FFmpeg is ignored.
- **FFmpeg install progress**: Tiny left-aligned progress bar with % in the footer during FFmpeg download.
### Changed
- **PKGBUILD**: Removed `ffmpeg` from depends; app bundles FFmpeg via static-ffmpeg in venv.

## [3.2.12] - 2026-03-22
### Fixed
- **OpenCV CUDA libcufft.so.12**: Added `nvidia-cufft` to the CUDA stack so cv2 imports successfully after install and restart. Resolves "Not installed" and yellow OpenCV status when CUDA wheel was installed but libcufft was missing.
### Changed
- CUDA install components: nvidia-cufft (cuFFT) now included; install dialog and docs updated.

## [3.2.11] - 2026-03-22
### Fixed
- **RESTART button overflow**: RESTART button width reduced to 90px (from 165px) so it no longer clips into the Engine Status border. Install OpenCV keeps 165px width.

## [3.2.10] - 2026-03-22
### Added
- **Restart after OpenCV install**: When OpenCV install succeeds, the Install button becomes a green glowing "RESTART" button. Clicking it relaunches ChronoArchiver so the new installation takes effect. New `restart_app()` in `core/updater.py` spawns a helper to relaunch after exit.
### Fixed
- **Install OpenCV button state**: After successful install, the button no longer remains "Install OpenCV"; it now shows "Restart required" with a prominent RESTART action.

## [3.2.9] - 2026-03-22
### Fixed
- **OpenCV install success not reported**: Signal was `Signal(bool)` but we emitted `(ok, err)` tuple. Changed to `Signal(object)` so the slot receives the tuple correctly; install success is now reported properly.
### Changed
- **Debug logging**: More intensive logging for install flow (task start/return/emit, slot receive, check_opencv_in_venv result).

## [3.2.8] - 2026-03-22
### Fixed
- **OpenCV wheel install**: Pip requires PEP 427 wheel filenames. Downloads now save wheels with the correct name (from Content-Disposition or URL) instead of `tmpXXX.whl`, fixing "Invalid wheel filename (wrong number of parts)".

## [3.2.7] - 2026-03-22
### Added
- **Debug logging for installs and scans**: All OpenCV install phases, Model setup, and pip errors are now written to the debug log file. Enables diagnosing failures (e.g. pip stderr) when installs fail.
### Changed
- **CUDA install UX**: Progress text now shows "Downloading ~750 MB (may take 2–5 min)..." during nvidia pip install to indicate the step is active.

## [3.2.6] - 2026-03-22
### Changed
- **OpenCV CUDA install components**: `nvidia-cublas` is listed in the confirmation dialog and installed explicitly with `nvidia-cuda-runtime` and `nvidia-cudnn-cu13` into the app venv (total size estimate includes cuBLAS).

## [3.2.5] - 2026-03-22
### Changed
- **OpenCV CUDA: venv-only install (no sudo)**: CUDA runtime and cuDNN are now installed via pip packages (`nvidia-cuda-runtime`, `nvidia-cudnn-cu13`) into the app venv. Removed pacman/pkexec/sudo; all CUDA stack installs app-internally without elevated privileges.

## [3.2.4] - 2026-03-22
### Added
- **OpenCV CUDA: CUDA Toolkit and cuDNN**: For NVIDIA GPU on Arch Linux, CUDA and cuDNN are now installed automatically via `pacman -S cuda cudnn` before the OpenCV wheel. Components list shows all three (CUDA ~2.2 GB, cuDNN ~314 MB, OpenCV wheel ~483 MB). Prompts for password via pkexec/sudo.

## [3.2.3] - 2026-03-22
### Changed
- **OpenCV install progress**: Download speed (MB/s) shown during download. At 100% download, phase changes to "Installing..." with "Setting up wheel (this may take a minute)" so UI indicates activity during pip install.

## [3.2.2] - 2026-03-22
### Fixed
- **OpenCV CUDA install**: Components list now shows only the actual download (~483 MB wheel), not CUDA/cuDNN (which are system packages). Progress bar matches real download size.
- **OpenCV install failure**: Pip error output is now shown in the console when install fails.
- **CUDA wheel fallback**: If CUDA wheel fails (e.g. missing CUDA 13.1/cuDNN 9.17.1), installer automatically falls back to OpenCL build.

## [3.2.1] - 2026-03-22
### Removed
- **Media Converter**: Tool removed; code stripped.

## [3.2.0] - 2026-03-22
### Changed
- **AI Scanner – Engine Status layout**: Fixed Install OpenCV button causing box stretch. Button uses fixed width; variant shown in tooltip. Directories box yields horizontal space to Engine Status.
- **OpenCV CUDA install**: CUDA Toolkit (~3.5 GB) and cuDNN (~800 MB) now listed as required components with sizes; removed redundant "install separately" message.

## [3.1.0] - 2026-03-21
### Added
- **GPU-specific OpenCV install**: Install flow now selects OpenCV variant based on detected GPU:
  - **NVIDIA**: CUDA wheel (cudawarped/opencv-contrib-python); requires CUDA/cuDNN.
  - **AMD Radeon**: opencv-python with OpenCL (cv2.UMat, ROCm-compatible).
  - **Intel Xe/Arc/Integrated**: opencv-python with OpenCL.
  - **No discrete GPU**: opencv-python with OpenCL (universal).
- **Engine Status**: Install button label reflects variant (e.g. "Install OpenCV (CUDA)", "Install OpenCV (OpenCL — AMD Radeon)").

### Changed
- `detect_gpu()` now returns `nvidia`|`amd`|`intel`|`''`; Intel detection via DRM vendor and lspci.
- `get_opencv_install_components()` and `install_opencv()` use variant parameter instead of use_cuda.

## [3.0.10] - 2026-03-21
### Changed
- **OpenCV install progress**: Progress bar is now a fixed (determinate) bar driven by download size. Wheel is downloaded with streaming, then installed locally. Shows MB downloaded / total.
- **OpenCV install confirmation**: Dialog now lists each component with its size and shows total download size before install. For CUDA: shows wheel name and size; adds note about CUDA/cuDNN requirement.

## [3.0.9] - 2026-03-21
### Fixed
- **OpenCV no longer auto-reinstalled**: Bootstrap now uses `is_venv_runnable()` (PySide6, PIL, requests only) instead of `is_venv_ready()` (which required OpenCV). When the user uninstalls OpenCV and restarts, the app launches without reinstalling OpenCV.

## [3.0.8] - 2026-03-21
### Changed
- **AI Scanner – Models row**: When models are not installed, only "Setup Models" is shown (like Install OpenCV). When installed, "Uninstall Models" is shown instead. Update! appears only when models are ready and an update is available.
- **Footer refresh**: Footer (OpenCV, AI Models status) now refreshes immediately when OpenCV or models are installed or uninstalled, without restart.

## [3.0.7] - 2026-03-21
### Fixed
- **OpenCV status accuracy**: Footer and AI Scanner Engine Status now use a runtime check (`check_opencv_in_venv`) instead of import-time detection. Fixes incorrect green checkmark when OpenCV was manually uninstalled from the venv.
- **Uninstall OpenCV**: Uninstall now runs in a background thread and the UI updates immediately after completion without requiring a restart.
### Changed
- **AI Scanner layout**: Options (Recursive, Keep Animals, Conf %) are stacked vertically; Directories, Options, and Engine Status boxes share the same height.

## [3.0.6] - 2026-03-21
### Fixed
- **AI Media Scanner – OpenCV Setup**: Progress dialog updates now use Qt signals instead of direct widget access from the install worker thread, preventing potential crashes or undefined behavior.
- **OpenCV uninstall**: Added `opencv-contrib-python-headless` to the uninstall list so cudawarped CUDA wheel and headless variants are fully removed.
- **venv_manager**: Improved error message when no matching CUDA wheel exists for the platform.

## [3.0.5] - 2026-03-22
### Added
- **GPU detection**: venv_manager detects NVIDIA/AMD; docs/GPU_ACCELERATION.md for CUDA build-from-source.

## [3.0.4] - 2026-03-22
### Fixed
- **Footer GPU metric**: Switched from `utilization.encoder` (NVENC only) to `utilization.gpu` so GPU usage is shown during AI scan and other GPU compute, not just video encoding.
- **AI Scanner**: Backend selection now tries CUDA → OpenCL → CPU; animal detector also uses preferred GPU backend when available.

## [3.0.3] - 2026-03-22
### Added
- **AI Media Scanner**: When Move/Copy files to target (START), photos are now EXIF orientation–corrected so sideways/upside-down images are saved right-side up.

## [3.0.2] - 2026-03-22
### Fixed
- **AI Media Scanner**: Progress bar now shows percentage during scan instead of "Ready"; resets to "Ready" 2s after scan complete.
- **AI Media Scanner**: Preview pane now updates correctly when clicking files in Move list (clears Keep selection so Move selection is shown).
- **AI Media Scanner**: Results label updates with dropdown: "Move (others)" or "Copy (others)" based on Move/Copy selection.

## [3.0.1] - 2026-03-22
### Fixed
- **AI Model Setup**: At 99% download for tar archives, status switches to "Extracting... please wait..." instead of remaining at "100%" during extraction (~20s).

## [3.0.0] - 2026-03-21
### Changed (Breaking)
- **App-private venv (MAJOR)**: ChronoArchiver now runs all Python dependencies from an internal venv at `~/.local/share/ChronoArchiver/venv` (or `%LOCALAPPDATA%\ChronoArchiver\venv` on Windows). First launch runs bootstrap to create the venv and install PySide6, psutil, requests, Pillow, platformdirs, opencv-python, piexif. No sudo or system pip required.
- **Launcher**: Entry point is `bootstrap.py` (creates venv on first run, then execs into main app).
- **PKGBUILD**: Minimal dependencies—`python` and `ffmpeg` only. All Python packages (PySide6, opencv-python, etc.) come from the app venv.
- **Setup Models**: Uses `venv_manager` for OpenCV install; if venv missing, runs full `ensure_venv()` to create and populate it.
- **Remove Models**: Deletes the entire app venv; ChronoArchiver re-runs first-time setup on next launch.
### Added
- `src/core/venv_manager.py`: Centralized venv creation, `install_package()`, `ensure_venv()`, `remove_venv()`, `add_venv_to_path()`.
- `src/bootstrap.py`: First-run setup with tkinter UI (or headless), then exec into venv python.

## [2.0.62] - 2026-03-22
### Changed
- **Setup Models – OpenCV on Linux**: When `pip --user` fails with externally-managed-environment (e.g. Arch), create an app-private venv at `~/.local/share/ChronoArchiver/venv` and install opencv-python there (no sudo). App adds venv site-packages to sys.path at startup.
- **Remove Models**: Deletes app-private venv; also runs `pip uninstall` for Windows/user installs.
### Fixed
- OpenCV install without sudo on Linux (Arch, etc.).

## [2.0.61] - 2026-03-22
### Fixed
- **Setup Models – OpenCV install**: Show pip output live in the setup dialog (indeterminate bar + line-by-line progress); on `externally-managed-environment` (Arch etc.), show "On Arch Linux run: sudo pacman -S python-opencv"; 3s pause so user can read the error before dialog closes.

## [2.0.60] - 2026-03-22
### Changed
- **AI Media Scanner**: Guide now targets Setup Models when OpenCV is missing (even if models are installed); clicking it installs OpenCV via pip.

## [2.0.59] - 2026-03-22
### Added
- **AI Media Scanner – Engine Status**: Remove Models button (always visible) to delete all model files and uninstall OpenCV; Update! button appears next to "All Models Ready!" only when OpenCV or AI Models update is detected during pre-check.

## [2.0.58] - 2026-03-22
### Changed
- **Footer pre-reqs**: Separate OpenCV and AI Models — OpenCV reflects cv2 import only; new AI Models entry shows model files status; both use ✓/—.
- **Setup Models**: Installs OpenCV (opencv-python via pip) when missing, then downloads models; prompts restart after OpenCV install.
### Fixed
- **Uninstall**: chronoarchiver.install documents that models/config/logs are removed; OpenCV is not auto-removed (may be used by other apps).

## [2.0.57] - 2026-03-22
### Fixed
- **AI Media Scanner**: Correct OpenCV gate — footer no longer shows OpenCV ✓ when only model files exist; START disabled and "OpenCV (python-opencv) required" shown when cv2 import fails; prevents misleading "ERROR: OpenCV not installed" after clicking Start AI Scan.

## [2.0.56] - 2026-03-22
### Changed
- **AI Media Scanner**: Results row — Target folder input, Move/Copy dropdown, START button (green when target set); smaller console; guide flow includes Browse Target and START move/copy.

## [2.0.55] - 2026-03-22
### Changed
- **Footer pre-reqs**: OpenCV shows green ✓ when cv2 imports OR when AI models are ready (same check as scanner).
- **AI Scanner**: "Models Ready" → "All Models Ready!"

## [2.0.54] - 2026-03-22
### Fixed
- **Footer pre-reqs**: OpenCV check uses direct `import cv2` at display time with broad exception handling; green ✓ when import succeeds.

## [2.0.53] - 2026-03-22
### Fixed
- **Footer pre-reqs**: OpenCV now shows green ✓ when installed; uses scanner's OPENCV_AVAILABLE flag for consistent detection.

## [2.0.52] - 2026-03-22
### Fixed
- **Model setup**: Progress updates only in the setup popup dialog, not the main panel's scanning bar.
- **Model setup**: Show "Installing models... please wait..." during tar extraction and hash verification to avoid appearing frozen.

## [2.0.51] - 2026-03-22
### Changed
- **Startup footer**: Left status shows pre-check steps (Checking FFmpeg…, Checking OpenCV…, Checking PySide6…) before Idle; displays "Pre-check complete" for 3 seconds, then switches to Idle.

## [2.0.50] - 2026-03-22
### Fixed
- **AI Media Scanner models**: Face model URL switched from GitHub (404, Git LFS) to Hugging Face; animal model URL switched from download.tensorflow.org (SSL cert issue) to storage.googleapis.com mirror. All model URLs verified.

## [2.0.49] - 2026-03-22
### Fixed
- **AI Media Scanner – Setup Models**: Setup now opens a dedicated popup dialog showing download URL, current model, and fixed progress bar (pre-calculated from known sizes). Fixes issue where clicking Setup Models showed "Downloading" but nothing happened.
- **AI Media Scanner**: All models (Face YuNet, Animals & Objects SSD, Config) download in one batch; models detected on next app launch.
### Added
- **AI Media Scanner**: Model version check — Engine Status shows "Updated models available" in yellow when newer models exist (optional).
- **AI Media Scanner**: Refresh model check when panel becomes visible.
- **docs/models_version.txt**: Version manifest for model update detection.
- **Uninstall**: AUR package `post_remove` hook deletes all user data (models, config, logs) for a clean uninstall; README documents paths for source-install removal.

## [2.0.48] - 2026-03-22
### Fixed
- **Organizer**: EXIF handling — piexif load/decode wrapped; support both `YYYY:MM:DD` and `YYYY-MM-DD`; handle ValueError, TypeError, MemoryError; use debug() instead of print.
- **Model manager**: HTTPS TensorFlow URL; requests timeout (10, 60); safe content-length parse; KeyError on tar.getmember.
- **Updater**: No unlink before child exec (race fix); retry on GitHub 429/503 with backoff; close mkstemp fd in finally.
- **AV1 settings**: UTF-8 encoding on config read/write.
- **App**: webbrowser.open wrapped in try/except for missing browser.
- **Encoder panel**: Windows long-path warning when source or target exceeds 200 chars.
### Added
- **docs/KNOWN_ISSUES_AND_MITIGATIONS.md**: Researched failure modes and mitigations.

## [2.0.47] - 2026-03-22
### Fixed
- **AV1 settings**: Sanitize merged JSON — `concurrent_jobs` snapped to 1/2/4 (avoids 0 workers / hung batch), quality clamped 0–63, reject timers bounded, `existing_output` and `preset` validated; load/save errors logged via debug logger instead of print.
- **Encoder**: Defensive `concurrent_jobs` int parse and clamp 1–8 before spawning workers; combo index bounds in `_on_jobs_changed`.
- **Scanner**: Progress callback clamps ratio to ≤1.0 to avoid progress bar overflow.
- **Updater**: GitHub API request sends `Accept: application/vnd.github+json`.

## [2.0.46] - 2026-03-22
### Fixed
- **Update check**: When API returns error or non-list JSON, handle gracefully; show "UPDATE CHECK UNAVAILABLE" instead of "up to date" when check fails; log failures via debug logger instead of print.
- **Encoder**: Guard `os.path.commonpath` with try/except for `ValueError` (e.g. Windows mixed-drive paths).

## [2.0.45] - 2026-03-22
### Fixed
- **Update check**: In-app update checker now uses GitHub tags API instead of releases/latest — the latter returns 404 when no GitHub Releases exist (only tags are pushed), causing AUR users to see "up to date" despite newer versions; tags API correctly detects latest version from pushed tags.

## [2.0.44] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Encoding now automatically transitions to "ENCODING COMPLETE" when the batch finishes — no manual STOP required to see final state; added `batch_complete` signal from worker so UI resets even when finished-signal ordering lags.

## [2.0.43] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Mirror-folder output no longer recreates redundant top-level folders (e.g. `Source`) in the target; structure root is now the common parent of all queued files, so only meaningful subdirs (e.g. date folders) are mirrored.

## [2.0.42] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Master progress bar and ESTIMATED TIME REMAINING now update on every file completion — previously relied only on FFmpeg progress parsing which may not fire for short encodes; progress now updates in _on_encode_finished.
- **Mass AV1 Encoder**: Added out_time_ms progress parsing fallback for FFmpeg variants.

## [2.0.41] - 2026-03-22
### Added
- **Mass AV1 Encoder**: AMD hardware encoding — av1_vaapi (Linux) and av1_amf (Windows) when NVIDIA CUDA is not available.
- **Footer**: Activity status with animated dots (Encoding..., Organizing..., Scanning...) instead of log-style output.
### Fixed
- **Mass AV1 Encoder**: NVIDIA full GPU pipeline — added -hwaccel_output_format cuda for decode→encode without CPU copy.
- **Mass AV1 Encoder**: FFmpeg progress parsing — support carriage-return output, out_time= format, -stats_period 0.5.
- **Mass AV1 Encoder**: Work Progress — I/O throughput (MB/s), master bar updates, ESTIMATED TIME REMAINING label with ETA, fps/speed on thread 3rd line.

## [2.0.40] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: START button now responds when target was selected via Browse — `_browse_dst` was blocking `textChanged`, so `_update_start_enabled` never ran and the button stayed disabled.
- **Footer pre-reqs**: Optional status (e.g. OpenCV when not installed) now uses yellow dash; green checkmark for success, red X for failed. Matches requested color scheme.
### Note
- Multiple log files in the log folder indicate separate app launches; one file per session; max 3 retained.

## [2.0.39] - 2026-03-22
### Fixed
- **Guide glow (all panels)**: Third step now correctly shows guide on START button when all inputs are ready (source + target selected); guide was disappearing instead of pulsing on the green START button.

## [2.0.38] - 2026-03-22
### Fixed
- **Logging**: Single debug log file per session; prune runs after file creation to cap at 3 total instances in log folder.
- **Logging**: All entries now identify originating internal app (Media Organizer, Mass AV1 Encoder, AI Media Scanner); av1_engine and model_manager use correct logger names (ChronoArchiver.Encoder, ChronoArchiver.Scanner).

## [2.0.37] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Scan completion now correctly closes dialog and applies results — replaced QTimer.singleShot (which does not run in worker threads) with thread-safe scan_done / scan_done_then_start signals.

## [2.0.36] - 2026-03-22
### Changed
- **Mass AV1 Encoder**: Scan dialog emits for every file found; count increments per file (no throttling).

## [2.0.35] - 2026-03-22
### Changed
- **Logging**: Single log file per session — `chronoarchiver_YYYY-MM-DD_HH-MM-SS.log` created at startup; standard logging and debug() both write to it; no separate chronoarchiver.log; log level DEBUG; added verbose logging for scan, encode, panel switches, pre-reqs.

## [2.0.34] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Source scanner — broaden emit threshold (first 25 files, then every 100ms) to fix freeze after 10 files; remove processEvents (re-entrancy); engine: catch all exceptions in getsize, add os.walk onerror to skip permission-denied dirs; ensure _done always runs with try/except guards; surface scan errors in console.

## [2.0.33] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Scan dialog — restore indeterminate progress bar (unknown total); more frequent updates (emit for first 10 files, then every 50ms); processEvents in update to prevent UI freeze.

## [2.0.32] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Source and target folders no longer saved; cleared on each launch.
- **Mass AV1 Encoder**: Scan dialog now updates file count and total size correctly via thread-safe signal; fixed double "Scanning source folder..." (block signals during Browse setText); replaced indeterminate bar with static bar.
### Changed
- **Mass AV1 Encoder**: Added .mov and .webm to supported scan extensions.

## [2.0.31] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Scan dialog no longer opens on app startup; only opens when user selects source (Browse or typing/pasting path).

## [2.0.30] - 2026-03-22
### Changed
- **Mass AV1 Encoder**: Auto-scan now opens a separate `ScanProgressDialog` window showing file count and total size during source scan; main progress bar is used only for encoding (4 thread bars + total encoding progress) once the user clicks Start.

## [2.0.29] - 2026-03-22
### Fixed
- **Mass AV1 Encoder**: Directories group — increased top padding to align source input with Options; Configuration box bottom aligned with Options via row stretch; progress bar no longer shows indeterminate animation during auto-scan — remains static at "0/0 Files" until scan completes.

## [2.0.28] - 2026-03-21
### Added
- **Media Organizer**: Disk space check before moving; destination writable check; source/target overlap validation; permission error handling (log and continue); long path (>400 chars) warning.
- **AI Media Scanner**: Log corrupt/unreadable images (`cv2.imread` returns None); handle PermissionError when reading files; skip very large images (>100 MB) to avoid OOM.
- **Mass AV1 Encoder**: FFmpeg presence check at startup; target disk space check before encoding; existing output policy (Overwrite / Skip / Rename); remove partial output on encode failure or cancel.

### Changed
- **Cross-cutting**: Worker threads wrapped in try/except; exceptions logged and propagated to UI.

## [2.0.27] - 2026-03-21
### Changed
- **Media Organizer, AI Media Scanner, Mass AV1 Encoder**: Unified queue strategy — all three apps now build a pre-scan queue of (path, size) tuples and use byte-weighted progress for the master bar during processing. Organizer and Scanner log total size (MB) when building the queue.

## [2.0.26] - 2026-03-21
### Fixed
- **Mass AV1 Encoder**: Guide glow now stays on source Browse until scan completes; Work Progress shows "Scanning source..." and indeterminate bar during scan; guide moves to target Browse only after queue is populated.

## [2.0.25] - 2026-03-21
### Fixed
- **Mass AV1 Encoder**: Source and target input boxes now match in width (same min/max constraints).
- **AI Media Scanner**: Setup Models glow no longer causes "AI Models Missing" text to jump; guide buttons use transparent border when idle so size stays constant.

## [2.0.24] - 2026-03-21
### Changed
- **Guide glow**: Pulsing red glow now targets the *buttons* the user clicks (Browse, Setup Models, Photos checkbox) instead of the input fields.

## [2.0.23] - 2026-03-21
### Added
- **Media Organizer, Mass AV1 Encoder, AI Media Scanner**: Pulsing red glow guides users to the next required input (source path, target, media types, Setup Models, etc.). Glow moves step-by-step until START turns green.

## [2.0.22] - 2026-03-21
### Changed
- **Media Organizer, Mass AV1 Encoder, AI Media Scanner**: START buttons disabled until all required inputs are set (source path, target if applicable, media types or extensions, AI models). Matches AI Scanner pattern across all panels.
- **AI Media Scanner**: Model storage moved to user-writable `platformdirs.user_data_dir` (`~/.local/share/ChronoArchiver/models` on Linux). Fixes AUR installs where `/usr/share/chronoarchiver` is read-only.
- **AI Media Scanner**: Download progress bar now updates during model download; status shows "Downloading..." during setup.
### Fixed
- **AI Media Scanner**: START enabled only when both valid folder and ready models are present.

## [2.0.21] - 2026-03-21
### Changed
- **Media Organizer, AI Media Scanner**: STOP buttons grey when disabled; START turns grey during processing; STOP turns red when active. Matches encoder behavior. Re-enable START on stop.

## [2.0.20] - 2026-03-21
### Changed
- **Footer**: Metrics (CPU, GPU, RAM) now shown on all panels (Media Organizer, AI Media Scanner, Mass AV1 Encoder); app-level metrics poll.
- **Footer**: Pre-req checkmarks use bright green (#10b981) for ✓ and Ready; red for ✗ when missing.

## [2.0.19] - 2026-03-21
### Changed
- **Footer**: Restructured — left shows app activity (Encoding, Organizing, Idle); center shows pre-req status (FFmpeg, OpenCV, PySide6); right unchanged (COPY CONSOLE, DEBUG, metrics).

## [2.0.18] - 2026-03-21
### Changed
- **Mass AV1 Encoder**: Preset and Threads dropdowns reduced by 4px vertically (16px) to prevent overlay on Optimize Audio.

## [2.0.17] - 2026-03-21
### Fixed
- **AI Media Scanner**: Face detection now correctly treats empty result array as no faces (`len(faces) > 0` check).
- **Media Organizer**: Corrected indentation in RENAME FIX log branch.

## [2.0.16] - 2026-03-21
### Fixed
- **Mass AV1 Encoder**: Preset and Threads dropdown popups no longer render as oversized overlay; QAbstractItemView styled with sensible min/max height.
### Changed
- **Mass AV1 Encoder**: Options box now expands vertically to match combined height of Directories + Configuration; added bottom stretch for alignment.

## [2.0.15] - 2026-03-21
### Changed
- **Mass AV1 Encoder**: Shrunk Configuration dropdowns (Preset, Threads) vertically (16px height) so Directories + Configuration align with Options box; horizontal sizing reverted.

## [2.0.14] - 2026-03-21
### Fixed
- **AI Media Scanner**: Model path resolution corrected for AUR installations (parent-of-core logic now works for both source and packaged layouts).
- **Mass AV1 Encoder**: Open Logs button now supports macOS (Darwin) via `open` command; added exception handling.

## [2.0.13] - 2026-03-21
### Changed
- **Mass AV1 Encoder**: Skinnier dropdowns (Preset, Threads) for better alignment of Directories + Configuration with Options box.
- **AI Media Scanner**: "ResNet Needs Setup" → "AI Models Missing!"; Start AI Scan button disabled until models are verified present.

## [2.0.12] - 2026-03-21
### Changed
- **Debug logging**: Filename now includes app-start date/time (`chronoarchiver_debug_YYYY-MM-DD_HH-MM-SS.log`); keeps last 3 instances.
- **Debug logging**: Extended events across the app — Media Organizer, AI Media Scanner, Model Manager, app startup.

## [2.0.11] - 2026-03-21
### Changed
- **Mass AV1 Encoder**: Output format fixed to `.mp4`; output naming `stem_av1.mp4` (files with `_av1` before extension are skipped on rescan). Removed Output dropdown from Configuration.
- **Mass AV1 Encoder**: Configuration box shrunk; Work Progress moved up; delete source only when both checkboxes are selected.
- **Debug logging**: Increased events for Mass AV1 Encoder (scan, encode start/finish, reject, fail, delete, batch complete).

## [2.0.10] - 2026-03-21
### Changed
- **Mass AV1 Encoder**: Removed Queue Preview; scan auto-starts when source directory is selected (Browse or typed path); queue resets when source changes; smaller dropdowns; compact Options and Configuration boxes with no extra vertical space.
- **AI Media Scanner**: Right-aligned Start/Stop buttons; larger Scanning Progress bar.

### Removed
- **Mass AV1 Encoder**: Queue Preview box (Scan, Remove Selected, queue list).

## [2.0.9] - 2026-03-21
### Changed
- **AI Media Scanner**: Compact layout — smaller Directories, Options, and Engine Status boxes; horizontal Scanning Progress strip; image preview when selecting Keep/Move items after scan; Results section with dedicated preview pane.
- **Media Organizer**: Directories, Options, and Execution Mode boxes now share equal vertical height.

## [2.0.8] - 2026-03-21
### Added
- **Debug logging**: Centralized `chronoarchiver_debug.log` with timestamps and utility name (Media Organizer, Mass AV1 Encoder, AI Media Scanner). Rotation keeps last 3 log files to prevent storage bloat.
- **Footer buttons**: COPY CONSOLE (copy current panel console to clipboard); DEBUG (open debug log folder in file manager).
- **Media Organizer**: Optional target directory to organize into a different folder; extensions override (comma-separated; blank uses Photos/Videos); summary stats (Moved X | Skipped Y | Duplicates Z) after each run; ffprobe `creation_time` fallback for video metadata before mtime.
- **Mass AV1 Encoder**: Queue preview populated by Scan (items removable before Start); output format choice (.mkv, .webm, .mp4); CRF hints per preset with suggested CQ ranges.
- **AI Media Scanner**: Keep (subjects) and Move (others) result lists; Move Files to move others to `Archived_Others/`; Keep Animals checkbox and confidence threshold (10–90%); Export CSV for Keep/Move paths.

### Changed
- Nav bar panel labels: "AI Encoder" → "Mass AV1 Encoder", "AI Scanner" → "AI Media Scanner".

## [2.0.7] - 2026-03-21
### Fixed
- Updater button stuck on "CHECKING...": switched from Qt Signal to queue + main-thread QTimer polling for reliable cross-thread delivery.
### Changed
- Code cleanup: removed unused imports, dead telemetry signal, REPO_URL; replaced bare `except` with specific exceptions; removed unused `_slbl`, `concurrent.futures`, `_worker_lock`; corrected AI Scanner model hint (YuNet/SSD).

## [2.0.6] - 2026-03-21
### Changed
- AI Encoder: Options box now matches vertical height of Directories + Configuration columns.
- AI Encoder: Fixed overlapping dual-checkbox for "Delete Source on Success"; label moved to top, verification checkboxes placed on separate line and right-aligned.
### Fixed
- Updater button no longer stuck on "CHECKING..."; uses Qt Signal for thread-safe main-thread callback and adds 15s watchdog fallback.

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
- Nav bar: Added "☕ Buy me a coffee" donate button linking to PayPal $5 USD.

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
