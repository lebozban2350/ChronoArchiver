"""
Local vs remote (SFTP/SSH) path picker — opened from Browse; main panel layout unchanged.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core.remote_ssh import (
    is_remote_path,
    parse_remote_destination,
    run_ssh_echo_ok_test,
    to_sftp_folder_uri,
)


def run_local_remote_path_dialog(parent, title: str, initial_path: str = "") -> str | None:
    """
    Show local-folder vs remote SFTP/SSH picker. Returns a local filesystem path or
    ``sftp://…/`` URI, or None if cancelled.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(440)
    v = QVBoxLayout(dlg)

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
    le_pw = QLineEdit()
    le_pw.setEchoMode(QLineEdit.EchoMode.Password)
    le_pw.setPlaceholderText("SSH password if needed (not saved; use keys for unattended runs)")
    le_pw.setMinimumHeight(28)

    btn_test_ssh = QPushButton("Test SSH")
    btn_test_ssh.setMinimumHeight(28)
    btn_test_ssh.setToolTip(
        "Runs echo ok on the remote host using the path and password above "
        "(SSH keys, sshpass, or GUI askpass)."
    )
    pw_wrap = QWidget()
    pw_h = QHBoxLayout(pw_wrap)
    pw_h.setContentsMargins(0, 0, 0, 0)
    pw_h.setSpacing(8)
    pw_h.addWidget(le_pw, 1)
    pw_h.addWidget(btn_test_ssh, 0)

    btn_browse = QPushButton("Browse…")
    btn_browse.setMinimumHeight(28)
    path_row = QHBoxLayout()
    path_row.addWidget(le_path, 1)
    path_row.addWidget(btn_browse, 0)
    v.addLayout(path_row)
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

    def browse_local() -> None:
        start = le_path.text().strip()
        if is_remote_path(start):
            start = str(Path.home())
        pick = start or str(Path.home())
        d = QFileDialog.getExistingDirectory(dlg, "Select folder", pick)
        if d:
            le_path.setText(d)

    def do_test_ssh() -> None:
        ok, msg = run_ssh_echo_ok_test(le_path.text(), le_pw.text(), batch_mode=False)
        if ok:
            QMessageBox.information(dlg, "SSH test", msg)
        else:
            QMessageBox.warning(dlg, "SSH test", msg)

    rb_local.toggled.connect(lambda _c: sync_mode())
    rb_remote.toggled.connect(lambda _c: sync_mode())
    btn_browse.clicked.connect(browse_local)
    btn_test_ssh.clicked.connect(do_test_ssh)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    sync_mode()

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None

    raw = le_path.text().strip()
    if not raw:
        QMessageBox.warning(parent, title, "Enter a path.")
        return None

    if rb_local.isChecked():
        if is_remote_path(raw):
            QMessageBox.warning(
                parent,
                title,
                "That looks like a remote path. Choose “Remote (SSH / SFTP)” instead.",
            )
            return None
        return raw

    rmt, _ = parse_remote_destination(raw)
    if rmt is None:
        QMessageBox.warning(
            parent,
            title,
            "Remote path not recognized. Use user@host:/path or sftp://user@host/path.",
        )
        return None
    return to_sftp_folder_uri(rmt)
