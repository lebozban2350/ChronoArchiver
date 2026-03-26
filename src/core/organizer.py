import os
import shutil
import hashlib
import re
import subprocess
import pathlib
from datetime import datetime
from typing import Callable, Optional
import piexif

try:
    from .debug_logger import debug, UTILITY_MEDIA_ORGANIZER
except ImportError:
    from core.debug_logger import debug, UTILITY_MEDIA_ORGANIZER

PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif', '.raw', '.dng', '.arw', '.cr2', '.nef', '.orf', '.rw2'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.webm', '.mkv', '.m4v', '.wmv', '.mpg', '.mpeg', '.ts'}
MIN_YEAR = 1957  # First digital photo (Russell Kirsch 1957)
DEFAULT_EXCLUDE_DIRS = {'.thumbnails', '@recently deleted', '$recycle.bin', '.trash', 'thumbnails'}

class OrganizerEngine:
    def __init__(self, logger_callback: Optional[Callable[[str], None]] = None):
        self.logger = logger_callback or (lambda x: debug(UTILITY_MEDIA_ORGANIZER, x))
        self.cancel_flag = False

    def cancel(self):
        self.cancel_flag = True

    def get_date_taken(self, file_path: str) -> Optional[datetime]:
        """
        Extract date taken. Resolution order:
        - Images: EXIF DateTimeOriginal/Digitized → filename → mtime
        - Videos: FFprobe creation_time → filename → mtime (container metadata often more accurate than filename)
        """
        ext = pathlib.Path(file_path).suffix.lower()
        is_video = ext in VIDEO_EXTS

        def _valid(dt: datetime) -> bool:
            return dt is not None and dt.year >= MIN_YEAR

        # 1. Images: EXIF (DateTimeOriginal 36867, DateTimeDigitized 36868)
        if not is_video:
            try:
                exif_dict = piexif.load(file_path)
                exif_section = exif_dict.get("Exif") or {}
                for tag_id in (36867, 36868):
                    if tag_id not in exif_section:
                        continue
                    raw = exif_section[tag_id]
                    date_str = raw.decode("utf-8", errors="replace").strip()
                    if len(date_str) < 19:
                        continue
                    date_str = date_str[:19]
                    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            if _valid(dt):
                                return dt
                        except ValueError:
                            continue
                    break
            except (Exception, MemoryError):
                pass

        # 2. Videos: FFprobe creation_time (format, then stream tags as fallback)
        if is_video:
            probes = [
                ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
                 "-of", "default=noprint_wrappers=1:nokey=1", file_path],
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream_tags=creation_time",
                 "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            ]
            for cmd in probes:
                try:
                    out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                    if out:
                        line = out.split("=")[-1] if "=" in out else out.split("\n")[0]
                        if line:
                            dt = datetime.fromisoformat(line.replace("Z", "+00:00"))
                            if dt.tzinfo:
                                dt = dt.replace(tzinfo=None)
                            if _valid(dt):
                                return dt
                except (subprocess.SubprocessError, ValueError, OSError, IndexError):
                    pass

        # 3. Filename (YYYY, MM, DD with optional separators)
        filename = os.path.basename(file_path)
        pattern = r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})"
        match = re.search(pattern, filename)
        if match:
            y, m, d = match.groups()
            try:
                dt = datetime.strptime(f"{y}{m}{d}", "%Y%m%d")
                if _valid(dt):
                    return dt
            except ValueError:
                pass

        # 4. Parent folder date (e.g. 2024-03-15 or 20240315 in dir name)
        parent = os.path.dirname(file_path)
        for _ in range(3):  # Check up to 3 levels up
            if not parent or parent == os.path.dirname(parent):
                break
            pname = os.path.basename(parent)
            m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", pname)
            if m:
                y, mo, d = m.groups()
                try:
                    dt = datetime.strptime(f"{y}{mo}{d}", "%Y%m%d")
                    if _valid(dt):
                        return dt
                except ValueError:
                    pass
            parent = os.path.dirname(parent)

        # 5. File modification time
        try:
            timestamp = pathlib.Path(file_path).stat().st_mtime
            dt = datetime.fromtimestamp(timestamp)
            if _valid(dt):
                return dt
        except OSError:
            pass
        return None

    def _quick_hash(self, file_path: str, chunk_size: int = 1024 * 1024) -> str:
        """Read the first 1MB of a file and return its MD5 hash."""
        hasher = hashlib.md5(usedforsecurity=False)
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(chunk_size)
                if chunk:
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    FOLDER_STRUCTURES = {
        "nested": "YYYY/YYYY-MM",
        "flat_month": "YYYY-MM",
        "flat_day": "YYYY-MM-DD",
        "nested_day": "YYYY/YYYY-MM/YYYY-MM-DD",
    }

    def organize(self, source_dir: str, dry_run: bool = True, folder_structure: str = "nested",
                 valid_exts: Optional[set] = None, target_dir: Optional[str] = None,
                 action: str = "move",
                 exclude_dirs: Optional[set] = None, duplicate_policy: str = "rename",
                 progress_callback=None, stats_callback=None):
        """action: move|copy|symlink. duplicate_policy: skip|keep_newer|overwrite|overwrite_same|rename"""
        debug(UTILITY_MEDIA_ORGANIZER, f"organize start: source={source_dir}, dry_run={dry_run}, structure={folder_structure}, action={action}, target={target_dir or 'in-place'}")
        source_dir = (source_dir or "").strip()
        if not source_dir:
            self.logger("Source directory is empty.")
            debug(UTILITY_MEDIA_ORGANIZER, "ERROR: Source directory empty")
            return
        if not os.path.exists(source_dir):
            self.logger("Source directory does not exist.")
            debug(UTILITY_MEDIA_ORGANIZER, "ERROR: Source directory does not exist")
            return

        self.cancel_flag = False
        if valid_exts is None:
            valid_exts = PHOTO_EXTS | VIDEO_EXTS

        target_dir = (target_dir or "").strip() or None
        base_dir = target_dir.rstrip(os.sep) if target_dir else source_dir
        exclude_dirs = exclude_dirs or set()
        exclude_lower = {d.lower().strip() for d in exclude_dirs if d}
        exclude_lower.update(DEFAULT_EXCLUDE_DIRS)

        # Fail-safes: source/target overlap, writable, disk space
        if target_dir:
            src_real = os.path.normcase(os.path.realpath(source_dir))
            tgt_real = os.path.normcase(os.path.realpath(target_dir))
            if src_real == tgt_real:
                self.logger("ERROR: Source and target are the same directory.")
                debug(UTILITY_MEDIA_ORGANIZER, "ERROR: source == target")
                return
            if src_real.startswith(tgt_real + os.sep) or tgt_real.startswith(src_real + os.sep):
                self.logger("ERROR: Target cannot be inside source or vice versa.")
                debug(UTILITY_MEDIA_ORGANIZER, f"ERROR: overlap src={src_real} tgt={tgt_real}")
                return
            if not dry_run:
                if not os.access(target_dir, os.W_OK):
                    self.logger("ERROR: Target directory is not writable.")
                    debug(UTILITY_MEDIA_ORGANIZER, f"ERROR: target not writable: {target_dir}")
                    return

        self.logger("Building file queue...")
        if progress_callback:
            progress_callback(0, 1, 0, 0, "Scanning...")

        queue_list = []
        for root, dirs, files in os.walk(source_dir):
            if self.cancel_flag:
                break
            dirs[:] = [d for d in dirs if d.lower() not in exclude_lower]
            for file in files:
                if self.cancel_flag:
                    break
                ext = pathlib.Path(file).suffix.lower()
                if ext not in valid_exts:
                    continue
                full_path = os.path.join(root, file)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0
                queue_list.append((full_path, size, file))

        total_files = len(queue_list)
        total_bytes = sum(s for _, s, _ in queue_list)
        self.logger(f"Found {total_files} media files ({total_bytes / (1024*1024):.1f} MB).")
        debug(UTILITY_MEDIA_ORGANIZER, f"Found {total_files} files, {total_bytes} bytes")

        # Disk space check (when moving to different target)
        if target_dir and not dry_run and total_bytes > 0:
            try:
                usage = shutil.disk_usage(base_dir)
                free_mb = usage.free / (1024 * 1024)
                need_mb = total_bytes / (1024 * 1024)
                if usage.free < total_bytes * 1.1:  # 10% headroom
                    self.logger(f"WARNING: Low disk space on target. Free: {free_mb:.1f} MB, Need: ~{need_mb:.1f} MB.")
                    debug(UTILITY_MEDIA_ORGANIZER, f"Low disk: free={usage.free} need={total_bytes}")
            except OSError:
                pass

        folder_style = self.FOLDER_STRUCTURES.get(folder_structure, folder_structure)
        dest_note = f" -> {base_dir}" if target_dir else " (in-place)"
        self.logger(f"Starting Organization (Dry Run: {dry_run}, Style: {folder_style}{dest_note})...")

        files_moved = 0
        files_processed = 0
        bytes_done = 0
        duplicates_found = 0
        skipped = 0
        assigned_targets = set()

        for full_path, size, file in queue_list:
            if self.cancel_flag:
                self.logger("Operation Cancelled.")
                debug(UTILITY_MEDIA_ORGANIZER, "Operation cancelled by user")
                break

            files_processed += 1
            bytes_done += size
            if progress_callback and total_bytes > 0:
                progress_callback(bytes_done, total_bytes, files_processed, total_files, file)

            date_obj = self.get_date_taken(full_path)
            if not date_obj:
                self.logger(f"Skipping {file}: Could not determine date.")
                debug(UTILITY_MEDIA_ORGANIZER, f"Skip (no date): {file}")
                skipped += 1
                continue

            # Format Data
            year = str(date_obj.year)
            month_name = f"{date_obj.year}-{date_obj.month:02d}"
            date_prefix = f"{date_obj.year}-{date_obj.month:02d}-{date_obj.day:02d}"

            # Target Structure (base_dir = target or source for in-place)
            day_str = f"{date_obj.year}-{date_obj.month:02d}-{date_obj.day:02d}"
            if folder_structure == "flat_month":
                target_subdir = os.path.join(base_dir, month_name)
                rel_base = month_name
            elif folder_structure == "flat_day":
                target_subdir = os.path.join(base_dir, day_str)
                rel_base = day_str
            elif folder_structure == "nested_day":
                target_subdir = os.path.join(base_dir, year, month_name, day_str)
                rel_base = os.path.join(year, month_name, day_str)
            else:  # nested (default)
                target_subdir = os.path.join(base_dir, year, month_name)
                rel_base = os.path.join(year, month_name)

            # Logic: Check if file already has a YYYY-MM-DD prefix
            match = re.match(r'^(\d{4}-\d{2}-\d{2})_', file)

            if match:
                existing_date = match.group(1)
                if existing_date == date_prefix:
                    new_filename = file
                else:
                    original_name = file[len(match.group(0)):]
                    new_filename = f"{date_prefix}_{original_name}"
                    if not dry_run:
                        self.logger(f"[RENAME FIX] Found incorrect date {existing_date}, fixing to {date_prefix}")
            else:
                new_filename = f"{date_prefix}_{file}"

            if ".." in new_filename or os.path.isabs(new_filename):
                self.logger(f"Skipping {file}: Invalid filename (path traversal).")
                debug(UTILITY_MEDIA_ORGANIZER, f"Skip (invalid name): {file}")
                skipped += 1
                continue

            target_path = os.path.join(target_subdir, new_filename)
            try:
                real_target = os.path.realpath(target_path)
                real_base = os.path.realpath(base_dir)
                if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
                    self.logger(f"Skipping {file}: Resolved path outside target.")
                    debug(UTILITY_MEDIA_ORGANIZER, f"Skip (path escape): {file}")
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue

            # Long path check (filesystem limit ~255 per component, 4096 total on Linux)
            if len(target_path) > 400:
                self.logger(f"WARNING: Long path may fail: {target_path[:80]}...")
                debug(UTILITY_MEDIA_ORGANIZER, f"Long path: {len(target_path)} chars")

            if full_path == target_path:
                continue

            # Deduplication / Collision
            if os.path.exists(target_path):
                try:
                    target_size = os.path.getsize(target_path)
                except OSError:
                    target_size = -1
                same_size = size == target_size
                same_hash = same_size and self._quick_hash(full_path) == self._quick_hash(target_path)
                if same_hash and duplicate_policy in ("skip", "overwrite", "overwrite_same"):
                    self.logger(f"[DUPLICATE] {file} exists in {rel_base}. Skipping.")
                    duplicates_found += 1
                    continue
                if duplicate_policy == "skip":
                    self.logger(f"[SKIP] {file} exists in {rel_base} (different file).")
                    duplicates_found += 1
                    continue
                if duplicate_policy == "keep_newer":
                    try:
                        if os.path.getmtime(full_path) <= os.path.getmtime(target_path):
                            self.logger(f"[SKIP] {file} — target newer.")
                            duplicates_found += 1
                            continue
                    except OSError:
                        pass
                if duplicate_policy != "overwrite" and (duplicate_policy != "overwrite_same" or not same_size):
                    p_new = pathlib.Path(new_filename)
                    base, extension = p_new.stem, p_new.suffix
                    for n in range(1, 9999):
                        candidate = f"{base}_{n}{extension}"
                        candidate_path = os.path.join(target_subdir, candidate)
                        norm_cand = os.path.normcase(candidate_path)
                        if norm_cand not in assigned_targets and not os.path.exists(candidate_path):
                            target_path = candidate_path
                            new_filename = candidate
                            assigned_targets.add(norm_cand)
                            break
                    else:
                        new_name_collision = f"{base}_9999{extension}"
                        target_path = os.path.join(target_subdir, new_name_collision)
                        new_filename = new_name_collision
                        assigned_targets.add(os.path.normcase(target_path))

            rel_target_path = os.path.join(rel_base, new_filename)
            action_verb = {"move": "MOVE", "copy": "COPY", "symlink": "LINK"}.get(action, "MOVE")

            def _do_file(src: str, dst: str, label: str) -> bool:
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                except OSError as e:
                    self.logger(f"Error creating directory for {label}: {e}")
                    return False
                try:
                    if action == "move":
                        shutil.move(src, dst)
                    elif action == "copy":
                        shutil.copy2(src, dst)
                    else:
                        os.symlink(src, dst)
                    return True
                except OSError as e:
                    self.logger(f"Error {action} {label}: {e}")
                    return False

            if not dry_run:
                if _do_file(full_path, target_path, file):
                    files_moved += 1
                    self.logger(f"[{action_verb}] \"{file}\" -> \"{rel_target_path}\"")
            else:
                files_moved += 1
                self.logger(f"[DRY RUN] [{action_verb}] \"{file}\" -> \"{rel_target_path}\"")

        self.logger(f"Done. Moved: {files_moved}, Skipped: {skipped}, Duplicates: {duplicates_found}.")
        debug(UTILITY_MEDIA_ORGANIZER, f"Done: moved={files_moved}, skipped={skipped}, duplicates={duplicates_found}")
        if stats_callback:
            stats_callback(files_moved, skipped, duplicates_found)

