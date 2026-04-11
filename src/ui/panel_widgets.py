"""
Shared Qt widgets helpers and panel QSS snippets for ChronoArchiver panels.

Keep behavior identical to the former per-panel copies — only import site changes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

# Primary START (#btnStart) — inline styles for guide pulse on Organizer, Scanner, Mass AV1 Encoder.
# Must not override QPushButton#btnStart:disabled or #btnStop when clearing after pulse.
GUIDE_PANEL_PRIMARY_START_IDLE_QSS = (
    "background-color:#10b981; color:#064e3b; border:2px solid #064e3b; font-size:10px; font-weight:900;"
)
GUIDE_PANEL_PRIMARY_START_PULSE_QSS = (
    "background-color:#10b981; color:#064e3b; border:2px solid #ef4444; font-size:10px; font-weight:900;"
)


def apply_guide_clear_primary_start_button(btn: QPushButton) -> None:
    """After guide pulse: restore idle green on enabled #btnStart, else clear so app QSS applies (disabled / STOP)."""
    if btn.objectName() == "btnStop" or not btn.isEnabled():
        btn.setStyleSheet("")
    else:
        btn.setStyleSheet(GUIDE_PANEL_PRIMARY_START_IDLE_QSS)


# Tight combo used by Mass AV1 Encoder, AI Image Upscaler, AI Video Upscaler (identical QSS).
COMBO_BOX_PANEL_QSS = (
    "QComboBox { font-size: 9px; padding: 0 4px; min-height: 12px; max-height: 16px; }"
    "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: right; width: 16px; }"
    "QComboBox QAbstractItemView { max-height: 160px; outline: none; padding: 0px; }"
)

# Compact spin row (image + video upscalers).
SPIN_BOX_COMPACT_QSS = "font-size:8px; padding-left:2px; padding-right:4px; min-height:18px; max-height:18px;"


def field_label(text: str, width: int) -> QLabel:
    w = QLabel(text)
    w.setObjectName("fieldLabel")
    w.setFixedWidth(width)
    w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w


def eng_row_btn_qss(w: int, h: int, fg: str, bd: str, bg: str = "transparent") -> str:
    """Fixed-size engine / model row buttons (AI Scanner, AI Image Upscaler, AI Video Upscaler)."""
    return (
        f"font-size:7px; font-weight:700; color:{fg}; background-color:{bg}; "
        f"border:2px solid {bd}; "
        f"min-width:{w}px; max-width:{w}px; min-height:{h}px; max-height:{h}px; padding:0px;"
    )


def path_browse_btn_qss(bar_h: int, btn_w: int, border: str, fg: str, *, border_px: int = 2) -> str:
    """Browse buttons: fixed box; idle vs guide pulse only swaps colors (no layout warp).

    Use border_px=1 for AI Image Upscaler browse button; default 2 matches encoder and scanner.
    """
    return (
        f"font-size:9px; font-weight:700; color:{fg}; border:{border_px}px solid {border}; "
        f"min-width:{btn_w}px; max-width:{btn_w}px; "
        f"min-height:{bar_h}px; max-height:{bar_h}px; padding:0px; margin:0px;"
    )


def format_net_speed(bytes_per_sec: float) -> str:
    """Human-readable throughput for installer pop-ups (B/s … GB/s)."""
    if bytes_per_sec < 0 or bytes_per_sec != bytes_per_sec:  # NaN
        return "—"
    if bytes_per_sec >= 1024**3:
        return f"{bytes_per_sec / (1024**3):.2f} GB/s"
    if bytes_per_sec >= 1024**2:
        return f"{bytes_per_sec / (1024**2):.1f} MB/s"
    if bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


def fmt_bytes(b: int) -> str:
    """Rough download / size estimate for installer copy (~GB, ~MB, …)."""
    if b <= 0:
        return "0 B"
    gb = b / (1024**3)
    if gb >= 0.1:
        return f"~{gb:.2f} GB"
    mb = b / (1024**2)
    if mb >= 0.1:
        return f"~{mb:.0f} MB"
    kb = b / 1024
    if kb >= 1:
        return f"~{kb:.0f} KB"
    return f"{b} B"


def pytorch_installer_vram_guidance() -> str:
    """GDDR / RAM note for PyTorch + diffusers installer pop-ups."""
    from core.venv_manager import get_ml_torch_install_variant

    if get_ml_torch_install_variant() == "cuda":
        return (
            "Recommended GDDR: ≥ 16 GB on NVIDIA for Z-Image-Turbo class CUDA inference (model guidance); "
            "8 GB GDDR may work with smaller max resolution — lower it if you hit OOM. "
            "Real-ESRGAN (tiled video upscale) often needs ~4+ GB free VRAM at 1080p-class frames; reduce resolution/tile on OOM."
        )
    return "CPU PyTorch: no GDDR. Prefer 32 GB+ system RAM for practical Z-Image runs; CPU is far slower than CUDA."
