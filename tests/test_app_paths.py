"""`core.app_paths` behavior with a fake install root."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import app_paths


def test_install_root_none_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(app_paths.ENV_INSTALL_ROOT, raising=False)
    assert app_paths.install_root() is None
    assert app_paths.uses_install_layout() is False


def test_paths_under_chronoarchiver_install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "fake_install"
    root.mkdir()
    monkeypatch.setenv(app_paths.ENV_INSTALL_ROOT, str(root))

    assert app_paths.install_root() == root
    assert app_paths.uses_install_layout() is True
    assert app_paths.data_dir() == root

    sd = app_paths.settings_dir()
    assert sd == root / "Settings"
    assert sd.is_dir()

    ld = app_paths.logs_dir()
    assert ld == root / "Logs"
    assert ld.is_dir()

    md = app_paths.models_dir()
    assert md == root / "Settings" / "models"
    assert md.is_dir()
