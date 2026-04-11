import glob
import os
import platform
import shutil
import time
import threading
import subprocess
import re
import json
import psutil
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Generator
from collections import deque

try:
    from .debug_logger import debug, UTILITY_MASS_AV1_ENCODER
except ImportError:
    from core.debug_logger import debug, UTILITY_MASS_AV1_ENCODER


def _ffmpeg_muxed_size_bytes(line: str) -> int:
    """
    Best-effort parse of FFmpeg progress ``(L)size=`` (``KiB`` / ``kB`` / ``MiB`` / ``GiB``).
    Matches modern FFmpeg lines such as ``size=     256KiB`` and final ``Lsize= ...``.
    """
    m = re.search(r"(?:L)?size=\s*(\d+)\s*(KiB|kB|MiB|GiB)?", line, re.I)
    if not m:
        return 0
    n = int(m.group(1))
    suf = (m.group(2) or "KiB").lower()
    if suf == "kib" or suf == "kb":
        return n * 1024
    if suf == "mib":
        return n * 1024 * 1024
    if suf == "gib":
        return n * 1024 * 1024 * 1024
    return n * 1024


def _ffmpeg_progress_fps_speed(line: str) -> tuple[Optional[float], Optional[float]]:
    """Parse ``fps=`` and ``speed=…x`` from a FFmpeg status line (encoding throughput)."""
    fps_m = re.search(r"fps=\s*([\d.]+)", line)
    spd_m = re.search(r"speed=\s*([\d.]+)\s*x", line)
    fps_v = float(fps_m.group(1)) if fps_m else None
    spd_v = float(spd_m.group(1)) if spd_m else None
    return fps_v, spd_v


def verify_local_media_file_ready(path: str) -> tuple[bool, str | None]:
    """
    Ensure a local path is fully written and readable as video before FFmpeg runs.
    Avoids decode/encoder failures when a transfer is incomplete or still flushing.
    """
    if not path:
        return False, "empty path"
    if not os.path.isfile(path):
        return False, "not a regular file"
    try:
        s1 = os.path.getsize(path)
    except OSError as e:
        return False, str(e)
    if s1 <= 0:
        return False, "empty file"
    time.sleep(0.05)
    try:
        s2 = os.path.getsize(path)
    except OSError as e:
        return False, str(e)
    if s1 != s2:
        return False, "file size changed (transfer may still be in progress)"
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                path,
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if "video" not in out.lower():
            return False, f"no video stream (ffprobe: {out.strip()!r})"
    except subprocess.CalledProcessError as e:
        tail = (e.output or "")[:300]
        return False, f"ffprobe stream check failed: {tail}"
    except subprocess.TimeoutExpired:
        return False, "ffprobe stream check timed out"
    try:
        d_out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=120,
        ).strip()
        if not d_out:
            return False, "zero duration"
        if float(d_out) <= 0.0:
            return False, "zero duration"
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        return False, f"duration probe failed: {e}"
    return True, None


