"""Download / locate Real-ESRGAN official RRDB weights (x2plus, x4plus)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.realesrgan_runner import (
    invalidate_rrdb_checkpoint_cache,
    validate_rrdb_rgb_checkpoint_file,
)

# Official release assets (xinntao/Real-ESRGAN)
X2PLUS_NAME = "RealESRGAN_x2plus.pth"
X4PLUS_NAME = "RealESRGAN_x4plus.pth"
X2PLUS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
X4PLUS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"

APPROX_X2_BYTES = 67 * 1024 * 1024
APPROX_X4_BYTES = 67 * 1024 * 1024

_MIN_VALID_BYTES = 8 * 1024 * 1024
_DOWNLOAD_TIMEOUT_SEC = 360

_log = logging.getLogger("ChronoArchiver.realesrgan")


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
        if p.stat().st_size <= _MIN_VALID_BYTES:
            return False
        ok, err, quarantine = validate_rrdb_rgb_checkpoint_file(p)
        if ok:
            return True
        if quarantine:
            invalidate_rrdb_checkpoint_cache(p)
            bad = p.with_name(p.name + ".bad")
            try:
                if bad.is_file():
                    bad.unlink()
                p.rename(bad)
                _log.warning(
                    "Moved invalid Real-ESRGAN checkpoint aside (%s): %s",
                    bad,
                    err,
                )
            except OSError as e:
                _log.warning(
                    "Invalid Real-ESRGAN checkpoint but could not quarantine %s: %s (%s)",
                    p,
                    err,
                    e,
                )
        else:
            _log.warning("Real-ESRGAN checkpoint check failed (not quarantining): %s: %s", p, err)
        return False

    def download(
        self,
        net_scale: int,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> tuple[bool, str]:
        """Download one checkpoint. Returns (ok, error_message)."""
        self._cancel.clear()
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"cannot create models folder: {e}"

        url = model_url_for_net_scale(net_scale)
        dest = self.path_for_net_scale(net_scale)
        temp = dest.with_suffix(".partial")
        try:
            if temp.is_file():
                temp.unlink()
        except OSError:
            pass

        req = Request(url, headers={"User-Agent": "ChronoArchiver/Real-ESRGAN (weights)"})
        est = expected_bytes(net_scale)
        downloaded = 0
        try:
            with urlopen(req, timeout=_DOWNLOAD_TIMEOUT_SEC) as resp:
                code = getattr(resp, "status", None) or getattr(resp, "code", 200)
                if code != 200:
                    return False, f"HTTP {code}"
                cl = resp.headers.get("Content-Length") if resp.headers else None
                try:
                    total = int(cl) if cl is not None and str(cl).strip().isdigit() else est
                except (TypeError, ValueError):
                    total = est
                if total <= 0:
                    total = est

                block = 256 * 1024
                with open(temp, "wb") as f:
                    while not self._cancel.is_set():
                        chunk = resp.read(block)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(url, downloaded, total)
        except HTTPError as e:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            return False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            reason = e.reason if getattr(e, "reason", None) else str(e)
            return False, f"network: {reason}"
        except OSError as e:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            return False, str(e)

        if self._cancel.is_set():
            try:
                temp.unlink()
            except OSError:
                pass
            return False, "cancelled"

        if downloaded < _MIN_VALID_BYTES:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            return False, f"download too small ({downloaded} bytes) — check connection or URL"

        try:
            temp.replace(dest)
        except OSError as e:
            try:
                if temp.is_file():
                    temp.unlink()
            except OSError:
                pass
            return False, f"could not save file: {e}"

        if not self.is_ready(net_scale):
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass
            return False, "saved file failed size check (corrupt or wrong content)"

        return True, ""

    def ensure_weights(
        self,
        scales: tuple[int, ...] = (2, 4),
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> tuple[bool, str]:
        """Download any missing checkpoints in ``scales``. Progress callback: (filename, downloaded, total)."""
        for ns in scales:
            if self._cancel.is_set():
                return False, "cancelled"
            if self.is_ready(ns):
                continue
            name = model_filename_for_net_scale(ns)

            def _wrap(url: str, d: int, t: int, _name: str = name) -> None:
                if progress_cb:
                    progress_cb(_name, d, t)

            ok, err = self.download(ns, _wrap)
            if not ok:
                return False, err or f"failed: {name}"
        return True, ""
