"""Parse SFTP/SSH-style remote paths and run lightweight SSH connectivity checks (OpenSSH)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

# Match subprocess watchdog to ConnectTimeout + margin (SafeCopi-style).
SSH_SUBPROCESS_MAX_RUNTIME_OVERHEAD_SEC: int = 120
SSH_TEST_CONNECT_TIMEOUT_SEC: int = 12

REMOTE_FS_UNSUPPORTED_HINT: str = (
    "SFTP/SSH paths are not supported for this job — mount the share locally (SSHFS, SMB, etc.) "
    "or copy files, then choose a local folder."
)

_RSYNC_REMOTE = re.compile(r"^(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<path>.+)$")
_URL_REMOTE_SCHEMES = frozenset({"sftp", "ssh", "fish"})

_ASKPASS_WRAPPER: Optional[Path] = None


@dataclass(frozen=True)
class RemoteTarget:
    """Parsed remote host + absolute path (SFTP URL or user@host:/path)."""

    host: str
    path: str
    user: Optional[str] = None

    def ssh_spec(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


def parse_remote_destination(dest: str) -> Tuple[Optional[RemoteTarget], str]:
    """
    Return (RemoteTarget, remainder) for a destination string.
    If not remote, RemoteTarget is None and the second value is dest stripped.
    Accepts ``user@host:/path`` and ``sftp://user@host/path`` (Dolphin-style).
    """
    s = dest.strip()
    if not s:
        return None, s

    if "://" in s[:24]:
        parsed = urlparse(s)
        scheme = parsed.scheme.lower() if parsed.scheme else ""
        if scheme in _URL_REMOTE_SCHEMES and parsed.hostname:
            path = unquote(parsed.path or "/")
            if not path.startswith("/"):
                path = "/" + path if path else "/"
            user = parsed.username
            host = parsed.hostname
            return RemoteTarget(host=host, path=path, user=user), path

    m = _RSYNC_REMOTE.match(s)
    if not m:
        return None, s
    user = m.group("user")
    host = m.group("host")
    path = m.group("path")
    return RemoteTarget(host=host, path=path, user=user), path


def is_remote_path(s: str) -> bool:
    return parse_remote_destination(s.strip())[0] is not None


def to_sftp_folder_uri(remote: RemoteTarget) -> str:
    """Stable ``sftp://`` folder URI with trailing slash for directory pickers."""
    p = remote.path or "/"
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/") or "/"
    p = p + "/"
    if remote.user:
        return f"sftp://{remote.user}@{remote.host}{p}"
    return f"sftp://{remote.host}{p}"


def ssh_extra_argv(connect_timeout: int, batch_mode: bool) -> List[str]:
    opts: List[str] = ["-o", f"ConnectTimeout={connect_timeout}"]
    if batch_mode:
        opts += ["-o", "BatchMode=yes"]
    else:
        opts += [
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "GSSAPIAuthentication=no",
            "-o",
            "PasswordAuthentication=yes",
            "-o",
            "KbdInteractiveAuthentication=yes",
            "-o",
            "NumberOfPasswordPrompts=6",
            "-o",
            "PreferredAuthentications=keyboard-interactive,password",
        ]
    return opts


def _ssh_askpass_py() -> Path:
    return Path(__file__).resolve().parent.parent / "ui" / "ssh_askpass.py"


def ensure_ssh_askpass_wrapper() -> Path:
    """Create a shell wrapper that runs ``ssh_askpass.py`` with this interpreter."""
    global _ASKPASS_WRAPPER
    if _ASKPASS_WRAPPER is not None and _ASKPASS_WRAPPER.is_file():
        return _ASKPASS_WRAPPER
    askpass_py = _ssh_askpass_py()
    if not askpass_py.is_file():
        raise FileNotFoundError(f"Missing {askpass_py}")
    fd, name = tempfile.mkstemp(prefix="chronoarchiver-askpass-", suffix=".sh")
    os.close(fd)
    path = Path(name)
    py = sys.executable
    path.write_text(f"#!/bin/sh\nexec '{py}' '{askpass_py}' \"$@\"\n", encoding="utf-8")
    path.chmod(0o700)
    _ASKPASS_WRAPPER = path
    return path


