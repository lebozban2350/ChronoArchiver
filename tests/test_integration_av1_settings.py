"""AV1 settings with isolated install root."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import app_paths

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "fake_install"
    root.mkdir()
    monkeypatch.setenv(app_paths.ENV_INSTALL_ROOT, str(root))


def test_av1_defaults_fresh_config():
    from core.av1_settings import AV1Settings

    s = AV1Settings()
    assert s.get("quality") == 30
    assert s.get("preset") == "p4"
    assert s.get("existing_output") == "overwrite"
