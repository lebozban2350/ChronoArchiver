"""Persistent AI Video Upscaler options under Settings/ai_video_upscaler/."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .debug_logger import UTILITY_APP, debug
    from .video_target_presets import (
        VIDEO_TARGET_PRESETS,
        default_target_long_edge_for_migration,
    )
except ImportError:
    from core.debug_logger import UTILITY_APP, debug
    from core.video_target_presets import (
        VIDEO_TARGET_PRESETS,
        default_target_long_edge_for_migration,
    )

_VALID_PRESET_KEYS = frozenset(p.key for p in VIDEO_TARGET_PRESETS)


def _preset_key_from_merged(merged: dict, *, had_preset_key_on_disk: bool) -> str:
    """Resolve preset key; migrate legacy scale_index when preset_key was not stored on disk."""
    if had_preset_key_on_disk:
        pk = str(merged.get("preset_key") or "").strip()
        if pk in _VALID_PRESET_KEYS:
            return pk
    try:
        si = int(merged.get("scale_index", 2))
    except (TypeError, ValueError):
        si = 2
    si = max(0, min(2, si))
    target_le = default_target_long_edge_for_migration(si)
    for p in VIDEO_TARGET_PRESETS:
        if p.long_edge >= target_le:
            return p.key
    return VIDEO_TARGET_PRESETS[-1].key


DEFAULTS: dict = {
    # source_video: kept in JSON for migration/sanitize only; panel does not restore or persist path.
    "source_video": "",
    "preset_key": "uhd_4k",
}


def _sanitize(data: dict, defaults: dict, *, had_preset_key_on_disk: bool = True) -> dict:
    merged = {**defaults, **data}
    out = {
        "source_video": str(merged.get("source_video", "") or "").strip(),
        "preset_key": _preset_key_from_merged(
            merged, had_preset_key_on_disk=had_preset_key_on_disk
        ),
    }
    return out


class VideoUpscalerPanelSettings:
    def __init__(self, settings_dir: Path):
        self._dir = Path(settings_dir)
        self.config_path = self._dir / "video_panel_settings.json"

    def load(self) -> dict:
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                had_pk = isinstance(raw, dict) and "preset_key" in raw
                merged = {**DEFAULTS, **raw}
                return _sanitize(merged, DEFAULTS, had_preset_key_on_disk=had_pk)
            except (json.JSONDecodeError, OSError, TypeError) as e:
                debug(UTILITY_APP, f"Video upscaler settings load failed: {e}")
        return _sanitize(dict(DEFAULTS), DEFAULTS)

    def save(self, data: dict) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = _sanitize(data, DEFAULTS)
            tmp = self.config_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp.replace(self.config_path)
        except OSError as e:
            debug(UTILITY_APP, f"Video upscaler settings save failed: {e}")
