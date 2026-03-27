"""Persistent Z-Image upscaler panel options under Settings/z_image_pro_upscaler/ (same tree as models)."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .debug_logger import UTILITY_APP, debug
except ImportError:
    from core.debug_logger import UTILITY_APP, debug

DEFAULT_PROMPT = ""

DEFAULTS: dict = {
    "source_image": "",
    "prompt": DEFAULT_PROMPT,
    # Lower default to preserve source while still allowing prompt edits.
    "strength": 0.35,
    "steps": 9,
    "cfg": 6.0,
    "scale_index": 0,
    "max_edge": 2048,
    "save_fmt": "PNG",
}


def _sanitize(data: dict, defaults: dict) -> dict:
    out = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    p = str(out.get("source_image", "")).strip()
    out["source_image"] = p
    # Empty prompt is valid: cleanup/upscale-only mode without prompt-driven edits.
    out["prompt"] = str(out.get("prompt", defaults["prompt"]) or "").strip()
    try:
        st = float(out.get("strength", defaults["strength"]))
    except (TypeError, ValueError):
        st = float(defaults["strength"])
    out["strength"] = max(0.15, min(0.85, st))
    try:
        stp = int(out.get("steps", defaults["steps"]))
    except (TypeError, ValueError):
        stp = int(defaults["steps"])
    out["steps"] = max(4, min(16, stp))
    try:
        cfg = float(out.get("cfg", defaults["cfg"]))
    except (TypeError, ValueError):
        cfg = float(defaults["cfg"])
    out["cfg"] = max(0.0, min(12.0, cfg))
    try:
        si = int(out.get("scale_index", defaults["scale_index"]))
    except (TypeError, ValueError):
        si = int(defaults["scale_index"])
    out["scale_index"] = max(0, min(2, si))
    try:
        me = int(out.get("max_edge", defaults["max_edge"]))
    except (TypeError, ValueError):
        me = int(defaults["max_edge"])
    out["max_edge"] = max(512, min(8192, me))
    # snap to 64 per spinbox
    out["max_edge"] = max(512, min(8192, (out["max_edge"] // 64) * 64))
    sf = str(out.get("save_fmt", "PNG")).strip().upper()
    out["save_fmt"] = sf if sf in ("PNG", "JPG") else "PNG"
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
