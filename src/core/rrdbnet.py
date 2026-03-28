# RRDBNet architecture for Real-ESRGAN x2/x4 checkpoints (MIT License, xinntao/Real-ESRGAN).

from __future__ import annotations

import torch
from torch import nn


def _make_layer(block: type[nn.Module], n_layers: int) -> nn.Sequential:
    return nn.Sequential(*[block() for _ in range(n_layers)])


def pixel_unshuffle(x: torch.Tensor, scale: int) -> torch.Tensor:
    """Pixel unshuffle (BasicSR / xinntao Real-ESRGAN). Downsample spatially, multiply channels."""
    b, c, hh, hw = x.size()
    out_channel = c * (scale**2)
    assert hh % scale == 0 and hw % scale == 0, "H/W must be divisible by unshuffle scale"
    h = hh // scale
    w = hw // scale
    x_view = x.view(b, c, h, scale, w, scale)
    return x_view.permute(0, 1, 3, 5, 2, 4).reshape(b, out_channel, h, w)


class ResidualDenseBlock_5C(nn.Module):
    """Multi-column dense block used inside RRDB."""

    def __init__(self, nf: int = 64, gc: int = 32, bias: bool = True) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1, bias=bias)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1, bias=bias)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1, bias=bias)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1, bias=bias)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1, bias=bias)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf: int, gc: int = 32) -> None:
        super().__init__()
        self.rdb1 = ResidualDenseBlock_5C(nf, gc)
        self.rdb2 = ResidualDenseBlock_5C(nf, gc)
        self.rdb3 = ResidualDenseBlock_5C(nf, gc)

    def forward(self, x):
        out = self.rdb1(x)
        out = self.rdb2(out)
        out = self.rdb3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """Generator matching RealESRGAN_x2plus / x4plus official weights (BasicSR RRDBNet layout)."""

    def __init__(
        self,
        num_in_ch: int = 3,
        num_out_ch: int = 3,
        num_feat: int = 64,
        num_block: int = 23,
        num_grow_ch: int = 32,
        scale: int = 4,
    ) -> None:
        super().__init__()
        self.scale = scale
        # x2 checkpoints use pixel_unshuffle(2) so conv_first expects 4× RGB channels (12); x4 uses 3.
        eff_in_ch = num_in_ch * 4 if scale == 2 else num_in_ch
        self.conv_first = nn.Conv2d(eff_in_ch, num_feat, 3, 1, 1)
        self.body = _make_layer(lambda: RRDB(num_feat, num_grow_ch), num_block)
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        if scale not in (2, 4):
            raise ValueError(f"RRDBNet scale must be 2 or 4, got {scale}")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = pixel_unshuffle(x, 2) if self.scale == 2 else x
        fea = self.conv_first(feat)
        trunk = self.conv_body(self.body(fea))
        fea = fea + trunk
        fea = self.lrelu(self.conv_up1(self.upsample(fea)))
        fea = self.lrelu(self.conv_up2(self.upsample(fea)))
        out = self.conv_last(self.lrelu(self.conv_hr(fea)))
        return out
