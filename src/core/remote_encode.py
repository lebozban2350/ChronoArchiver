"""
SSH/SCP helpers for AV1 batch encoding against remote source and/or destination paths.

Each file is copied to a local temp path, encoded with FFmpeg, then copied to the final
location (local or remote). Requires OpenSSH ``ssh`` and ``scp`` on the client, and
``python3`` on the remote for directory scans.

Authentication: SSH keys/agent (password field empty), or install ``sshpass`` and enter
the account password (bulk transfers avoid per-file GUI prompts).
"""

from __future__ import annotations

import base64
import logging
import os
import posixpath
import secrets
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.remote_ssh import RemoteTarget, parse_remote_destination, ssh_command_environment, ssh_extra_argv

CONNECT_SCP = 60
ENCODE_SCAN_CONNECT = 30


class RemoteEncodeError(Exception):
    pass


def _debug_remote_scan(message: str, *, warn: bool = False) -> None:
    """Log to the session pipe file; optional mirror to standard log at WARNING for scan failures."""
    try:
        from core.debug_logger import UTILITY_MASS_AV1_ENCODER, debug

        debug(UTILITY_MASS_AV1_ENCODER, message)
    except Exception:
        pass
    if warn:
        try:
            logging.getLogger("ChronoArchiver").warning("Mass AV1 Encoder | %s", message)
        except Exception:
            pass


def _ssh_stderr_text(cp: subprocess.CompletedProcess) -> str:
    return (cp.stderr or cp.stdout or "").strip()


def _ssh_merged_remote_text(cp: subprocess.CompletedProcess) -> str:
    """Join stderr and stdout for protocol lines (some ssh/sshpass setups mux to stdout)."""
    parts = [x for x in (cp.stderr, cp.stdout) if x]
    return "\n".join(parts)


def _remote_via_posix_sh(shell_command: str) -> List[str]:
    """
    Run ``shell_command`` on the remote host under POSIX ``/bin/sh -c``.

    Use an explicit ``/bin/sh`` so the remote login shell (e.g. fish) never parses the
    command. Avoid heredocs (``<<``): fish rejects them when sshd runs the forced command
    through the user shell on some setups.
    """
    return ["/bin/sh", "-c", shell_command]


def _remote_python_script_as_quoted_invocation(script: str) -> str:
    """
    Run ``python3`` on the remote host with the script embedded in one ``sh -c`` line.

    - No stdin (works with ``sshpass``).
    - No heredoc (fish-safe).
    - ``-u`` unbuffered so lines reach the client before the process exits.
    """
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    py = "import base64; exec(compile(base64.b64decode(%r), '<chrono_scan>', 'exec'))" % (b64,)
    return "python3 -u -c " + shlex.quote(py)


def sh_single_quote(s: str) -> str:
    return "'" + str(s).replace("'", "'\"'\"'") + "'"


def _ssh_auth_error_message(stderr_stdout: str) -> Optional[str]:
    """Human hint when OpenSSH fails with auth/host-key errors (not missing python3)."""
    t = (stderr_stdout or "").lower()
    if not any(
        x in t
        for x in (
            "permission denied",
            "authentication failure",
            "too many authentication failures",
            "no matching host key",
        )
    ):
        return None
    return (
        "SSH authentication failed. Use the **SSH password** field on this panel "
        "(the Browse dialog copies your password there when you confirm OK). "
        "For password-based batch SSH, install **sshpass**; or use an SSH key or agent and leave the password empty. "
    )


@dataclass(frozen=True)
class RemoteFileRef:
    """One video file under a remote root (POSIX paths)."""

    target: RemoteTarget
    root_posix: str
    rel_posix: str
    size: int

    @property
    def abs_posix(self) -> str:
        root = self.root_posix.rstrip("/") or "/"
        rel = self.rel_posix.lstrip("/")
        if root == "/":
            return "/" + rel if rel else "/"
        return f"{root}/{rel}" if rel else root


