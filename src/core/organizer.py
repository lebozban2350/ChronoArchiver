import os
import shutil
import hashlib
import re
import pathlib
from datetime import datetime
from typing import List, Callable, Optional
import piexif

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

        # 3. Fallback to file creation/modification (Standard for videos/webms if no other lib)
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

    def organize(self, source_dir: str, dry_run: bool = True, use_flat_folders: bool = False, valid_exts: Optional[set] = None, progress_callback=None):
        if not os.path.exists(source_dir):
            self.logger("Source directory does not exist.")
            return

        self.cancel_flag = False
        if valid_exts is None:
            valid_exts = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi', '.webm', '.mkv', '.gif', '.bmp', '.tiff'}
        
        self.logger("Counting files...")
        if progress_callback: progress_callback(0, 0, "Counting files...")
        
        total_files = self.count_files(source_dir, valid_exts)
        self.logger(f"Found {total_files} media files.")
        
        folder_style = "Flat (YYYY-MM)" if use_flat_folders else "Nested (YYYY/YYYY-MM)"
        self.logger(f"Starting Organization (Dry Run: {dry_run}, Style: {folder_style})...")
        
        files_moved = 0
        files_processed = 0
        duplicates_found = 0
        
        for root, _, files in os.walk(source_dir):
            if self.cancel_flag:
                self.logger("Operation Cancelled.")
                break
                
            for file in files:
                if self.cancel_flag: break
                
                ext = pathlib.Path(file).suffix.lower()
                if ext not in valid_exts:
                    continue
                    
                files_processed += 1
                if progress_callback:
                    progress_callback(files_processed, total_files, file)

                full_path = os.path.join(root, file)
                date_obj = self.get_date_taken(full_path)
                
                if not date_obj:
                    self.logger(f"Skipping {file}: Could not determine date.")
                    continue
                
                # Format Data
                year = str(date_obj.year)
                month_name = f"{date_obj.year}-{date_obj.month:02d}"
                date_prefix = f"{date_obj.year}-{date_obj.month:02d}-{date_obj.day:02d}"

                # Target Structure
                if use_flat_folders:
                    # Flat: Source/YYYY-MM/
                    target_dir = os.path.join(source_dir, month_name)
                    rel_base = month_name
                else:
                    # Nested: Source/YYYY/YYYY-MM/
                    target_dir = os.path.join(source_dir, year, month_name)
                    rel_base = os.path.join(year, month_name)
                
                # Logic: Check if file already has a YYYY-MM-DD prefix
                match = re.match(r'^(\d{4}-\d{2}-\d{2})_', file)
                
                if match:
                    existing_date = match.group(1)
                    if existing_date == date_prefix:
                        # It matches our calculated date. Keep it as is (avoid double prefix)
                        new_filename = file
                    else:
                        # Mismatch! The file has a date prefix, but it's WRONG (according to our best scan).
                        # Strip the old prefix and apply the new one.
                        # Original name without prefix
                        original_name = file[len(match.group(0)):]
                        new_filename = f"{date_prefix}_{original_name}"
                        if not dry_run:
                             self.logger(f"[RENAME FIX] Found incorrect date {existing_date}, fixing to {date_prefix}")
                else:
                    # No prefix, add it.
                    new_filename = f"{date_prefix}_{file}"

                target_path = os.path.join(target_dir, new_filename)
                
                # Check if it's already there (path match)
                if full_path == target_path:
                    continue
                
                # Deduplication / Collision
                if os.path.exists(target_path):
                    # Simple size check and quick hash check
                    if os.path.getsize(full_path) == os.path.getsize(target_path) and \
                       self._quick_hash(full_path) == self._quick_hash(target_path):
                        self.logger(f"[DUPLICATE] {file} exists in {rel_base}. Skipping.")
                        duplicates_found += 1
                        continue
                    else:
                        # Name collision, rename append timestamp
                        p_new = pathlib.Path(new_filename)
                        base, extension = p_new.stem, p_new.suffix
                        new_name_collision = f"{base}_{int(datetime.now().timestamp())}{extension}"
                        target_path = os.path.join(target_dir, new_name_collision)
                        new_filename = new_name_collision

                rel_target_path = os.path.join(rel_base, new_filename)
                
                if not dry_run:
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        shutil.move(full_path, target_path)
                        files_moved += 1
                        self.logger(f"[MOVE] \"{file}\" -> \"{rel_target_path}\"")
                    except Exception as e:
                        self.logger(f"Error moving {file}: {e}")
                else:
                    files_moved += 1
                    self.logger(f"[DRY RUN] \"{file}\" -> \"{rel_target_path}\"")

        self.logger(f"Done. Moved: {files_moved}. Duplicates: {duplicates_found}.")

