"""Pure Real-ESRGAN model-manager helpers (requires torch for `realesrgan_models` import)."""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from core.realesrgan_models import (  # noqa: E402  (after importorskip)
    model_filename_for_net_scale,
    net_scale_for_user_scale,
)


@pytest.mark.parametrize(
    ("user_scale", "expected_net"),
    [(1.0, 2), (2.0, 2), (2.01, 4), (3.0, 4), (4.0, 4)],
)
def test_net_scale_for_user_scale(user_scale: float, expected_net: int):
    assert net_scale_for_user_scale(user_scale) == expected_net


def test_model_filename_for_net_scale():
    assert model_filename_for_net_scale(2) == "RealESRGAN_x2plus.pth"
    assert model_filename_for_net_scale(4) == "RealESRGAN_x4plus.pth"
