"""
Local vs remote (SFTP/SSH) path picker — shared by Browse across ChronoArchiver panels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.remote_ssh import (
    is_remote_path,
    parse_remote_destination,
    run_ssh_echo_ok_test,
    to_sftp_folder_uri,
)

from version import APP_NAME

# Callers should use these so window titles and copy stay consistent app-wide.
RemoteBrowsePurpose = Literal["source", "target", "target_optional", "library"]

_PURPOSE_LABEL: dict[str, str] = {
    "source": "Source folder",
    "target": "Target folder",
    "target_optional": "Target folder (optional)",
    "library": "Media library",
}

_PURPOSE_HINT: dict[str, str] = {
    "source": "Choose where media to process is stored.",
    "target": "Choose where outputs will be written.",
    "target_optional": "Optional output location; leave blank in the panel if unused.",
    "library": "Choose the image folder the scanner indexes.",
}


def remote_browse_window_title(purpose: RemoteBrowsePurpose) -> str:
    """Stable title for the local/remote browse dialog (window bar)."""
    role = _PURPOSE_LABEL.get(purpose, _PURPOSE_LABEL["source"])
    return f"{APP_NAME} — {role}"


def run_local_remote_path_dialog(
    parent,
    initial_path: str = "",
    *,
    purpose: RemoteBrowsePurpose = "source",
) -> tuple[str | None, str]:
    """
    Show the standard local-folder vs remote SFTP/SSH picker used by all panels.

    Returns ``(path, ssh_password_plain)``. ``path`` is a local directory, an ``sftp://…/``
    URI, or ``None`` if cancelled. The password is the remote-mode field at OK time (empty
    string for local folder or empty field); callers should copy it to any panel SSH field
    so background jobs match what **Test SSH** used.

    Parameters
    ----------
    purpose
        Drives the window title and short hint only; validation rules are unchanged.
    """
    title = remote_browse_window_title(purpose)
    hint = _PURPOSE_HINT.get(purpose, _PURPOSE_HINT["source"])

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(480)
    dlg.setStyleSheet("QDialog { background: #0c0c0c; color: #e5e7eb; }")

    v = QVBoxLayout(dlg)
    v.setContentsMargins(10, 10, 10, 12)
    v.setSpacing(6)
    intro = QLabel(
        f"{hint} Use a local folder or an SSH/SFTP path. Password is not saved; prefer keys for unattended runs."
    )
    intro.setWordWrap(True)
    intro.setStyleSheet("font-size: 10px; color: #9ca3af;")
    v.addWidget(intro)

    rb_local = QRadioButton("Local folder")
    rb_remote = QRadioButton("Remote (SSH / SFTP)")
    bg = QButtonGroup(dlg)
    bg.addButton(rb_local)
    bg.addButton(rb_remote)
    init = (initial_path or "").strip()
    if init and is_remote_path(init):
        rb_remote.setChecked(True)
    else:
        rb_local.setChecked(True)

    row_kind = QHBoxLayout()
    row_kind.addWidget(rb_local)
    row_kind.addWidget(rb_remote)
    row_kind.addStretch(1)
    v.addLayout(row_kind)

    le_path = QLineEdit()
    le_path.setMinimumHeight(28)
    le_path.setPlaceholderText("e.g. /home/you/Documents/")
    le_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    le_pw = QLineEdit()
    le_pw.setEchoMode(QLineEdit.EchoMode.Password)
    le_pw.setPlaceholderText("SSH password if needed (not saved; use keys for unattended runs)")
    le_pw.setMinimumHeight(28)
    le_pw.setMinimumWidth(120)
    le_pw.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    btn_test_ssh = QPushButton("Test SSH")
    btn_test_ssh.setMinimumHeight(28)
    btn_test_ssh.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn_test_ssh.setToolTip(
        "Runs echo ok on the remote host using the path and password above "
        "(SSH keys, sshpass, or GUI askpass). On OK, the same password is copied to the panel "
        "SSH field so scans and batch jobs use it."
    )
    pw_wrap = QWidget()
    pw_h = QHBoxLayout(pw_wrap)
    pw_h.addWidget(le_pw, 1)
    pw_h.addWidget(btn_test_ssh, 0)

    btn_browse = QPushButton("Browse…")
    btn_browse.setMinimumHeight(28)
    btn_browse.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    path_row = QHBoxLayout()
    path_row.setSpacing(8)
    path_row.addWidget(le_path, 1)
    path_row.addWidget(btn_browse, 0)
    v.addLayout(path_row)
    pw_h.setContentsMargins(0, 0, 0, 0)
    pw_h.setSpacing(8)
    v.addWidget(pw_wrap)

    bb = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    v.addWidget(bb)
    le_path.setText(init)

    def sync_mode() -> None:
        loc = rb_local.isChecked()
        btn_browse.setVisible(loc)
        pw_wrap.setVisible(not loc)
        if loc:
            le_path.setPlaceholderText("e.g. /home/you/Documents/")
        else:
            le_path.setPlaceholderText("e.g. sftp://user@192.168.1.10/mnt/share/ or user@host:/mnt/share/")
        dlg.adjustSize()

    def browse_local() -> None:
        start = le_path.text().strip()
        if is_remote_path(start):
            start = str(Path.home())
        pick = start or str(Path.home())
        d = QFileDialog.getExistingDirectory(dlg, f"{APP_NAME} — Local folder", pick)
        if d:
            le_path.setText(d)

    def do_test_ssh() -> None:
        ok, msg = run_ssh_echo_ok_test(le_path.text(), le_pw.text(), batch_mode=False)
        if ok:
            QMessageBox.information(dlg, f"{APP_NAME} — SSH test", msg)
        else:
            QMessageBox.warning(dlg, f"{APP_NAME} — SSH test", msg)

    rb_local.toggled.connect(lambda _c: sync_mode())
    rb_remote.toggled.connect(lambda _c: sync_mode())
    btn_browse.clicked.connect(browse_local)
    btn_test_ssh.clicked.connect(do_test_ssh)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    sync_mode()

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None, ""

    raw = le_path.text().strip()
    if not raw:
        QMessageBox.warning(parent, title, "Enter a path.")
        return None, ""

    if rb_local.isChecked():
        if is_remote_path(raw):
            QMessageBox.warning(
                parent,
                title,
                "That looks like a remote path. Choose “Remote (SSH / SFTP)” instead.",
            )
            return None, ""
        return raw, ""

    rmt, _ = parse_remote_destination(raw)
    if rmt is None:
        QMessageBox.warning(
            parent,
            title,
            "Remote path not recognized. Use user@host:/path or sftp://user@host/path.",
        )
        return None, ""
    return to_sftp_folder_uri(rmt), le_pw.text()
