"""Run Real-ESRGAN RRDB checkpoints (x2plus / x4plus) with optional tiling — adapted from xinntao/Real-ESRGAN (MIT)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from core.rrdbnet import RRDBNet


def _load_weights(model: torch.nn.Module, model_path: str | Path) -> None:
    loadnet = torch.load(str(model_path), map_location=torch.device("cpu"))
    if isinstance(loadnet, dict):
        if "params_ema" in loadnet:
            state = loadnet["params_ema"]
        elif "params" in loadnet:
            state = loadnet["params"]
        else:
            state = loadnet
    else:
        state = loadnet
    model.load_state_dict(state, strict=True)


class RealESRGANRunner:
    """BGR uint8 in/out; matches official enhance() behavior for RGB pipeline."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        net_scale: int,
        tile: int = 400,
        tile_pad: int = 10,
        pre_pad: int = 10,
        half: bool = True,
        device: torch.device | None = None,
    ) -> None:
        if net_scale not in (2, 4):
            raise ValueError("net_scale must be 2 or 4")
        self.net_scale = net_scale
        self.tile_size = tile
        self.tile_pad = tile_pad
        self.pre_pad = pre_pad
        self.mod_scale: int | None = None
        self.mod_pad_h = 0
        self.mod_pad_w = 0
        self.half = half and torch.cuda.is_available()

        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=net_scale)
        _load_weights(model, model_path)
        model.eval()
        self.model = model.to(self.device)
        if self.half:
            self.model = self.model.half()

        self.img: torch.Tensor | None = None
        self.output: torch.Tensor | None = None

    def _pre_process(self, img_rgb: np.ndarray) -> None:
        img = torch.from_numpy(np.transpose(img_rgb, (2, 0, 1))).float()
        self.img = img.unsqueeze(0).to(self.device)
        if self.half:
            self.img = self.img.half()

        if self.pre_pad != 0:
            self.img = F.pad(self.img, (0, self.pre_pad, 0, self.pre_pad), "reflect")

        if self.net_scale == 2:
            self.mod_scale = 2
        else:
            self.mod_scale = 4

        self.mod_pad_h, self.mod_pad_w = 0, 0
        assert self.img is not None
        _, _, h, w = self.img.size()
        if h % self.mod_scale != 0:
            self.mod_pad_h = self.mod_scale - h % self.mod_scale
        if w % self.mod_scale != 0:
            self.mod_pad_w = self.mod_scale - w % self.mod_scale
        if self.mod_pad_h or self.mod_pad_w:
            self.img = F.pad(self.img, (0, self.mod_pad_w, 0, self.mod_pad_h), "reflect")

    def _process(self) -> None:
        assert self.img is not None
        with torch.no_grad():
            self.output = self.model(self.img)

    def _tile_process(self) -> None:
        assert self.img is not None
        batch, channel, height, width = self.img.shape
        s = self.net_scale
        output_height = height * s
        output_width = width * s
        output_shape = (batch, channel, output_height, output_width)
        self.output = self.img.new_zeros(output_shape)
        tiles_x = math.ceil(width / self.tile_size)
        tiles_y = math.ceil(height / self.tile_size)

        for y in range(tiles_y):
            for x in range(tiles_x):
                ofs_x = x * self.tile_size
                ofs_y = y * self.tile_size
                input_start_x = ofs_x
                input_end_x = min(ofs_x + self.tile_size, width)
                input_start_y = ofs_y
                input_end_y = min(ofs_y + self.tile_size, height)

                input_start_x_pad = max(input_start_x - self.tile_pad, 0)
                input_end_x_pad = min(input_end_x + self.tile_pad, width)
                input_start_y_pad = max(input_start_y - self.tile_pad, 0)
                input_end_y_pad = min(input_end_y + self.tile_pad, height)

                input_tile_width = input_end_x - input_start_x
                input_tile_height = input_end_y - input_start_y

                input_tile = self.img[
                    :, :,
                    input_start_y_pad:input_end_y_pad,
                    input_start_x_pad:input_end_x_pad,
                ]

                with torch.no_grad():
                    output_tile = self.model(input_tile)

                output_start_x = input_start_x * s
                output_end_x = input_end_x * s
                output_start_y = input_start_y * s
                output_end_y = input_end_y * s

                output_start_x_tile = (input_start_x - input_start_x_pad) * s
                output_end_x_tile = output_start_x_tile + input_tile_width * s
                output_start_y_tile = (input_start_y - input_start_y_pad) * s
                output_end_y_tile = output_start_y_tile + input_tile_height * s

                assert self.output is not None
                self.output[:, :, output_start_y:output_end_y, output_start_x:output_end_x] = output_tile[
                    :, :,
                    output_start_y_tile:output_end_y_tile,
                    output_start_x_tile:output_end_x_tile,
                ]

    def _post_process(self) -> torch.Tensor:
        assert self.output is not None
        out = self.output
        if self.mod_scale is not None and (self.mod_pad_h or self.mod_pad_w):
            _, _, h, w = out.size()
            out = out[:, :, 0 : h - self.mod_pad_h * self.net_scale, 0 : w - self.mod_pad_w * self.net_scale]
        if self.pre_pad != 0:
            _, _, h, w = out.size()
            out = out[:, :, 0 : h - self.pre_pad * self.net_scale, 0 : w - self.pre_pad * self.net_scale]
        return out

    @torch.no_grad()
    def enhance(self, img_bgr: np.ndarray, *, user_scale: float | None = None) -> np.ndarray:
        """Upscale BGR image. user_scale: desired multiple vs input (e.g. 3.0 with x4 net resizes down)."""
        import cv2

        h_input, w_input = img_bgr.shape[0:2]
        img = img_bgr.astype(np.float32) / 255.0
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        self._pre_process(img)
        if self.tile_size > 0:
            self._tile_process()
        else:
            self._process()
        output_img = self._post_process()
        output_img = output_img.data.squeeze().float().cpu().clamp_(0, 1).numpy()
        output_img = np.transpose(output_img[[2, 1, 0], :, :], (1, 2, 0))
        output = (output_img * 255.0).round().astype(np.uint8)

        if user_scale is not None and abs(float(user_scale) - float(self.net_scale)) > 1e-6:
            output = cv2.resize(
                output,
                (int(w_input * user_scale), int(h_input * user_scale)),
                interpolation=cv2.INTER_LANCZOS4,
            )
        return output
