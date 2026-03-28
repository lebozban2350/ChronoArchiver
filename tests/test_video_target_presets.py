"""Pure helpers from `core.video_target_presets` — no I/O."""

from __future__ import annotations

from core.video_target_presets import (
    VIDEO_TARGET_PRESETS,
    VideoTargetPreset,
    aspect_ratio_label,
    source_display_parts,
    source_long_edge,
    source_video_caption_line,
)


def test_source_long_edge():
    assert source_long_edge(1920, 1080) == 1920
    assert source_long_edge(1080, 1920) == 1920


def test_aspect_ratio_label_common():
    assert aspect_ratio_label(1920, 1080) == "16:9"
    assert aspect_ratio_label(640, 480) == "4:3"


def test_aspect_ratio_label_zero():
    assert aspect_ratio_label(0, 100) == "—"


def test_source_display_parts_exact_preset():
    cn, px, ar = source_display_parts(1920, 1080)
    assert cn == "1080p (FHD)"
    assert px == "1920×1080"
    assert ar == "16:9"


def test_source_display_parts_custom_dimensions():
    cn, px, ar = source_display_parts(1234, 567)
    assert cn == "Custom"
    assert px == "1234×567"
    assert ":" in ar


def test_source_video_caption_line():
    line = source_video_caption_line(1920, 1080)
    assert "Source" in line or "1920" in line


def test_video_target_preset_combo_label():
    p = VideoTargetPreset("uhd_4k", "4K / 2160p (UHD)", 3840, 2160, "16:9")
    assert "3840×2160" in p.combo_label()
    assert p.long_edge == 3840


def test_presets_have_sane_long_edges():
    """Preset tuple is UI-ordered (not strictly sorted: e.g. DCI 2K vs QHD cross)."""
    edges = [p.long_edge for p in VIDEO_TARGET_PRESETS]
    assert len(edges) == len(set(edges))
    assert all(e > 0 for e in edges)
