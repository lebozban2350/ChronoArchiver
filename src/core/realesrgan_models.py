"""Download / locate Real-ESRGAN official RRDB weights (x2plus, x4plus)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from urllib.request import Request, urlopen

# Official release assets (xinntao/Real-ESRGAN)
X2PLUS_NAME = "RealESRGAN_x2plus.pth"
X4PLUS_NAME = "RealESRGAN_x4plus.pth"
X2PLUS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
X4PLUS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"

APPROX_X2_BYTES = 67 * 1024 * 1024
APPROX_X4_BYTES = 67 * 1024 * 1024


def net_scale_for_user_scale(user_scale: float | int) -> int:
    """Use x2 weights for 2× target; x4 for 3× and 4× (with resize after net for 3×)."""
    u = float(user_scale)
    if u <= 2.0 + 1e-6:
        return 2
    return 4


def model_filename_for_net_scale(net_scale: int) -> str:
    return X2PLUS_NAME if net_scale == 2 else X4PLUS_NAME


def model_url_for_net_scale(net_scale: int) -> str:
    return X2PLUS_URL if net_scale == 2 else X4PLUS_URL


def expected_bytes(net_scale: int) -> int:
    return APPROX_X2_BYTES if net_scale == 2 else APPROX_X4_BYTES


class RealESRGANModelManager:
    def __init__(self, models_root: Path) -> None:
        self._root = models_root
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def path_for_net_scale(self, net_scale: int) -> Path:
        return self._root / model_filename_for_net_scale(net_scale)

    def is_ready(self, net_scale: int) -> bool:
        p = self.path_for_net_scale(net_scale)
        if not p.is_file():
            return False
        return p.stat().st_size > 8 * 1024 * 1024

    def download(
        self,
        net_scale: int,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> bool:
        self._cancel.clear()
        self._root.mkdir(parents=True, exist_ok=True)
        url = model_url_for_net_scale(net_scale)
        dest = self.path_for_net_scale(net_scale)
        temp = dest.with_suffix(".partial")
        try:
            if temp.is_file():
                temp.unlink()
        except OSError:
            pass

        req = Request(url, headers={"User-Agent": "ChronoArchiver/RealESRGAN"})
        total = expected_bytes(net_scale)
        downloaded = 0
        try:
            with urlopen(req, timeout=120) as resp:
                block = 1024 * 256
                with open(temp, "wb") as f:
                    while not self._cancel.is_set():
                        chunk = resp.read(block)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(url, downloaded, total)
        except OSError:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            return False

        if self._cancel.is_set():
            try:
                temp.unlink()
            except OSError:
                pass
            return False

        try:
            temp.replace(dest)
        except OSError:
            return False
        return self.is_ready(net_scale)