def remote_target_and_root(display_path: str) -> Tuple[RemoteTarget, str]:
    r, _ = parse_remote_destination(display_path.strip())
    if r is None:
        raise RemoteEncodeError("Not a remote path.")
    raw = (r.path or "/").replace("\\", "/")
    if not raw.startswith("/"):
        raw = "/" + raw.lstrip("/")
    root = posixpath.normpath(raw)
    if not root or root == ".":
        root = "/"
    if not root.startswith("/"):
        root = "/" + root
    root = root.rstrip("/") or "/"
    return r, root


def password_for_remote_encode(password_plain: str) -> Optional[str]:
    """
    Empty → use SSH keys/agent only.

    Non-empty requires ``sshpass`` on PATH (avoids dozens of password prompts per batch).
    """
    pw = (password_plain or "").strip()
    if not pw:
        return None
    if not shutil.which("sshpass"):
        raise RemoteEncodeError(
            "Remote encoding with a password requires sshpass (e.g. pacman -S sshpass on Linux). "
            "Alternatively use an SSH key or ssh-agent and leave the password field empty."
        )
    return pw


def _scp_argv(
    connect_timeout: int,
    batch_mode: bool,
    password_for_sshpass: Optional[str],
    src_spec: str,
    dst_spec: str,
) -> List[str]:
    inner = ["scp", "-q", *ssh_extra_argv(connect_timeout, batch_mode), src_spec, dst_spec]
    if password_for_sshpass:
        ss = shutil.which("sshpass")
        if not ss:
            raise RemoteEncodeError("sshpass not found.")
        return [ss, "-e", *inner]
    return inner


def run_scp_from_remote(
    remote: RemoteTarget,
    remote_posix: str,
    local_path: str,
    *,
    password_for_sshpass: Optional[str],
) -> None:
    spec = f"{remote.ssh_spec()}:{remote_posix}"
    batch = password_for_sshpass is None
    cmd = _scp_argv(CONNECT_SCP, batch, password_for_sshpass, spec, local_path)
    env = ssh_command_environment(None, password_for_sshpass)
    kw: dict = {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": None,
        "env": env,
    }
    if os.name != "nt":
        kw["start_new_session"] = True
    cp = subprocess.run(cmd, **kw)
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip() or f"exit {cp.returncode}"
        raise RemoteEncodeError(f"scp pull failed: {err}")


def run_scp_to_remote(
    local_path: str,
    remote: RemoteTarget,
    remote_posix: str,
    *,
    password_for_sshpass: Optional[str],
) -> None:
    spec = f"{remote.ssh_spec()}:{remote_posix}"
    batch = password_for_sshpass is None
    cmd = _scp_argv(CONNECT_SCP, batch, password_for_sshpass, local_path, spec)
    env = ssh_command_environment(None, password_for_sshpass)
    kw: dict = {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "timeout": None,
        "env": env,
    }
    if os.name != "nt":
        kw["start_new_session"] = True
    cp = subprocess.run(cmd, **kw)
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip() or f"exit {cp.returncode}"
        raise RemoteEncodeError(f"scp push failed: {err}")


def _remote_scan_via_scp_and_ssh(
    remote: RemoteTarget,
    script: str,
    batch: bool,
    password_for_sshpass: Optional[str],
) -> subprocess.CompletedProcess:
    """
    Upload scan script with scp, run ``python3 -u`` on it, remove it on the remote host.

    Matches the proven pull/push path used for encoding when stdin/argv capture fails under sshpass.
    """
    token = secrets.token_hex(8)
    remote_py = f"/tmp/chronoarchiver_scan_{token}.py"
    q = sh_single_quote(remote_py)
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    local_path = tf.name
    try:
        tf.write(script)
        tf.close()
        run_scp_to_remote(local_path, remote, remote_py, password_for_sshpass=password_for_sshpass)
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass
    # No `var=$?` here: some hosts run the forced command through fish, which rejects POSIX assignments.
    shell_body = f"python3 -u {q}"
    cmd = [
        "ssh",
        "-T",
        *ssh_extra_argv(ENCODE_SCAN_CONNECT, batch),
        remote.ssh_spec(),
        *_remote_via_posix_sh(shell_body),
    ]
    cp = run_ssh_argv(cmd, password_for_sshpass=password_for_sshpass, timeout=86400)
    rm_cmd = [
        "ssh",
        "-T",
        *ssh_extra_argv(ENCODE_SCAN_CONNECT, batch),
        remote.ssh_spec(),
        *_remote_via_posix_sh(f"rm -f {q}"),
    ]
    try:
        run_ssh_argv(rm_cmd, password_for_sshpass=password_for_sshpass, timeout=CONNECT_SCP + 30)
    except Exception:
        pass
    return cp


