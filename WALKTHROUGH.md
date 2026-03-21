# WALKTHROUGH.md

# Walkthrough: ChronoArchiver v1.0.15 (Dependency & Icon Polish)
- **Dependency Resolution**: Corrected `PKGBUILD` to depend on `python-opencv` instead of `opencv`, resolving the `ModuleNotFoundError: No module named 'cv2'` on Arch Linux.
- **Pixel-Perfect Icon Scaling**: Re-processed the premium icon motif to fit exactly 256px height (top-to-bottom) with absolute alpha transparency and zero padding artifacts.
- **Global Release**: Synchronized version `v1.0.15` across GitHub and the official AUR repository.

---

# Walkthrough: ChronoArchiver v1.0.14 (Architecture & Refined Branding)
- **Architecture Stabilization**: Resolved a critical circular import between `app.py` and `tabs.py` by centralizing UI constants in `theme.py` and refactor of `ui.tabs` into a package.
- **Refined Premium Icon**: Regenerated icon with initial transparency and tight framing.

---

# Walkthrough: ChronoArchiver v1.0.13 (Brand Catchline)
- **Official Catchline**: Integrated "Time to Archive!" into the application title bar and log console header.
- **Unified Branding**: Synchronized the catchline across `README.md`, `PKGBUILD`, and `chronoarchiver.desktop`.
- **Global Release**: Bumped version to `v1.0.13` and synchronized all repositories (GitHub and AUR).
