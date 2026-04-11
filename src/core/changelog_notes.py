"""Load CHANGELOG.md and extract the section for a given version (release notes UI)."""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Public web fallbacks when no local CHANGELOG is available (e.g. some frozen layouts).
CHANGELOG_BLOB_URL = "https://github.com/UnDadFeated/ChronoArchiver/blob/main/CHANGELOG.md"
CHANGELOG_RAW_URL = "https://raw.githubusercontent.com/UnDadFeated/ChronoArchiver/main/CHANGELOG.md"

# Shipped with the app so “What’s new” always has text when repo CHANGELOG.md is missing or stale.
# On each release bump, copy the ## [X.Y.Z] block from CHANGELOG.md (see tools/bump_version.py reminder).
EMBEDDED_RELEASE_NOTES: dict[str, str] = {
    "5.7.11": """## [5.7.11] - 2026-04-12

### Fixed
- **Mass AV1 Encoder**: **Stale progress** after a file finishes is ignored (**SIGSEGV** mitigation). **Master/ETA/I-O** updates capped at **~10/s**.
""",
    "5.7.10": """## [5.7.10] - 2026-04-12

### Fixed
- **Mass AV1 Encoder**: **SSH** scan dialog shows **live** progress; **encode finish** UI work is **serialized** for stability.

### Changed
- **Mass AV1 Encoder**: **FFmpeg** progress posts throttled to **~6.7/s** per worker.
""",
    "5.7.9": """## [5.7.9] - 2026-04-10

### Fixed
- **Mass AV1 Encoder**: Safer **4-thread** worker exit (**atomic** active-job count); no false **batch complete** on **STOP** in **remote pipeline** mode.

### Changed
- **Mass AV1 Encoder**: **GC** every **400** files on very long batches.
""",
    "5.7.8": """## [5.7.8] - 2026-04-12

### Fixed
- **NVENC**: Expected **183/218** retry is **INFO**, not **ERROR**. Worker→UI encoder signals are **queued** for thread safety.
""",
    "5.7.7": """## [5.7.7] - 2026-04-12

### Fixed
- **Mass AV1 Encoder**: Throttled FFmpeg **progress → UI** updates (~8/s per worker) to avoid Qt event-queue overload on long encodes.
""",
    "5.7.6": """## [5.7.6] - 2026-04-12

### Changed
- **Onboarding guide**: Shared primary-button guide styles/helpers in **`panel_widgets`**; Ruff formatting across the tree.

### Fixed
- **AV1 engine** / **remote SSH**: Duplicate import and dead assignment cleanup. **Organizer** / **Encoder** / **Scanner** guide pulse no longer conflicts with disabled or **STOP** button styling.
""",
    "5.7.5": """## [5.7.5] - 2026-04-11

### Changed
- **Mass AV1 Encoder**: Red **STOP ENCODING** styling (clears guide pulse overrides); **Preset**, **Threads**, and **If output exists** combos size to content.

### Fixed
- **Mass AV1 Encoder**: **STOP** remains enabled while encoding when the form re-validates.
""",
    "5.7.4": """## [5.7.4] - 2026-04-10

### Fixed
- **Footer GPU %**: Stronger **discrete NVIDIA** selection (``lspci`` domain BDFs + ``nvidia-smi -L``); **encoder** utilization included; optional ``CHRONOARCHIVER_FOOTER_NVIDIA_GPU``.
""",
    "5.7.3": """## [5.7.3] - 2026-04-10

### Fixed
- **Mass AV1 Encoder**: Console uses **plain text** (`QPlainTextEdit`) instead of rich HTML so long encode batches do not crash Qt during repaint.
""",
    "5.7.2": """## [5.7.2] - 2026-04-10

### Fixed
- **Mass AV1 Encoder**: Per-job **fps / speed** line parses current FFmpeg progress fields (including ``time=N/A`` warmup and ``KiB``/``Lsize``).
""",
    "5.7.1": """## [5.7.1] - 2026-04-10

### Changed
- **Footer GPU %** (`nvidia-smi`): Uses the same preferred NVIDIA adapter as `detect_gpu()` (discrete before integrated; ``CHRONOARCHIVER_FFMPEG_NVENC_GPU`` override). Linux matches **lspci** to ``pci.bus_id``; Windows multi-GPU falls back to largest **memory.total** when needed.
""",
    "5.7.0": """## [5.7.0] - 2026-04-10

### Added
- **Mass AV1 Encoder**: Already-**AV1** sources passthrough to `*_av1.mp4` (copy or **ffmpeg -c copy** remux) instead of re-encoding.

### Changed
- Encoder codec UI via **ffprobe** + queued signals; **NVENC** CUDA-decode skip after first **183/218** per batch; browse dialog layout fixes.

### Removed
- Footer **COPY DEBUG INFO**, **SHORTCUTS**, **SECURITY**, **EXPORT DIAGNOSTICS** and related modules.
""",
    "5.6.4": """## [5.6.4] - 2026-04-10

### Added
- **Mass AV1 Encoder / network batches**: Prefetch pipeline overlaps **scp** downloads with local **FFmpeg** encoding (bounded queue); cleans temps after upload.
""",
    "5.6.3": """## [5.6.3] - 2026-04-10

### Fixed
- **Remote scan / sshpass**: Clears ``SSH_ASKPASS`` / ``GIT_ASKPASS`` when using password mode so captured SSH output is reliable.
- **Encoder**: Remote scan failures log at WARNING; temp encode files use prefix ``chronoarchiver_av1_`` and are cleaned per job and on stop/quit; large scan totals no longer overflow Qt signals; **KeyError** in progress UI fixed (do not replace speed label list with a dict).
""",
    "5.6.2": """## [5.6.2] - 2026-04-10

### Fixed
- **Remote AV1 encoding**: SSH remote steps use ``sh -c`` so **fish** login shells do not break ``python3`` scan/verify.
""",
    "5.6.1": """## [5.6.1] - 2026-04-10

### Fixed
- **AV1 Encoder / Browse**: SSH password from the remote picker is copied to the panel field on OK; remote scan/encode match **Test SSH**. Clearer errors when SSH auth fails (not mislabeled as missing ``python3``).
""",
    "5.6.0": """## [5.6.0] - 2026-04-10

### Added
- **Mass AV1 Encoder — remote source and/or destination**: **scp** pull, local **FFmpeg**, **scp** push; remote scan via **SSH** + **python3** on the host; optional **sshpass** for password auth.

### Fixed
- **Encoder guide**: Local source + remote destination no longer traps the highlight on **Browse**.
""",
    "5.5.1": """## [5.5.1] - 2026-04-10

### Fixed
- **Guide pulse**: Remote `sftp://` paths no longer leave the highlight stuck on **Browse**; flow continues to **Start** / output where appropriate (encoder skips scan wait for remote URIs).
""",
    "5.5.0": """## [5.5.0] - 2026-04-10

### Added
- **Browse (Organizer, Mass AV1 Encoder, AI Media Scanner)**: pop-up **Local folder** vs **Remote (SSH / SFTP)** with `sftp://` or `user@host:/path`, optional password (not saved), and **Test SSH**. Remote URIs are stored in the path field; local processing shows a clear error until paths are local or mounted.
""",
    "5.4.4": """## [5.4.4] - 2026-04-09

### Changed
- **README**: Rewritten for first-time users with a simplified onboarding flow while preserving the existing application branding block and documentation links.
""",
    "5.4.3": """## [5.4.3] - 2026-04-08

### Added
- **`tools/verify_release_versions.py`**: CI checks version strings across **pyproject**, **README**, **PKGBUILD**, installer defaults, and **EMBEDDED_RELEASE_NOTES**.

### Fixed
- **CI**: **`libegl1`** and related libs for **PySide6** offscreen; **What’s new** resolves notes from disk, GitHub raw, or bundled text.

### Changed
- **CI**: pinned **Ruff**, Node 24 opt-in for Actions, **`bump_version`** reminder for embedded notes; **Ruff** includes **`tools/`**; **`updater.py`** formatting aligned with **Ruff 0.8.4**.
""",
    "5.4.2": """## [5.4.2] - 2026-04-06

### Added
- **Media Organizer**: **EXIF auto-rotate photos** checkbox in **Execution Mode** — for JPEG/PNG/WebP/TIFF/BMP/GIF with a non-default **Orientation** tag, decode with Pillow, apply **`ImageOps.exif_transpose`**, and save upright (re-encodes). Skipped when **Action** is **Symlink**; unsupported formats fall back to plain move/copy.

### Documentation
- **README**: Media Organizer row mentions optional EXIF auto-rotate.
""",
}