def run_ssh_argv(
    argv: List[str],
    *,
    password_for_sshpass: Optional[str],
    timeout: Optional[float],
    stdin: Optional[str] = None,
) -> subprocess.CompletedProcess:
    core = argv
    if password_for_sshpass:
        ss = shutil.which("sshpass")
        if not ss:
            raise RemoteEncodeError("sshpass not found.")
        cmd = [ss, "-e", *core]
    else:
        cmd = core
    env = ssh_command_environment(None, password_for_sshpass)
    kw: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "env": env,
    }
    if stdin is not None:
        kw["input"] = stdin
    else:
        kw["stdin"] = subprocess.DEVNULL
    if os.name != "nt":
        kw["start_new_session"] = True
    return subprocess.run(cmd, **kw)


def remote_verify_python3(remote: RemoteTarget, password_for_sshpass: Optional[str]) -> None:
    batch = password_for_sshpass is None
    cmd = [
        "ssh",
        "-T",
        *ssh_extra_argv(ENCODE_SCAN_CONNECT, batch),
        remote.ssh_spec(),
        *_remote_via_posix_sh('python3 -c "import sys; sys.exit(0)"'),
    ]
    cp = run_ssh_argv(cmd, password_for_sshpass=password_for_sshpass, timeout=ENCODE_SCAN_CONNECT + 45)
    if cp.returncode != 0:
        err = _ssh_stderr_text(cp)
        _debug_remote_scan(
            f"remote_verify_python3 failed host={remote.ssh_spec()} rc={cp.returncode} stderr={err[:1200]!r}",
            warn=True,
        )
        auth = _ssh_auth_error_message(err)
        if auth:
            raise RemoteEncodeError(auth.rstrip() + (f" ({err[:400]})" if err else ""))
        raise RemoteEncodeError(f"Remote host must have ``python3`` on PATH for scanning. SSH: {err or cp.returncode}")


def _scan_script_source(root: str, exts: Tuple[str, ...]) -> str:
    # root embedded as repr — must be a trusted path from our own parser only.
    ext_list = sorted(set(e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts))
    ext_repr = repr(tuple(ext_list))
    # Remote: resolve path from SSH login cwd; follow symlinked dirs (media trees).
    # os.walk on a missing path yields nothing and exits 0 — detect with isdir first.
    return f"""import os,sys
root={root!r}
root=os.path.normpath(os.path.abspath(os.path.expanduser(root)))
if not os.path.isdir(root):
    _ed="CHRONOARCHIVER_SCAN_ENOTDIR\\t"+repr(root)
    sys.stderr.write(_ed+"\\n")
    sys.stderr.flush()
    print(_ed, flush=True)
    sys.exit(3)
exts=set({ext_repr})
out_n=0
for dp,dns,fns in os.walk(root, followlinks=True):
    dns[:]=[x for x in dns if not x.startswith(".")]
    for fn in fns:
        if fn.startswith("."):
            continue
        low=fn.lower()
        if not any(low.endswith(e) for e in exts):
            continue
        stem,xe=os.path.splitext(fn)
        if stem.lower().endswith("_av1"):
            continue
        fp=os.path.join(dp,fn)
        try:
            sz=os.path.getsize(fp)
        except OSError:
            continue
        try:
            rel=os.path.relpath(fp,root)
        except ValueError:
            continue
        if rel.startswith(".."):
            continue
        rel=rel.replace("\\\\","/")
        print(f"{{sz}}\\t{{rel}}", flush=True)
        out_n+=1
_sum="CHRONOARCHIVER_SCAN_SUMMARY\\tfiles="+str(out_n)+"\\troot="+repr(root)
sys.stderr.write(_sum+"\\n")
sys.stderr.flush()
print(_sum, flush=True)
"""


