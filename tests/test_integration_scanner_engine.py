"""Scanner engine wiring (no full model inference)."""

from __future__ import annotations

import pytest

from core.scanner import OPENCV_AVAILABLE, ScannerEngine

pytestmark = pytest.mark.integration


def test_scanner_engine_instantiates():
    eng = ScannerEngine(logger_callback=lambda _x: None)
    assert eng.stop_event is not None
    assert OPENCV_AVAILABLE in (True, False)
