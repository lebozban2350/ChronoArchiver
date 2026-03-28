"""Detect PyTorch / CUDA resource errors for user-friendly handling."""

from __future__ import annotations


def is_torch_cuda_oom(exc: BaseException | None) -> bool:
    """True for CUDA OOM (including torch.cuda.OutOfMemoryError and RuntimeError text)."""
    if exc is None:
        return False
    name = type(exc).__name__
    if "OutOfMemory" in name:
        return True
    s = str(exc).lower()
    if "out of memory" in s:
        return True
    return False
