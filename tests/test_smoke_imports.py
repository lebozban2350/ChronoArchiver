"""Minimal import smoke — no media, no GPU. Keeps CI fast."""

from __future__ import annotations


def test_import_app_paths():
    import core.app_paths  # noqa: F401


def test_import_debug_logger():
    import core.debug_logger  # noqa: F401


def test_import_video_target_presets():
    import core.video_target_presets  # noqa: F401


def test_import_fs_task_lock():
    import core.fs_task_lock  # noqa: F401


def test_import_zimage_portrait():
    import core.zimage_portrait  # noqa: F401


def test_import_realesrgan_stack_if_torch():
    import pytest

    torch = pytest.importorskip("torch")
    assert torch is not None
    import core.rrdbnet  # noqa: F401
    import core.realesrgan_runner  # noqa: F401
    import core.realesrgan_models  # noqa: F401