def video_file_is_av1(input_path: str) -> bool:
    """True if the first video stream is AV1 (ffprobe codec_name ``av1``)."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=120,
        ).strip()
        return out.lower() == "av1"
    except (subprocess.SubprocessError, OSError, ValueError):
        return False


def passthrough_av1_to_output(
    input_path: str,
    output_path: str,
    *,
    log: logging.Logger | None = None,
) -> bool:
    """
    Write ``output_path`` from an AV1 source without re-encoding: copy when both sides are
    ``.mp4``, otherwise FFmpeg stream-copy remux (e.g. MKV/WebM → MP4).
    """
    if not video_file_is_av1(input_path):
        return False
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    ext_in = os.path.splitext(input_path)[1].lower()
    ext_out = os.path.splitext(output_path)[1].lower()
    if ext_in == ".mp4" and ext_out == ".mp4":
        try:
            shutil.copy2(input_path, output_path)
            return True
        except OSError as e:
            if log:
                log.warning("AV1 passthrough: copy failed: %s", e)
            return False
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            input_path,
            "-map",
            "0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
        ]
        r = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=86400,
        )
        if r.returncode == 0:
            return True
        if log and r.stderr:
            debug(UTILITY_MASS_AV1_ENCODER, f"AV1 remux stderr tail: {r.stderr[-400:]}")
        if output_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return False
    except (subprocess.SubprocessError, OSError) as e:
        if log:
            log.warning("AV1 passthrough: remux failed: %s", e)
        if output_path and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        return False


def terminate_ffmpeg_process_tree(proc: subprocess.Popen | None, *, log: logging.Logger | None = None) -> None:
    """
    Terminate FFmpeg and any child processes so they do not outlive the app after crash/close.
    Uses psutil when available; falls back to Popen.terminate()/kill().
    """
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for p in children:
            try:
                p.terminate()
            except psutil.Error:
                pass
        try:
            parent.terminate()
        except psutil.Error:
            pass
        try:
            to_wait = list(children) + [parent]
            _, survivors = psutil.wait_procs(to_wait, timeout=3)
            for p in survivors:
                try:
                    p.kill()
                except psutil.Error:
                    pass
        except psutil.NoSuchProcess:
            pass
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        if log:
            log.warning("FFmpeg tree terminate: %s", e)
        try:
            proc.kill()
        except Exception:
            pass


@dataclass
class EncodingProgress:
    file_name: str
    percent: float
    time_elapsed: str
    fps: float
    speed: float
    bytes_processed: int


class AV1EncoderEngine:
    """High-performance engine for batch AV1 encoding."""

    # After the first FFmpeg 183/218 with CUDA decode + NVENC, skip CUDA hwaccel for the rest
    # of the run so every file is not attempted twice (software decode + NVENC still used).
    _nvenc_skip_cuda_hwaccel: bool = False
    _nvenc_cuda_lock = threading.Lock()

    def __init__(self, job_id: int = 0):
        self.job_id = job_id
        self.on_progress: Optional[Callable[[int, EncodingProgress], None]] = None
        self.on_details: Optional[Callable[[int, str, str], None]] = None
        self._encoders_output = self._get_encoders_output()
        self.has_cuda = "av1_nvenc" in self._encoders_output
        self.has_amd_vaapi = "av1_vaapi" in self._encoders_output and platform.system() == "Linux"
        self.has_amd_amf = "av1_amf" in self._encoders_output and platform.system() == "Windows"
        self._hw_encoder = (
            "nvenc" if self.has_cuda else ("vaapi" if self.has_amd_vaapi else ("amf" if self.has_amd_amf else None))
        )
        self._current_process: Optional[subprocess.Popen] = None
        self._is_paused = False
        self._lock = threading.Lock()
        self.logger = logging.getLogger("ChronoArchiver.Encoder")
        if self._hw_encoder:
            self.logger.info(f"HW encoder: {self._hw_encoder}")
        else:
            self.logger.info("HW encoder: none, using libsvtav1")

    @classmethod
    def reset_nvenc_cuda_hwaccel_for_new_batch(cls) -> None:
        """Call when starting a new encode batch so a prior run's CUDA-decode skip does not apply."""
        with cls._nvenc_cuda_lock:
            cls._nvenc_skip_cuda_hwaccel = False

    @property
    def has_hardware_av1_encoder(self) -> bool:
        """True if FFmpeg reports an AV1 NVENC/VAAPI/AMF encoder (probe at engine init)."""
        return self._hw_encoder is not None

    def _get_encoders_output(self) -> str:
        try:
            return subprocess.check_output(["ffmpeg", "-encoders"], stderr=subprocess.STDOUT, text=True)
        except Exception:
            return ""

    def scan_files(self, directory: str, stop_event: Optional[threading.Event] = None) -> Generator[tuple, None, None]:
        """Scans a directory for supported video files, yielding results for real-time feedback."""
        extensions = (".mpg", ".mp4", ".ts", ".avi", ".3gp", ".mkv", ".mov", ".webm")
        self.logger.info(f"scan_files: start dir={directory}")
        debug(UTILITY_MASS_AV1_ENCODER, f"scan_files: start dir={directory}")

        def _skip_error(err):
            self.logger.warning(f"Scan skip dir: {err}")
            debug(UTILITY_MASS_AV1_ENCODER, f"scan_files: skip dir {err}")

        try:
            for root, dirs, filenames in os.walk(directory, onerror=_skip_error):
                if stop_event and stop_event.is_set():
                    self.logger.info(f"Scan interrupted for {directory}")
                    break

                dirs[:] = [d for d in dirs if not d.startswith(".")]

                for filename in filenames:
                    name_stem = os.path.splitext(filename)[0]
                    if name_stem.endswith("_av1"):
                        continue
                    if filename.lower().endswith(extensions):
                        full_path = os.path.join(root, filename)
                        try:
                            size = os.path.getsize(full_path)
                        except OSError:
                            size = 0
                        yield (full_path, size)
        except Exception as e:
            self.logger.error(f"Failed to scan files in {directory}: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"scan_files: exception dir={directory} err={e}")

    def pause(self):
        """Pauses the current encoding process."""
        with self._lock:
            if self._current_process and self._current_process.poll() is None and not self._is_paused:
                try:
                    psutil.Process(self._current_process.pid).suspend()
                    self._is_paused = True
                    self.logger.info(f"Engine State [Job {self.job_id}]: Process paused")
                except Exception as e:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: Failed to pause process: {e}")

    def resume(self):
        """Resumes the current encoding process."""
        with self._lock:
            if self._current_process and self._current_process.poll() is None and self._is_paused:
                try:
                    psutil.Process(self._current_process.pid).resume()
                    self._is_paused = False
                    self.logger.info(f"Engine State [Job {self.job_id}]: Process resumed")
                except Exception as e:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: Failed to resume process: {e}")

    def cancel(self):
        """Cancels the current encoding process."""
        with self._lock:
            if self._current_process:
                try:
                    terminate_ffmpeg_process_tree(self._current_process, log=self.logger)
                    self.logger.info(f"Engine State [Job {self.job_id}]: Process cancelled/terminated")
                except Exception as e:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: Failed to cancel process: {e}")

    def _get_video_duration(self, input_path: str) -> float:
        """Gets duration of video in seconds using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_path,
            ]
            output = subprocess.check_output(cmd, text=True).strip()
            if not output:
                return 0.0
            return float(output)
        except (subprocess.SubprocessError, ValueError, OSError):
            return 0.0

    def _detect_hdr(self, input_path: str) -> dict | None:
        """Detects HDR metadata in the source file using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=color_transfer,color_primaries,color_space,pix_fmt",
                "-of",
                "json",
                input_path,
            ]
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            data = json.loads(output)
            streams = data.get("streams", [])
            if not streams:
                return None

            stream = streams[0]
            color_transfer = stream.get("color_transfer", "")
            color_primaries = stream.get("color_primaries", "")
            color_space = stream.get("color_space", "")

            HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}
            HDR_PRIMARIES = {"bt2020"}

            is_hdr = (color_transfer in HDR_TRANSFERS) or (color_primaries in HDR_PRIMARIES)

            if is_hdr:
                self.logger.info(f"HDR detected in {os.path.basename(input_path)}")
                return {
                    "color_transfer": color_transfer,
                    "color_primaries": color_primaries,
                    "color_space": color_space,
                }
            return None
        except Exception:
            return None

    def _ffprobe_stream_display_labels(self, input_path: str) -> tuple[str, str]:
        """Video/audio summary lines for the UI via ffprobe JSON (avoids brittle FFmpeg stderr regex)."""
        try:
            out = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,"
                    "sample_rate,channels,channel_layout",
                    "-of",
                    "json",
                    input_path,
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            data = json.loads(out)
            streams = data.get("streams") or []
            vid, aud = "Unknown", "Unknown"
            for s in streams:
                ct = (s.get("codec_type") or "").lower()
                if ct == "video" and vid == "Unknown":
                    name = (s.get("codec_name") or "?").strip()
                    try:
                        w = int(s.get("width") or 0)
                        h = int(s.get("height") or 0)
                    except (TypeError, ValueError):
                        w, h = 0, 0
                    rf = s.get("r_frame_rate") or s.get("avg_frame_rate") or ""
                    fps_part = ""
                    if rf and "/" in str(rf):
                        try:
                            a, b = str(rf).split("/", 1)
                            f = float(a) / float(b)
                            if f > 0:
                                fps_part = f"{f:.2f} fps"
                        except (ValueError, ZeroDivisionError):
                            fps_part = str(rf)
                    elif rf:
                        fps_part = str(rf)
                    vid = f"{name} | {w}x{h}" + (f" | {fps_part}" if fps_part else "")
                elif ct == "audio" and aud == "Unknown":
                    name = (s.get("codec_name") or "?").strip()
                    sr = s.get("sample_rate")
                    try:
                        sr_part = f"{int(float(sr))} Hz" if sr is not None else "?"
                    except (TypeError, ValueError):
                        sr_part = "?"
                    ch = s.get("channel_layout")
                    if not ch:
                        ch = s.get("channels")
                    ch_part = str(ch) if ch is not None else "?"
                    aud = f"{name} | {sr_part} | {ch_part}"
            return vid, aud
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError, ValueError, TypeError):
            return "Unknown", "Unknown"

    def try_passthrough_existing_av1(self, input_path: str, output_path: str) -> bool:
        """
        If the file is already AV1, stream-copy or remux to ``output_path`` (``*_av1.mp4`` layout)
        without re-encoding. Updates details/progress UI like a finished encode.
        """
        if not video_file_is_av1(input_path):
            return False
        bn = os.path.basename(input_path)
        self.logger.info(
            "Engine State [Job %s]: Source is already AV1 — passthrough to %s (no re-encode)",
            self.job_id,
            os.path.basename(output_path),
        )
        debug(UTILITY_MASS_AV1_ENCODER, f"AV1 passthrough: {input_path} -> {output_path}")
        if not passthrough_av1_to_output(input_path, output_path, log=self.logger):
            return False
        probe_vid, probe_aud = self._ffprobe_stream_display_labels(input_path)
        if self.on_details and (probe_vid != "Unknown" or probe_aud != "Unknown"):
            self.on_details(
                self.job_id,
                probe_vid if probe_vid != "Unknown" else "-",
                probe_aud if probe_aud != "Unknown" else "-",
            )
        sz = 0
        try:
            sz = os.path.getsize(output_path)
        except OSError:
            pass
        if self.on_progress:
            self.on_progress(
                self.job_id,
                EncodingProgress(
                    file_name=bn,
                    percent=100.0,
                    time_elapsed="00:00:00",
                    fps=0.0,
                    speed=0.0,
                    bytes_processed=sz,
                ),
            )
        return True

    def encode_file(
        self,
        input_path: str,
        output_path: str,
        quality: int,
        preset: str,
        reencode_audio: bool,
        hw_accel_decode: bool = False,
        _retry_software_decode: bool = False,
    ) -> tuple:
        """Encodes a single file and emits progress.

        When FFmpeg lists ``av1_nvenc``, encoding uses the NVIDIA encoder whenever this build
        supports it. ``hw_accel_decode`` only toggles CUDA *decode* (demux/decode) acceleration;
        with it off, frames are decoded in software and still encoded on the GPU.
        """
        duration = self._get_video_duration(input_path)
        hdr_info = self._detect_hdr(input_path)

        probe_vid, probe_aud = self._ffprobe_stream_display_labels(input_path)
        emitted_probe_details = False
        if self.on_details and (probe_vid != "Unknown" or probe_aud != "Unknown"):
            self.on_details(
                self.job_id,
                probe_vid if probe_vid != "Unknown" else "-",
                probe_aud if probe_aud != "Unknown" else "-",
            )
            emitted_probe_details = True

        hw_flags = []
        v_args = []
        hw_decode = hw_accel_decode and not _retry_software_decode
        if self._hw_encoder == "nvenc" and hw_decode:
            with AV1EncoderEngine._nvenc_cuda_lock:
                if AV1EncoderEngine._nvenc_skip_cuda_hwaccel:
                    hw_decode = False
        used_cuda_decode = self._hw_encoder == "nvenc" and hw_decode

        if self._hw_encoder == "nvenc":
            if hw_decode:
                hw_flags = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            pix_fmt = "p010le" if hdr_info else "yuv420p"
            modern_preset = preset
            try:
                if not modern_preset.startswith("p") or int(modern_preset[1:]) > 7:
                    modern_preset = "p4"
            except ValueError:
                modern_preset = "p4"
            v_args = [
                "-c:v",
                "av1_nvenc",
                "-pix_fmt",
                pix_fmt,
                "-rc",
                "vbr",
                "-cq",
                str(quality),
                "-preset",
                modern_preset,
            ]
            gpu_raw = (os.environ.get("CHRONOARCHIVER_FFMPEG_NVENC_GPU") or "").strip()
            if gpu_raw:
                try:
                    v_args.extend(["-gpu", str(int(gpu_raw))])
                except ValueError:
                    pass
        elif self._hw_encoder == "vaapi" and hw_accel_decode:
            dri = glob.glob("/dev/dri/renderD*")
            vaapi_dev = dri[0] if dri else None
            if vaapi_dev:
                hw_flags = ["-vaapi_device", vaapi_dev, "-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]
            else:
                hw_flags = ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]
            qp_vaapi = max(50, min(200, 40 + quality * 4))
            v_args = ["-c:v", "av1_vaapi", "-qp", str(qp_vaapi)]
        elif self._hw_encoder == "amf" and hw_accel_decode:
            hw_flags = []
            qp_amf = max(8, min(52, 10 + quality))
            v_args = ["-c:v", "av1_amf", "-qp_i", str(qp_amf), "-qp_p", str(qp_amf)]
        else:
            p_map = {"p1": "12", "p2": "10", "p3": "8", "p4": "6", "p5": "4", "p6": "2", "p7": "0"}
            modern_preset = p_map.get(preset, "6")
            pix_fmt = "yuv420p10le" if hdr_info else "yuv420p"
            v_args = ["-c:v", "libsvtav1", "-pix_fmt", pix_fmt, "-preset", modern_preset, "-crf", str(quality)]

        if hdr_info and self._hw_encoder != "vaapi":
            color_space = hdr_info.get("color_space", "bt2020nc") or "bt2020nc"
            if color_space in ("unknown", ""):
                color_space = "bt2020nc"
            v_args += [
                "-color_primaries",
                hdr_info.get("color_primaries", "bt2020"),
                "-color_trc",
                hdr_info.get("color_transfer", "smpte2084"),
                "-colorspace",
                color_space,
            ]

        a_args = ["-c:a", "copy"]
        if reencode_audio:
            a_args = ["-c:a", "libopus", "-b:a", "128k", "-af", "aresample=async=1"]

        cmd = ["ffmpeg", "-y", "-stats_period", "0.5"] + hw_flags + ["-i", input_path]
        cmd += (
            ["-map", "0", "-map_metadata", "0", "-map_chapters", "0", "-fps_mode", "passthrough"]
            + v_args
            + a_args
            + [output_path]
        )

        self.logger.info(f"Engine State [Job {self.job_id}]: Starting encode for {os.path.basename(input_path)}")
        _nv = f" nvenc cuda_decode={hw_decode}" if self._hw_encoder == "nvenc" else ""
        debug(UTILITY_MASS_AV1_ENCODER, f"Job {self.job_id} encode start: {input_path} -> {output_path}{_nv}")

        STALL_TIMEOUT = 300
        _last_output = [time.time()]
        _watchdog_stop = threading.Event()

        def _watchdog():
            while not _watchdog_stop.is_set():
                _watchdog_stop.wait(30)
                if _watchdog_stop.is_set():
                    break
                if time.time() - _last_output[0] > STALL_TIMEOUT:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: ffmpeg stalled. Force killing.")
                    with self._lock:
                        if self._current_process:
                            terminate_ffmpeg_process_tree(self._current_process, log=self.logger)
                    break

        threading.Thread(target=_watchdog, daemon=True).start()

        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1, errors="replace"
            )
            with self._lock:
                self._current_process = proc

            details_detected = emitted_probe_details
            video_info, audio_info = "Unknown", "Unknown"
            error_log = deque(maxlen=50)
            last_pct = 0.0

            for raw in proc.stderr:
                _last_output[0] = time.time()
                for line in raw.replace("\r", "\n").split("\n"):
                    if not line.strip():
                        continue
                    error_log.append(line)

                    if not details_detected:
                        v_match = re.search(
                            r"Stream #.*Video: ([^,]+), [^,]+, (\d+x\d+).*, ([\d.]+) fps",
                            line,
                        )
                        if not v_match:
                            v_match = re.search(
                                r"Stream #.*Video: ([^,]+), [^,]+, (\d+x\d+).*, ([\d.]+) tbr",
                                line,
                            )
                        if v_match:
                            video_info = f"{v_match.group(1)} | {v_match.group(2)} | {v_match.group(3)} fps"
                        a_match = re.search(
                            r"Stream #.*Audio: ([^,]+), (\d+) Hz, ([^,]+)",
                            line,
                        )
                        if a_match:
                            audio_info = (
                                f"{a_match.group(1).strip()} | {a_match.group(2)} Hz | {a_match.group(3).strip()}"
                            )
                        if video_info != "Unknown" and audio_info != "Unknown" and self.on_details:
                            self.on_details(self.job_id, video_info, audio_info)
                            details_detected = True

                    time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line) or re.search(
                        r"out_time=(\d+):(\d+):(\d+\.?\d*)", line
                    )
                    out_time_ms = re.search(r"out_time_ms=(\d+)", line)
                    fps_v, spd_v = _ffmpeg_progress_fps_speed(line)
                    sz_b = _ffmpeg_muxed_size_bytes(line)

                    pct_val: Optional[float] = None
                    curr_time = 0.0
                    time_elapsed_str = "00:00:00"

                    if duration > 0:
                        if out_time_ms:
                            curr_time = int(out_time_ms.group(1)) / 1_000_000.0
                            pct_val = min((curr_time / duration) * 100, 100.0)
                            time_elapsed_str = f"{int(curr_time // 3600):02}:{int((curr_time % 3600) // 60):02}:{int(curr_time % 60):02}"
                        elif time_match:
                            h, m, s = map(float, time_match.groups())
                            curr_time = (h * 3600) + (m * 60) + s
                            pct_val = min((curr_time / duration) * 100, 100.0)
                            time_elapsed_str = f"{int(h):02}:{int(m):02}:{int(s):02}"

                    if pct_val is not None:
                        last_pct = pct_val

                    if not self.on_progress:
                        continue

                    fps_out = fps_v if fps_v is not None else 0.0
                    spd_out = spd_v if spd_v is not None else 0.0

                    if pct_val is not None:
                        self.on_progress(
                            self.job_id,
                            EncodingProgress(
                                file_name=os.path.basename(input_path),
                                percent=pct_val,
                                time_elapsed=time_elapsed_str,
                                fps=fps_out,
                                speed=spd_out,
                                bytes_processed=sz_b,
                            ),
                        )
                    elif (
                        duration > 0
                        and "frame=" in line
                        and re.search(r"time=\s*N/A", line)
                        and (fps_v is not None or spd_v is not None)
                    ):
                        # FFmpeg often reports encoding fps/speed while mux time is not ready yet.
                        self.on_progress(
                            self.job_id,
                            EncodingProgress(
                                file_name=os.path.basename(input_path),
                                percent=last_pct,
                                time_elapsed=time_elapsed_str,
                                fps=fps_out,
                                speed=spd_out,
                                bytes_processed=sz_b,
                            ),
                        )

            success = False
            if proc:
                proc.wait()
                success = proc.returncode == 0
            if not success:
                rc = proc.returncode if proc else None
                self.logger.error(f"FFmpeg failed for {os.path.basename(input_path)}.")
                debug(UTILITY_MASS_AV1_ENCODER, f"FFmpeg failed: {input_path} (returncode={rc})")
                # Log last FFmpeg stderr lines for diagnostics
                if error_log:
                    tail = list(error_log)[-8:]
                    for ln in tail:
                        debug(UTILITY_MASS_AV1_ENCODER, f"ffmpeg stderr: {ln[:200]}")
                # Remove partial output on failure
                if output_path and os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                        debug(UTILITY_MASS_AV1_ENCODER, f"Removed partial: {output_path}")
                    except OSError:
                        pass
                # Retry once with software decode on 183/218 (CUDA decode / hw surface) while keeping NVENC encode.
                # If CUDA decode keeps failing, _nvenc_skip_cuda_hwaccel avoids a wasted attempt on later files.
                if not _retry_software_decode and used_cuda_decode and rc in (183, 218):
                    with AV1EncoderEngine._nvenc_cuda_lock:
                        first_cuda_fail = not AV1EncoderEngine._nvenc_skip_cuda_hwaccel
                        AV1EncoderEngine._nvenc_skip_cuda_hwaccel = True
                    if first_cuda_fail:
                        self.logger.info(
                            "NVENC: CUDA hwaccel decode failed (FFmpeg exit %s). "
                            "Using software decode + NVENC for this file and the rest of this encode run.",
                            rc,
                        )
                    else:
                        debug(
                            UTILITY_MASS_AV1_ENCODER,
                            f"Retry software decode (keep NVENC): {input_path} rc={rc}",
                        )
                    return self.encode_file(
                        input_path,
                        output_path,
                        quality,
                        preset,
                        reencode_audio,
                        hw_accel_decode=True,
                        _retry_software_decode=True,
                    )
            else:
                debug(UTILITY_MASS_AV1_ENCODER, f"Job {self.job_id} encode success: {os.path.basename(input_path)}")
            return success, input_path, output_path
        except Exception as e:
            self.logger.error(f"Error encoding {input_path}: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encode exception: {input_path} — {e}")
            if output_path and os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    debug(UTILITY_MASS_AV1_ENCODER, f"Removed partial: {output_path}")
                except OSError:
                    pass
            return False, input_path, output_path
        finally:
            _watchdog_stop.set()
            # Clear engine handle and close this invocation's stderr. Use local `proc`, not
            # `self._current_process`: a recursive encode_file retry overwrites the latter while
            # the outer Popen's stderr would stay open (ResourceWarning).
            with self._lock:
                if proc is not None and self._current_process is proc:
                    self._current_process = None
            if proc is not None and proc.stderr:
                try:
                    proc.stderr.close()
                except OSError:
                    pass