def build_ssh_command_argv(
    remote: RemoteTarget,
    remote_cmd: str,
    *,
    connect_timeout: int = 15,
    batch_mode: bool = True,
    password_for_sshpass: Optional[str] = None,
) -> List[str]:
    core = [
        "ssh",
        *ssh_extra_argv(connect_timeout, batch_mode),
        remote.ssh_spec(),
        remote_cmd,
    ]
    if password_for_sshpass:
        ss = shutil.which("sshpass")
        if not ss:
            raise FileNotFoundError(
                "sshpass is not installed; install it or leave the password empty to use the GUI askpass prompt."
            )
        return [ss, "-e", *core]
    return core


def ssh_command_environment(
    extra_env: Optional[dict],
    password_for_sshpass: Optional[str],
) -> dict:
    env = os.environ.copy()
    if password_for_sshpass:
        env["SSHPASS"] = password_for_sshpass
        # Subprocess SSH has no controlling TTY. If the desktop session set SSH_ASKPASS /
        # GIT_ASKPASS, OpenSSH may prefer them over the password path sshpass provides,
        # which breaks or empties captured remote stdout/stderr.
        for k in (
            "SSH_ASKPASS",
            "SSH_ASKPASS_REQUIRE",
            "SSH_ASKPASS_PROMPT_TIMEOUT",
            "GIT_ASKPASS",
        ):
            env.pop(k, None)
        if extra_env:
            for k, v in extra_env.items():
                if k not in (
                    "SSH_ASKPASS",
                    "SSH_ASKPASS_REQUIRE",
                    "SSH_ASKPASS_PROMPT_TIMEOUT",
                    "GIT_ASKPASS",
                ):
                    env[k] = v
    elif extra_env:
        env.update(extra_env)
    return env


def run_ssh_command(
    remote: RemoteTarget,
    remote_cmd: str,
    *,
    connect_timeout: int = 15,
    batch_mode: bool = True,
    extra_env: Optional[dict] = None,
    password_for_sshpass: Optional[str] = None,
) -> subprocess.CompletedProcess:
    ssh_cmd = build_ssh_command_argv(
        remote,
        remote_cmd,
        connect_timeout=connect_timeout,
        batch_mode=batch_mode,
        password_for_sshpass=password_for_sshpass,
    )
    env = ssh_command_environment(extra_env, password_for_sshpass)
    overhead = SSH_SUBPROCESS_MAX_RUNTIME_OVERHEAD_SEC
    run_kw: dict = {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": connect_timeout + overhead,
        "env": env,
    }
    if os.name != "nt":
        run_kw["start_new_session"] = True
    return subprocess.run(ssh_cmd, **run_kw)


def run_ssh_echo_ok_test(
    raw_path: str,
    password_plain: str,
    *,
    batch_mode: bool = False,
) -> Tuple[bool, str]:
    """
    Run ``echo ok`` on the remote host. Returns (success, message_for_ui).
    ``batch_mode`` True skips password auth (keys/agent only).
    """
    raw = raw_path.strip()
    if not raw:
        return False, "Enter a remote path first."
    rmt, _ = parse_remote_destination(raw)
    if rmt is None:
        return False, "That path is not remote. Use user@host:/path or sftp://user@host/path."
    if not (rmt.user and str(rmt.user).strip()):
        return (
            False,
            "The remote address has no SSH username. Use user@host:/path or "
            "sftp://user@host/path (SSH does not guess your local login name here).",
        )
    pw_plain = password_plain.strip()
    pw_ssh = pw_plain if pw_plain and shutil.which("sshpass") else None
    extra_env: Optional[dict] = None
    if pw_ssh is None and not batch_mode:
        try:
            w = ensure_ssh_askpass_wrapper()
            extra_env = {
                "SSH_ASKPASS": str(w),
                "SSH_ASKPASS_REQUIRE": "force",
            }
        except OSError as e:
            return False, str(e)
    try:
        cp = run_ssh_command(
            rmt,
            "echo ok",
            connect_timeout=SSH_TEST_CONNECT_TIMEOUT_SEC,
            batch_mode=batch_mode,
            extra_env=extra_env,
            password_for_sshpass=pw_ssh,
        )
    except FileNotFoundError as e:
        return False, str(e)
    except subprocess.TimeoutExpired:
        return False, "Connection timed out. Check host, network, and firewall."
    out = (cp.stdout or "").strip().lower()
    ok = cp.returncode == 0 and "ok" in out
    if ok:
        return True, "SSH connection succeeded."
    err = (cp.stderr or "").strip() or f"exit {cp.returncode}"
    return False, f"SSH test failed:\n{err}"
