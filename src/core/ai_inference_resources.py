"""
VRAM / RAM baselines for AI panels (community + upstream guidance).

- Real-ESRGAN: tiling exists specifically to reduce VRAM; xinntao docs suggest lowering
  ``--tile`` on OOM. Users report ~4GB-class GPUs working with moderate tiles/resolution
  (see xinntao/Real-ESRGAN issues).
- Z-Image-Turbo (diffusers): heavy diffusion pipeline; app installer text already cites
  ~8–16GB GDDR for practical CUDA (see ``pytorch_installer_vram_guidance``).
"""

from __future__ import annotations

USER_MSG_CUDA_OOM = (
    "Not enough GPU memory (VRAM) to run this step. Close other GPU apps, reduce "
    "input resolution or max output size, or try again after freeing VRAM."
)

# Log / console detail (debug + panel ERROR lines).
REALESRGAN_VRAM_BASELINE_LOG = (
    "Real-ESRGAN (tiled): typical minimum ~4GB free VRAM for 1080p-class frames with "
    "tile≈400; OOM means reduce resolution/tile or use CPU if available."
)

ZIMAGE_VRAM_BASELINE_LOG = (
    "Z-Image-Turbo (CUDA): practical minimum often ~8GB GDDR for moderate sizes; "
    "16GB+ for larger outputs — lower max edge if you hit OOM."
)