def _parse_remote_scan_summary(protocol_text: str) -> Tuple[Optional[int], Optional[str]]:
    """Parse ``CHRONOARCHIVER_SCAN_SUMMARY`` from merged remote stderr/stdout."""
    for line in (protocol_text or "").splitlines():
        if not line.startswith("CHRONOARCHIVER_SCAN_SUMMARY"):
            continue
        file_count: Optional[int] = None
        root_disp: Optional[str] = None
        for part in line.split("\t")[1:]:
            if part.startswith("files="):
                try:
                    file_count = int(part[6:])
                except ValueError:
                    pass
            elif part.startswith("root="):
                root_disp = part[5:]
        return file_count, root_disp
    return None, None


def _remote_scan_console_hint(
    *,
    root_requested: str,
    parsed_queue_len: int,
    protocol_text: str,
) -> str:
    """One line for the encoder UI (thread-safe emit from worker)."""
    files_n, root_s = _parse_remote_scan_summary(protocol_text)
    ext_line = ".mp4, .mkv, .mov, .webm, .ts, .avi, .3gp, .mpg"
    if files_n is not None and root_s is not None:
        if files_n == 0:
            return (
                f"Remote: 0 videos under {root_s} on the server "
                f"(extensions {ext_line}; names ending with _av1 before the extension are skipped)."
            )
        if parsed_queue_len != files_n:
            return (
                f"Remote: server counted {files_n} file(s) under {root_s}; "
                f"{parsed_queue_len} entered the queue after parsing ({ext_line})."
            )
        return f"Remote: {files_n} video file(s) under {root_s} on the server ({ext_line})."
    tail = (protocol_text or "").strip().replace("\n", " ")
    if len(tail) > 400:
        tail = tail[:400] + "…"
    return (
        f"Remote: {parsed_queue_len} file(s) in queue; "
        f"no scan summary from server (stderr: {tail!r}). URI folder normalized to {root_requested!r}."
    )