def changelog_file_candidates() -> list[Path]:
    """Paths to try for CHANGELOG.md (git layout, then PyInstaller bundle / install dir)."""
    core = Path(__file__).resolve().parent
    out: list[Path] = []
    # src/core -> parents[1] = repository root
    out.append(core.parents[1] / "CHANGELOG.md")
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            out.append(Path(meipass) / "CHANGELOG.md")
        exe_dir = Path(sys.executable).resolve().parent
        out.append(exe_dir / "CHANGELOG.md")
        out.append(exe_dir.parent / "CHANGELOG.md")
    return out


def read_changelog_markdown() -> tuple[str | None, Path | None]:
    """
    Returns (markdown text, path) if a readable file was found; else (None, None).
    """
    for p in changelog_file_candidates():
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace"), p
        except OSError:
            continue
    return None, None


def changelog_section_for_version(body: str, version: str) -> str | None:
    """Return the full markdown block for ``## [version]`` through the next ``## [`` or EOF."""
    if not body or not version:
        return None
    pat = rf"(?ms)^## \[{re.escape(version.strip())}\].*?(?=^## \[|\Z)"
    m = re.search(pat, body)
    return m.group(0).strip() if m else None


def fetch_changelog_raw_from_github(timeout_s: float = 12.0) -> str | None:
    """Download main-branch CHANGELOG.md from GitHub (for offline installs missing a local file)."""
    try:
        req = urllib.request.Request(
            CHANGELOG_RAW_URL,
            headers={"User-Agent": "ChronoArchiver-WhatsNew"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec B310 — fixed GitHub raw URL
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def release_notes_for_version(version: str) -> tuple[str, Path | None, str]:
    """
    Return (markdown body, optional path to local CHANGELOG for “open file”, source tag).

    Resolution order: local CHANGELOG section → GitHub raw (same as repo main) →
    embedded dict shipped with the app → short offline fallback.
    Source is one of: ``local``, ``network``, ``embedded``, ``fallback``.
    """
    v = (version or "").strip()
    body, path = read_changelog_markdown()
    if body:
        section = changelog_section_for_version(body, v)
        if section:
            return section, path, "local"

    remote = fetch_changelog_raw_from_github()
    if remote:
        section = changelog_section_for_version(remote, v)
        if section:
            return section, path, "network"

    if v in EMBEDDED_RELEASE_NOTES:
        return EMBEDDED_RELEASE_NOTES[v].strip(), path, "embedded"

    fb = (
        f"Release notes for **{v}** are not bundled and could not be loaded "
        f"(offline or GitHub unreachable).\n\n"
        f"Use **View changelog** to open the project history in your browser when online."
    )
    return fb, path, "fallback"
