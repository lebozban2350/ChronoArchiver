"""RRDBNet forward pass without weights (torch required)."""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402

from core.rrdbnet import RRDBNet  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scale", [2, 4])
def test_rrdbnet_forward_random_rgb(scale: int):
    m = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=scale)
    m.eval()
    x = torch.randn(1, 3, 32, 32)
    with torch.no_grad():
        y = m(x)
    assert y.shape[0] == 1
    assert y.shape[1] == 3
    assert y.shape[2] == scale * 32
    assert y.shape[3] == scale * 32