def _remote_scan_parse_cp_result(
    cp: subprocess.CompletedProcess,
    remote: RemoteTarget,
    root_norm: str,
    *,
    transport: str,
    all_transports_exhausted: bool = False,
) -> Tuple[List[RemoteFileRef], str]:
    merged = _ssh_merged_remote_text(cp)
    for line in merged.splitlines():
        if line.startswith("CHRONOARCHIVER_SCAN_ENOTDIR"):
            detail = line.split("\t", 1)[1].strip() if "\t" in line else ""
            _debug_remote_scan(
                f"remote_scan ENOTDIR host={remote.ssh_spec()} requested_root={root_norm!r} detail={detail!r}",
                warn=True,
            )
            raise RemoteEncodeError(
                "Remote source path is not a directory or does not exist on the server "
                f"(resolved {detail}). Check the folder in Browse / the sftp:// path."
            )
    if cp.returncode != 0:
        err = _ssh_stderr_text(cp)
        auth = _ssh_auth_error_message(err)
        if auth:
            raise RemoteEncodeError(auth.rstrip() + (f" ({err[:400]})" if err else ""))
        _debug_remote_scan(
            f"remote_scan failed host={remote.ssh_spec()} root={root_norm!r} transport={transport} "
            f"rc={cp.returncode} stderr={err[:1200]!r}",
            warn=True,
        )
        raise RemoteEncodeError(f"Remote scan failed (exit {cp.returncode}): {err[:800]}")
    if cp.returncode == 0 and not merged.strip():
        _debug_remote_scan(
            f"remote_scan empty_streams host={remote.ssh_spec()} root={root_norm!r} transport={transport} "
            f"stdout={len(cp.stdout or '')} stderr={len(cp.stderr or '')} "
            f"all_transports_exhausted={all_transports_exhausted}",
            warn=True,
        )
        if all_transports_exhausted:
            raise RemoteEncodeError(
                "Remote scan returned no captured output after stdin script, argv-embedded script, "
                "and scp upload to /tmp. Confirm `python3` and writable `/tmp` on the host, OpenSSH client, "
                "and sshpass (if used)."
            )
        raise RemoteEncodeError(
            "Remote scan produced no output from the server (no stdout/stderr). "
            "Check that `python3` runs on the host and that ssh is executing the remote command."
        )
    out: List[RemoteFileRef] = []
    for line in (cp.stdout or "").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or "\t" not in line:
            continue
        if line.startswith("CHRONOARCHIVER_"):
            continue
        sz_s, rel = line.split("\t", 1)
        if not sz_s.isdigit():
            continue
        rel = rel.strip().replace("\\", "/")
        if ".." in rel.split("/"):
            continue
        sz = int(sz_s)
        out.append(
            RemoteFileRef(
                target=remote,
                root_posix=root_norm,
                rel_posix=rel,
                size=sz,
            )
        )
    fc_chk, _rs_chk = _parse_remote_scan_summary(merged)
    if fc_chk is not None and fc_chk > 0 and len(out) == 0:
        _debug_remote_scan(
            f"remote_scan parse_mismatch host={remote.ssh_spec()} files_counted={fc_chk} "
            f"parsed_lines=0 stdout_len={len(cp.stdout or '')}",
            warn=True,
        )
        raise RemoteEncodeError(
            f"Remote scan counted {fc_chk} video file(s) on the server but SSH output did not "
            f"yield parseable lines (stdout length {len(cp.stdout or '')}). "
            "Try updating OpenSSH client or check for a broken ssh/sshpass wrapper."
        )
    summary_line = ""
    for line in merged.splitlines():
        if line.startswith("CHRONOARCHIVER_SCAN_SUMMARY"):
            summary_line = line
            break
    hint = _remote_scan_console_hint(
        root_requested=root_norm,
        parsed_queue_len=len(out),
        protocol_text=merged,
    )
    _debug_remote_scan(
        f"remote_scan ok host={remote.ssh_spec()} root_requested={root_norm!r} transport={transport} "
        f"parsed_tab_lines={len(out)} stdout_chars={len(cp.stdout or '')} stderr_chars={len(cp.stderr or '')} "
        f"merged_preview={merged[:900]!r} summary={summary_line!r} hint={hint!r}"
    )
    return out, hint


def remote_scan_videos(
    remote: RemoteTarget,
    root_posix: str,
    extensions: Tuple[str, ...],
    password_for_sshpass: Optional[str],
) -> Tuple[List[RemoteFileRef], str]:
    """Return (video file refs, one-line console hint for the UI) for ``root_posix`` on the remote host."""
    root_norm = root_posix.rstrip("/") or "/"
    script = _scan_script_source(root_norm, extensions)
    batch = password_for_sshpass is None
    # 1) Stdin script + -T: no PTY so sshpass/subprocess can capture streams (pty often drops PIPE capture).
    # 2) Argv-embedded base64 fallback.
    # 3) scp script to /tmp + ssh python3 (same mechanism as encode pull/push).
    cmd_stdin = [
        "ssh",
        "-T",
        *ssh_extra_argv(ENCODE_SCAN_CONNECT, batch),
        remote.ssh_spec(),
        *_remote_via_posix_sh("python3 -u -"),
    ]
    cp = run_ssh_argv(
        cmd_stdin,
        password_for_sshpass=password_for_sshpass,
        timeout=86400,
        stdin=script,
    )
    merged = _ssh_merged_remote_text(cp)
    if cp.returncode == 0 and not merged.strip():
        _debug_remote_scan(
            "remote_scan: stdin transport returned rc=0 with no captured output; retry argv-embedded script"
        )
        remote_sh = _remote_python_script_as_quoted_invocation(script)
        cmd_argv = [
            "ssh",
            "-T",
            *ssh_extra_argv(ENCODE_SCAN_CONNECT, batch),
            remote.ssh_spec(),
            *_remote_via_posix_sh(remote_sh),
        ]
        cp = run_ssh_argv(cmd_argv, password_for_sshpass=password_for_sshpass, timeout=86400)
        merged = _ssh_merged_remote_text(cp)
        if cp.returncode == 0 and not merged.strip():
            _debug_remote_scan("remote_scan: argv transport empty; retry scp upload + remote python3 /tmp/ script")
            cp = _remote_scan_via_scp_and_ssh(remote, script, batch, password_for_sshpass)
            return _remote_scan_parse_cp_result(
                cp, remote, root_norm, transport="scp_tmp", all_transports_exhausted=True
            )
        return _remote_scan_parse_cp_result(cp, remote, root_norm, transport="argv_embedded")
    return _remote_scan_parse_cp_result(cp, remote, root_norm, transport="stdin_script")


