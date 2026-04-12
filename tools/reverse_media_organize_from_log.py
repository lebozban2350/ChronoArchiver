#!/usr/bin/env python3
"""
Reverse an in-place Media Organizer run by parsing [MOVE] lines from a session log.

The organizer logs: [MOVE] "original_basename" -> "relative/path/under/source"

This script moves each file from ``root/relative/path`` back to ``root/original_basename``,
processing lines in *reverse* order so duplicate basenames (e.g. m287.jpg) restore safely.

**Limitation:** This only restores a *flat* library where every file originally lived
directly under ``root`` (no meaningful subfolders). If files came from nested paths,
the log does not record full source paths — use NAS snapshots/backups instead.

Usage:
  python3 tools/reverse_media_organize_from_log.py --log PATH --root SOURCE_ROOT --dry-run
  python3 tools/reverse_media_organize_from_log.py --log PATH --root SOURCE_ROOT --execute
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

_MOVE_RE = re.compile(
    r'\[(?:MOVE|COPY)(?: \+ EXIF ROTATE)?\] "([^"]*)" -> "([^"]*)"'
)


def parse_moves(log_path: str) -> list[tuple[str, str]]:
    """Return list of (original_basename, rel_dest) from log lines, in file order."""
    out: list[tuple[str, str]] = []
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _MOVE_RE.search(line)
            if not m:
                continue
            orig, rel = m.group(1), m.group(2)
            if ".." in rel or rel.startswith("/"):
                continue
            out.append((orig, rel))
    return out


def unique_dest_path(
    root: str, basename: str, reserved: set[str] | None = None
) -> str:
    """Pick a free name under root: existing files OR names reserved by this run."""
    reserved = reserved or set()

    def taken(name: str) -> bool:
        p = os.path.join(root, name)
        return name in reserved or os.path.lexists(p)

    if not taken(basename):
        return os.path.join(root, basename)
    stem, ext = os.path.splitext(basename)
    for n in range(1, 10000):
        alt = f"{stem}_{n}{ext}"
        if not taken(alt):
            return os.path.join(root, alt)
    raise OSError(f"No free name for {basename!r} under {root}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", required=True, help="chronoarchiver_*.log path")
    ap.add_argument("--root", required=True, help="Organizer source root (same as the run)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Print planned moves only")
    g.add_argument("--execute", action="store_true", help="Perform shutil.move")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    if not os.path.isdir(root):
        print(f"ERROR: root is not a directory: {root}", file=sys.stderr)
        return 1

    moves = parse_moves(args.log)
    if not moves:
        print("No [MOVE]/[COPY] lines found (or log path wrong).", file=sys.stderr)
        return 1

    # Reverse order: last organized file is undone first (helps duplicate basenames).
    # Reserve destination basenames as we plan so two undo steps never target the same path.
    reserved_names: set[str] = set()
    plan: list[tuple[str, str]] = []
    for orig, rel in reversed(moves):
        src = os.path.normpath(os.path.join(root, rel))
        if not src.startswith(root + os.sep) and src != root:
            print(f"SKIP (path escape): {rel}", file=sys.stderr)
            continue
        if not os.path.isfile(src):
            print(f"MISSING (already moved or wrong root?): {src}", file=sys.stderr)
            continue
        dst = unique_dest_path(root, orig, reserved_names)
        reserved_names.add(os.path.basename(dst))
        plan.append((src, dst))

    print(f"Planned operations: {len(plan)} (from {len(moves)} log lines)")
    for src, dst in plan:
        print(f'  mv "{src}" -> "{dst}"')

    if args.dry_run:
        print("\nDry run only. Re-run with --execute to apply.")
        return 0

    for src, dst in plan:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.move(src, dst)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
