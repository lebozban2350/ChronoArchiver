"""Minimal Qt lifecycle (offscreen). Requires PySide6 from ``requirements.txt``."""

from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture(scope="module")
def qapplication():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_qapplication_singleton(qapplication):
    assert QApplication.instance() is qapplication


def test_widget_show_process_events(qapplication):
    w = QWidget()
    lab = QLabel("chrono-test", w)
    lab.show()
    w.show()
    qapplication.processEvents()
    assert lab.text() == "chrono-test"