def remote_mkdir_p(remote: RemoteTarget, dir_posix: str, password_for_sshpass: Optional[str]) -> None:
    q = sh_single_quote(dir_posix)
    cmd = [
        "ssh",
        *ssh_extra_argv(CONNECT_SCP, password_for_sshpass is None),
        remote.ssh_spec(),
        *_remote_via_posix_sh(f"mkdir -p {q}"),
    ]
    cp = run_ssh_argv(cmd, password_for_sshpass=password_for_sshpass, timeout=CONNECT_SCP + 60)
    if cp.returncode != 0:
        raise RemoteEncodeError(f"mkdir remote failed: {(cp.stderr or '').strip()[:400]}")


def remote_file_exists(remote: RemoteTarget, file_posix: str, password_for_sshpass: Optional[str]) -> bool:
    q = sh_single_quote(file_posix)
    cmd = [
        "ssh",
        *ssh_extra_argv(CONNECT_SCP, password_for_sshpass is None),
        remote.ssh_spec(),
        *_remote_via_posix_sh(f"test -f {q}"),
    ]
    cp = run_ssh_argv(cmd, password_for_sshpass=password_for_sshpass, timeout=CONNECT_SCP + 30)
    return cp.returncode == 0


def remote_unlink(remote: RemoteTarget, file_posix: str, password_for_sshpass: Optional[str]) -> None:
    q = sh_single_quote(file_posix)
    cmd = [
        "ssh",
        *ssh_extra_argv(CONNECT_SCP, password_for_sshpass is None),
        remote.ssh_spec(),
        *_remote_via_posix_sh(f"rm -f {q}"),
    ]
    run_ssh_argv(cmd, password_for_sshpass=password_for_sshpass, timeout=CONNECT_SCP + 60)


def join_dst_local(dst_local: str, rel_stem_posix: str) -> str:
    """``rel_stem_posix`` is relative path without extension, using ``/``."""
    rel_stem_posix = rel_stem_posix.replace("\\", "/").strip("/")
    if ".." in rel_stem_posix.split("/"):
        raise ValueError("invalid path")
    parent, stem = posixpath.split(rel_stem_posix) if rel_stem_posix else ("", "")
    if not stem:
        raise ValueError("invalid path")
    base = os.path.abspath(dst_local)
    out = os.path.join(base, *parent.split("/")) if parent else base
    return os.path.join(out, f"{stem}_av1.mp4")


def posix_join_under(root: str, rel_stem_posix: str) -> str:
    """Absolute POSIX output path under remote root (for scp destination)."""
    rel_stem_posix = rel_stem_posix.replace("\\", "/").strip("/")
    if ".." in rel_stem_posix.split("/"):
        raise ValueError("invalid path")
    r = root.rstrip("/") or "/"
    if not rel_stem_posix:
        raise ValueError("invalid path")
    parent, stem = posixpath.split(rel_stem_posix)
    if parent:
        return f"{r}/{parent}/{stem}_av1.mp4".replace("//", "/")
    return f"{r}/{stem}_av1.mp4".replace("//", "/")


def common_structure_root_posix(refs: List[RemoteFileRef]) -> str:
    dirs = [posixpath.dirname(r.abs_posix) for r in refs]
    if not dirs:
        return refs[0].root_posix if refs else "/"
    try:
        return posixpath.commonpath(dirs)
    except ValueError:
        return refs[0].root_posix
