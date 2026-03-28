"""Persistent AI Video Upscaler options under Settings/ai_video_upscaler/."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .debug_logger import UTILITY_APP, debug
except ImportError:
    from core.debug_logger import UTILITY_APP, debug

DEFAULTS: dict = {
    # source_video: kept in JSON for migration/sanitize only; panel does not restore or persist path.
    "source_video": "",
    "scale_index": 2,  # 0=2× 1=3× 2=4× — only user-facing option; pipeline is hardcoded in the panel.
}


def _sanitize(data: dict, defaults: dict) -> dict:
    out = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    out["source_video"] = str(out.get("source_video", "") or "").strip()
    try:
        si = int(out.get("scale_index", defaults["scale_index"]))
    except (TypeError, ValueError):
        si = int(defaults["scale_index"])
    out["scale_index"] = max(0, min(2, si))
    return out


class VideoUpscalerPanelSettings:
    def __init__(self, settings_dir: Path):
        self._dir = Path(settings_dir)
        self.config_path = self._dir / "video_panel_settings.json"

    def load(self) -> dict:
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    merged = {**DEFAULTS, **json.load(f)}
                return _sanitize(merged, DEFAULTS)
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
