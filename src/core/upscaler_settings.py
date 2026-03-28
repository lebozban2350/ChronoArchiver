"""Persistent AI Image Upscaler (Z-Image) panel options under Settings/z_image_pro_upscaler/ (same tree as models)."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .debug_logger import UTILITY_APP, debug
except ImportError:
    from core.debug_logger import UTILITY_APP, debug

DEFAULTS: dict = {
    "source_image": "",
    "save_fmt": "PNG",
    "beautify": False,
}


def _sanitize(data: dict, defaults: dict) -> dict:
    out = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    p = str(out.get("source_image", "")).strip()
    out["source_image"] = p
    sf = str(out.get("save_fmt", "PNG")).strip().upper()
    out["save_fmt"] = sf if sf in ("PNG", "JPG") else "PNG"
    out["beautify"] = bool(out.get("beautify", DEFAULTS["beautify"]))
    return out


class UpscalerPanelSettings:
    """JSON panel state next to HF models (encoder-style persistence)."""

    def __init__(self, z_image_settings_dir: Path):
        self._dir = Path(z_image_settings_dir)
        self.config_path = self._dir / "panel_settings.json"

    def load(self) -> dict:
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    merged = {**DEFAULTS, **json.load(f)}
                return _sanitize(merged, DEFAULTS)
            except (json.JSONDecodeError, OSError, TypeError) as e:
                debug(UTILITY_APP, f"Upscaler panel settings load failed, using defaults: {e}")
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
            debug(UTILITY_APP, f"Upscaler panel settings save failed: {e}")
