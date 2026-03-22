import os
import shutil
import hashlib
import re
import subprocess
import pathlib
from datetime import datetime
from typing import List, Callable, Optional, Tuple
import piexif

try:
    from .debug_logger import debug, UTILITY_MEDIA_ORGANIZER
except ImportError:
    from core.debug_logger import debug, UTILITY_MEDIA_ORGANIZER

VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.webm', '.mkv', '.m4v', '.wmv', '.mpg', '.mpeg', '.ts'}

class OrganizerEngine:
    def __init__(self, logger_callback: Optional[Callable[[str], None]] = None):
        self.logger = logger_callback or (lambda x: print(x))
        self.cancel_flag = False

    def cancel(self):
        self.cancel_flag = True

    def get_date_taken(self, file_path: str) -> Optional[datetime]:
        """
        Extract date taken from EXIF or fallback to file modified time.
        """
        # Try Piexif for images
        try:
            exif_dict = piexif.load(file_path)
            # DateTimeOriginal is 36867
            if 36867 in exif_dict.get("Exif", {}):
                date_str = exif_dict["Exif"][36867].decode("utf-8")
                # Format is usually "YYYY:MM:DD HH:MM:SS"
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            
            # DateTimeDigitized is 36868
            if 36868 in exif_dict.get("Exif", {}):
                date_str = exif_dict["Exif"][36868].decode("utf-8")
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")

        except Exception:
            pass
            
        # 2. Try Filename Parsing (Smart Regex)
        filename = os.path.basename(file_path)
        
        # Regex: Matches YYYY followed by MM followed by DD (with optional separators)
        pattern = r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})"
        match = re.search(pattern, filename)
        if match:
            y, m, d = match.groups()
            try:
                # Validates against a standard calendar (raises ValueError for things like Feb 31)
                return datetime.strptime(f"{y}{m}{d}", "%Y%m%d")
            except ValueError:
                return None

        # 3. For videos: try ffprobe creation_time
        ext = pathlib.Path(file_path).suffix.lower()
        if ext in VIDEO_EXTS:
            try:
                cmd = [
                    "ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
                    "-of", "default=noprint_wrappers=1:nokey=1", file_path
                ]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
                if out:
                    dt = datetime.fromisoformat(out.replace("Z", "+00:00"))
                    if dt.tzinfo:
                        dt = dt.replace(tzinfo=None)
                    if dt.year >= 1980:
                        return dt
            except (subprocess.SubprocessError, ValueError, OSError):
                pass

        # 4. Fallback to file modification time
        try:
            timestamp = pathlib.Path(file_path).stat().st_mtime
            dt = datetime.fromtimestamp(timestamp)
            if dt.year < 1980:
                return None
            return dt
        except OSError:
            return None

    def _quick_hash(self, file_path: str, chunk_size: int = 1024 * 1024) -> str:
        """Read the first 1MB of a file and return its MD5 hash."""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(chunk_size)
                if chunk:
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def count_files(self, source_dir: str, valid_exts: set) -> int:
        count = 0
        for root, _, files in os.walk(source_dir):
            if self.cancel_flag: return 0
            for file in files:
                if pathlib.Path(file).suffix.lower() in valid_exts:
                    count += 1
        return count

    def organize(self, source_dir: str, dry_run: bool = True, use_flat_folders: bool = False,
                 valid_exts: Optional[set] = None, target_dir: Optional[str] = None,
                 progress_callback=None, stats_callback=None):
        debug(UTILITY_MEDIA_ORGANIZER, f"organize start: source={source_dir}, dry_run={dry_run}, flat={use_flat_folders}, target={target_dir or 'in-place'}")
        if not os.path.exists(source_dir):
            self.logger("Source directory does not exist.")
            debug(UTILITY_MEDIA_ORGANIZER, "ERROR: Source directory does not exist")
            return

        self.cancel_flag = False
        if valid_exts is None:
            valid_exts = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi', '.webm', '.mkv', '.gif', '.bmp', '.tiff'}

        base_dir = target_dir.rstrip(os.sep) if target_dir else source_dir

        self.logger("Building file queue...")
        if progress_callback:
            progress_callback(0, 1, 0, 0, "Scanning...")

        queue_list = []
        for root, _, files in os.walk(source_dir):
            if self.cancel_flag:
                break
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

        folder_style = "Flat (YYYY-MM)" if use_flat_folders else "Nested (YYYY/YYYY-MM)"
        dest_note = f" -> {base_dir}" if target_dir else " (in-place)"
        self.logger(f"Starting Organization (Dry Run: {dry_run}, Style: {folder_style}{dest_note})...")

        files_moved = 0
        files_processed = 0
        bytes_done = 0
        duplicates_found = 0
        skipped = 0

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
            if use_flat_folders:
                target_subdir = os.path.join(base_dir, month_name)
                rel_base = month_name
            else:
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

            target_path = os.path.join(target_subdir, new_filename)

            if full_path == target_path:
                continue

            # Deduplication / Collision
            if os.path.exists(target_path):
                if os.path.getsize(full_path) == os.path.getsize(target_path) and \
                   self._quick_hash(full_path) == self._quick_hash(target_path):
                    self.logger(f"[DUPLICATE] {file} exists in {rel_base}. Skipping.")
                    debug(UTILITY_MEDIA_ORGANIZER, f"Duplicate: {file}")
                    duplicates_found += 1
                    continue
                else:
                    p_new = pathlib.Path(new_filename)
                    base, extension = p_new.stem, p_new.suffix
                    new_name_collision = f"{base}_{int(datetime.now().timestamp())}{extension}"
                    target_path = os.path.join(target_subdir, new_name_collision)
                    new_filename = new_name_collision

            rel_target_path = os.path.join(rel_base, new_filename)

            if not dry_run:
                os.makedirs(target_subdir, exist_ok=True)
                try:
                    shutil.move(full_path, target_path)
                    files_moved += 1
                    self.logger(f"[MOVE] \"{file}\" -> \"{rel_target_path}\"")
                except Exception as e:
                    self.logger(f"Error moving {file}: {e}")
                    debug(UTILITY_MEDIA_ORGANIZER, f"Error moving {file}: {e}")
            else:
                files_moved += 1
                self.logger(f"[DRY RUN] \"{file}\" -> \"{rel_target_path}\"")

        self.logger(f"Done. Moved: {files_moved}, Skipped: {skipped}, Duplicates: {duplicates_found}.")
        debug(UTILITY_MEDIA_ORGANIZER, f"Done: moved={files_moved}, skipped={skipped}, duplicates={duplicates_found}")
        if stats_callback:
            stats_callback(files_moved, skipped, duplicates_found)

