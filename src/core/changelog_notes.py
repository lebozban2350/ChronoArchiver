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
