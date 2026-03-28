"""Tier 1: import smoke — no Qt. ML modules require torch (optional in CI)."""

from __future__ import annotations

import pytest


def test_import_app_paths():
    import core.app_paths  # noqa: F401


def test_import_video_target_presets():
    import core.video_target_presets  # noqa: F401


def test_import_debug_logger():
    import core.debug_logger  # noqa: F401


def test_import_realesrgan_stack_if_torch():
    pytest.importorskip("torch")
    import core.rrdbnet  # noqa: F401
    import core.realesrgan_runner  # noqa: F401
    import core.realesrgan_models  # noqa: F401
