import json
import os
import shutil
from pathlib import Path

import platformdirs

try:
    from .debug_logger import debug, UTILITY_APP
except ImportError:
    from core.debug_logger import debug, UTILITY_APP


def _sanitize_encoder_config(data: dict, defaults: dict) -> dict:
    """Normalize values after JSON merge (invalid manual edits, old keys)."""
    out = dict(data)
    # Parallel jobs: UI allows 1, 2, 4 — snap anything else to nearest valid
    try:
        cj = int(out.get("concurrent_jobs", defaults["concurrent_jobs"]))
    except (TypeError, ValueError):
        cj = defaults["concurrent_jobs"]
    if cj < 1:
        cj = 1
    elif cj > 4:
        cj = 4
    if cj not in (1, 2, 4):
        cj = min((1, 2, 4), key=lambda x: abs(x - cj))
    out["concurrent_jobs"] = cj
    # CQ / quality (slider 0–63)
    try:
        q = int(out.get("quality", defaults["quality"]))
    except (TypeError, ValueError):
        q = defaults["quality"]
    out["quality"] = max(0, min(63, q))
    # Reject-duration thresholds
    for k, lo, hi in (("rejects_h", 0, 99), ("rejects_m", 0, 59), ("rejects_s", 0, 59)):
        try:
            v = int(out.get(k, defaults[k]))
        except (TypeError, ValueError):
            v = defaults[k]
        out[k] = max(lo, min(hi, v))
    eo = out.get("existing_output")
    if eo not in ("overwrite", "skip", "rename"):
        out["existing_output"] = "overwrite"
    p = str(out.get("preset", "p4")).lower().strip()
    if len(p) == 2 and p[0] == "p" and p[1].isdigit():
        pn = int(p[1])
        out["preset"] = f"p{pn}" if 1 <= pn <= 7 else "p4"
    else:
        out["preset"] = "p4"
    return out


def _av1_config_dir() -> Path:
    """
    Writable directory for av1_config.json.

    - Installer / portable layout: <install root>/Settings (alongside Logs, venv, src).
    - Else: platformdirs without a second app-name segment (Windows was
      Local/ChronoArchiver/ChronoArchiver; we use Local/ChronoArchiver only).
    """
    install_root = os.environ.get("CHRONOARCHIVER_INSTALL_ROOT", "").strip()
    if install_root:
        return Path(install_root) / "Settings"
    return Path(platformdirs.user_config_dir("ChronoArchiver", appauthor=False))


def _legacy_av1_config_file() -> Path:
    """Older releases used platformdirs default (nested ChronoArchiver on Windows)."""
    return Path(platformdirs.user_config_dir("ChronoArchiver")) / "av1_config.json"


def _migrate_legacy_av1_config(dest: Path) -> None:
    if dest.exists():
        return
    legacy = _legacy_av1_config_file()
    if not legacy.is_file() or legacy.resolve() == dest.resolve():
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, dest)
        try:
            legacy.unlink()
        except OSError:
            pass
    except OSError:
        pass


class AV1Settings:
    """Handles persistent settings for ChronoArchiver AV1 Encoder."""
    
    def __init__(self):
        cfg_dir = _av1_config_dir()
        self.config_path = str(cfg_dir / "av1_config.json")
        _migrate_legacy_av1_config(Path(self.config_path))
        self.config_dir = str(cfg_dir)
        self.defaults = {
            "quality": 30,
            "preset": "p4",
            "output_ext": ".mkv",
            "reencode_audio": True,
            "concurrent_jobs": 2,
            "source_folder": "",
            "target_folder": "",
            "maintain_structure": True,
            "debug_mode": False,
            "rejects_enabled": False,
            "rejects_h": 0,
            "rejects_m": 0,
            "rejects_s": 10,
            "delete_on_success": False,
            "delete_on_success_confirm": False,
            "hw_accel_decode": False,
            "shutdown_on_finish": False,
            "existing_output": "overwrite"  # overwrite | skip | rename
        }
        self.data = self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    merged = {**self.defaults, **json.load(f)}
                return _sanitize_encoder_config(merged, self.defaults)
            except (json.JSONDecodeError, OSError) as e:
                debug(UTILITY_APP, f"AV1 config load failed, using defaults: {e}")
                return _sanitize_encoder_config(dict(self.defaults), self.defaults)
        return _sanitize_encoder_config({**self.defaults}, self.defaults)

    def save(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except OSError as e:
            debug(UTILITY_APP, f"AV1 config save failed: {e}")

    def get(self, key):
        return self.data.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()
