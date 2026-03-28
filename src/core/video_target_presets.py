"""
Standard video output tiers for AI Video Upscaler (common name, pixel size, aspect label).

Target scale is applied uniformly from source dimensions so aspect ratio is preserved;
the preset's long edge defines the tier (same idea as matching 720p/1080p/4K delivery).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoTargetPreset:
    """One industry-style row: display strings + pixel box (landscape width × height)."""

    key: str
    common_name: str
    width: int
    height: int
    aspect_label: str

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    def combo_label(self) -> str:
        """Format: Common Name, Pixel Size, Aspect Ratio"""
        return f"{self.common_name}, {self.width}×{self.height}, {self.aspect_label}"


# UI order (roughly by tier; not strictly ascending long-edge — e.g. QHD 1440p before DCI 2K).
VIDEO_TARGET_PRESETS: tuple[VideoTargetPreset, ...] = (
    VideoTargetPreset("sd_480p", "480p (SD)", 640, 480, "4:3"),
    VideoTargetPreset("hd_720p", "720p (HD)", 1280, 720, "16:9"),
    VideoTargetPreset("fhd_1080p", "1080p (FHD)", 1920, 1080, "16:9"),
    VideoTargetPreset("qhd_1440p", "1440p (QHD)", 2560, 1440, "16:9"),
    VideoTargetPreset("dci_2k", "2K (DCI)", 2048, 1080, "1:1.77"),
    VideoTargetPreset("uhd_4k", "4K / 2160p (UHD)", 3840, 2160, "1:1.9"),
    VideoTargetPreset("uhd_8k", "8K / 4320p", 7680, 4320, "16:9"),
)


def source_long_edge(width: int, height: int) -> int:
    return max(int(width), int(height))


def aspect_ratio_label(width: int, height: int) -> str:
    """Reduced integer ratio (landscape form), e.g. 1920×1080 → 16:9."""
    w, h = abs(int(width)), abs(int(height))
    if w == 0 or h == 0:
        return "—"
    g = math.gcd(w, h)
    a, b = w // g, h // g
    if a < b:
        a, b = b, a
    return f"{a}:{b}"


def source_display_parts(width: int, height: int) -> tuple[str, str, str]:
    """
    Same three parts as target presets: common name, pixel size (W×H), aspect label.
    Used for the Original preview caption.
    """
    w, h = int(width), int(height)
    pixel_str = f"{w}×{h}"
    if w <= 0 or h <= 0:
        return ("—", "—", "—")
    for p in VIDEO_TARGET_PRESETS:
        if (w, h) == (p.width, p.height) or (w, h) == (p.height, p.width):
            return (p.common_name, pixel_str, p.aspect_label)
    ar = aspect_ratio_label(w, h)
    return ("Custom", pixel_str, ar)


def source_video_caption_line(width: int, height: int) -> str:
    """One line: Source Video: Common Name, W×H, aspect."""
    cn, px, ar = source_display_parts(width, height)
    if cn == "—":
        return ""
    return f"Source Video: {cn}, {px}, {ar}"


def presets_above_source(src_w: int, src_h: int) -> list[VideoTargetPreset]:
    """Presets strictly larger than the source (by long edge)."""
    ls = source_long_edge(src_w, src_h)
    return [p for p in VIDEO_TARGET_PRESETS if p.long_edge > ls]


def user_scale_for_preset(src_w: int, src_h: int, preset: VideoTargetPreset) -> float:
    """Uniform scale so max(output w,h) matches preset long edge (aspect preserved)."""
    ls = source_long_edge(src_w, src_h)
    if ls <= 0:
        return 1.0
    return float(preset.long_edge) / float(ls)


def default_target_long_edge_for_migration(old_scale_index: int) -> int:
    """Map legacy 0=2× / 1=3× / 2=4× indices to a reasonable default long edge."""
    # Rough mapping to tiers: 2× → 720p tier, 3× → 1080p tier, 4× → 4K tier
    m = {0: 1280, 1: 1920, 2: 3840}
    return m.get(max(0, min(2, old_scale_index)), 3840)
