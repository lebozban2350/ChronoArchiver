"""
Automatic Z-Image img2img parameters (scale, max edge, strength, steps, CFG).

Heuristics from source size, portrait/beautify, and freckle hint only (no user prompt field).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZImageAutoParams:
    scale: int
    max_side: int
    strength: float
    steps: int
    cfg: float
    summary: str


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pick_scale_and_max_side(ow: int, oh: int) -> tuple[int, int]:
    """Smaller sources get higher integer scale; large sources stay conservative for VRAM."""
    m = max(int(ow), int(oh), 1)
    if m <= 480:
        scale, max_side = 4, 2048
    elif m <= 800:
        scale, max_side = 3, 2304
    elif m <= 1400:
        scale, max_side = 2, 2560
    elif m <= 2200:
        scale, max_side = 2, 2048
    else:
        scale, max_side = 2, 1792
    return scale, max_side


def infer_zimage_params(
    *,
    ow: int,
    oh: int,
    portrait_detected: bool = False,
    freckle_heavy: bool = False,
    beautify: bool = False,
) -> ZImageAutoParams:
    """
    :param ow, oh: Source image dimensions (pixels).
    :param portrait_detected: True when a face was found (used only with ``beautify``).
    :param freckle_heavy: Heuristic — small steps/CFG bump when Beautify + portrait.
    :param beautify: If True and a face exists, use soft beautify params; otherwise minimal-change upscale.
    """
    scale, max_side = _pick_scale_and_max_side(ow, oh)
    if beautify and portrait_detected:
        # Subtle img2img (~0.2–0.35 strength) + moderate CFG (~6–7): natural retouch, less color drift.
        strength = 0.26
        steps = 8
        cfg = 6.0
        if freckle_heavy:
            steps = min(9, steps + 1)
            cfg = min(6.5, cfg + 0.25)
            strength = _clamp(strength - 0.01, 0.24, 0.30)
        summary = (
            f"Beautify (subtle retouch){' + freckle hint' if freckle_heavy else ''}: "
            f"{scale}×, max edge {max_side}px, "
            f"strength={strength:.2f}, steps={steps}, cfg={cfg:.1f}"
        )
    else:
        # Beautify off or no face: maximum fidelity, minimal img2img drift.
        strength = 0.21
        steps = 6
        cfg = 0.0
        summary = (
            f"high-fidelity minimal-change upscale: {scale}×, max edge {max_side}px, "
            f"strength={strength:.2f}, steps={steps}, cfg=0"
        )
    return ZImageAutoParams(
        scale=scale,
        max_side=max_side,
        strength=strength,
        steps=steps,
        cfg=cfg,
        summary=summary,
    )
