"""ML runtime probe (torch/diffusers optional)."""

from __future__ import annotations

import pytest

from core.ml_runtime import check_ml_runtime

pytestmark = pytest.mark.integration


def test_check_ml_runtime_returns_tuple():
    ok, reason = check_ml_runtime()
    assert isinstance(ok, bool)
    assert isinstance(reason, str) and len(reason) >= 2
    # Reasons include ok, missing_torch, missing_diffusers, no_cuda, import_error (see ml_runtime.check_ml_runtime).
