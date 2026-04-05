#!/usr/bin/env python3
"""
Bump the app version across canonical files. Single source: src/version.py (__version__).

Usage:
  python tools/bump_version.py 5.1.5

Updates: src/version.py, pyproject.toml, README.md (badge + release table + AUR line),
         PKGBUILD, tools/setup_launcher.py, tools/chronoarchiver_setup.spec
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "version.py"


def _validate_semver(s: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", s.strip()))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/bump_version.py MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2
    new_v = sys.argv[1].strip()
    if not _validate_semver(new_v):
        print("Version must look like 1.2.3", file=sys.stderr)
        return 2

    old = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', old, re.M)
    if not m:
        print("Could not parse __version__ in src/version.py", file=sys.stderr)
        return 1
    prev = m.group(1)
    if prev == new_v:
        print(f"Already at {new_v}")
        return 0

    # 1) version.py
    VERSION_FILE.write_text(
        re.sub(
            r'^(__version__\s*=\s*)["\'][^"\']+["\']',
            rf'\1"{new_v}"',
            old,
            count=1,
            flags=re.M,
        ),
        encoding="utf-8",
    )

    # 2) pyproject.toml
    p = ROOT / "pyproject.toml"
    p.write_text(
        re.sub(r'^version\s*=\s*".*"', f'version = "{new_v}"', p.read_text(encoding="utf-8"), count=1, flags=re.M),
        encoding="utf-8",
    )

    # 3) README.md
    r = ROOT / "README.md"
    txt = r.read_text(encoding="utf-8")
    txt = re.sub(r"version-\d+\.\d+\.\d+-blue", f"version-{new_v}-blue", txt, count=1)
    txt = re.sub(r"Release \*\*\d+\.\d+\.\d+\*\*", f"Release **{new_v}**", txt, count=1)
    txt = re.sub(r"tag `v\d+\.\d+\.\d+`", f"tag `v{new_v}`", txt, count=1)
    txt = re.sub(r"ChronoArchiver-Setup-\d+\.\d+\.\d+-", f"ChronoArchiver-Setup-{new_v}-", txt)
    txt = re.sub(r"at \*\*\d+\.\d+\.\d+\*\*:", f"at **{new_v}**:", txt, count=1)
    r.write_text(txt, encoding="utf-8")

    # 4) PKGBUILD
    pkg = ROOT / "PKGBUILD"
    pkg.write_text(
        re.sub(r"^pkgver=[^\n]+", f"pkgver={new_v}", pkg.read_text(encoding="utf-8"), count=1, flags=re.M),
        encoding="utf-8",
    )

    # 5) tools/setup_launcher.py
    sl = ROOT / "tools" / "setup_launcher.py"
    sl.write_text(
        re.sub(
            r'os\.environ\.get\("CHRONOARCHIVER_VERSION",\s*"[^"]*"\)',
            f'os.environ.get("CHRONOARCHIVER_VERSION", "{new_v}")',
            sl.read_text(encoding="utf-8"),
            count=1,
        ),
        encoding="utf-8",
    )

    # 6) tools/chronoarchiver_setup.spec
    spec = ROOT / "tools" / "chronoarchiver_setup.spec"
    spec.write_text(
        re.sub(
            r'os\.environ\.get\("CHRONOARCHIVER_VERSION",\s*"[^"]*"\)',
            f'os.environ.get("CHRONOARCHIVER_VERSION", "{new_v}")',
            spec.read_text(encoding="utf-8"),
            count=1,
        ),
        encoding="utf-8",
    )

    print(f"Bumped {prev} -> {new_v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
