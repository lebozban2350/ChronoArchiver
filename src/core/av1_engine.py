import glob
import os
import platform
import threading
import subprocess
import re
import json
import time
import psutil
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Generator
from collections import deque

try:
    from .debug_logger import debug, UTILITY_MASS_AV1_ENCODER
except ImportError:
    from core.debug_logger import debug, UTILITY_MASS_AV1_ENCODER

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
    
    def __init__(self, job_id: int = 0):
        self.job_id = job_id
        self.on_progress: Optional[Callable[[int, EncodingProgress], None]] = None
        self.on_details: Optional[Callable[[int, str, str], None]] = None
        self._encoders_output = self._get_encoders_output()
        self.has_cuda = "av1_nvenc" in self._encoders_output
        self.has_amd_vaapi = "av1_vaapi" in self._encoders_output and platform.system() == "Linux"
        self.has_amd_amf = "av1_amf" in self._encoders_output and platform.system() == "Windows"
        self._hw_encoder = "nvenc" if self.has_cuda else ("vaapi" if self.has_amd_vaapi else ("amf" if self.has_amd_amf else None))
        self._current_process: Optional[subprocess.Popen] = None
        self._is_paused = False
        self._lock = threading.Lock()
        self.logger = logging.getLogger("ChronoArchiver.Encoder")
        if self._hw_encoder:
            self.logger.info(f"HW encoder: {self._hw_encoder}")
        else:
            self.logger.info("HW encoder: none, using libsvtav1")

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
                
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for filename in filenames:
                    name_stem = os.path.splitext(filename)[0]
                    if name_stem.endswith("_av1"):
                        continue
                    if filename.lower().endswith(extensions):
                        full_path = os.path.join(root, filename)
                        try:
                            size = os.path.getsize(full_path)
                        except Exception:
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
                    self._current_process.terminate()
                    self.logger.info(f"Engine State [Job {self.job_id}]: Process cancelled/terminated")
                except Exception as e:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: Failed to cancel process: {e}")

    def _get_video_duration(self, input_path: str) -> float:
        """Gets duration of video in seconds using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", input_path
            ]
            output = subprocess.check_output(cmd, text=True).strip()
            return float(output) if output else 0.0
        except (subprocess.SubprocessError, ValueError, OSError):
            return 0.0

    def _detect_hdr(self, input_path: str) -> dict | None:
        """Detects HDR metadata in the source file using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=color_transfer,color_primaries,color_space,pix_fmt",
                "-of", "json", input_path
            ]
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            data = json.loads(output)
            streams = data.get("streams", [])
            if not streams: return None

            stream = streams[0]
            color_transfer = stream.get("color_transfer", "")
            color_primaries = stream.get("color_primaries", "")
            color_space = stream.get("color_space", "")
            pix_fmt = stream.get("pix_fmt", "")

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

    def encode_file(self, input_path: str, output_path: str, quality: int, preset: str, reencode_audio: bool, hw_accel: bool = False) -> tuple:
        """Encodes a single file and emits progress."""
        duration = self._get_video_duration(input_path)
        hdr_info = self._detect_hdr(input_path)

        hw_flags = []
        v_args = []
        vf_before = []

        if self._hw_encoder == "nvenc" and hw_accel:
            hw_flags = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            pix_fmt = ("p010le" if hdr_info else "yuv420p")
            modern_preset = preset
            try:
                if not modern_preset.startswith("p") or int(modern_preset[1:]) > 7:
                    modern_preset = "p4"
            except ValueError:
                modern_preset = "p4"
            v_args = ["-c:v", "av1_nvenc", "-pix_fmt", pix_fmt, "-rc", "vbr", "-cq", str(quality), "-preset", modern_preset]
        elif self._hw_encoder == "vaapi" and hw_accel:
            dri = glob.glob("/dev/dri/renderD*")
            vaapi_dev = dri[0] if dri else None
            if vaapi_dev:
                hw_flags = ["-vaapi_device", vaapi_dev, "-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]
            else:
                hw_flags = ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]
            qp_vaapi = max(50, min(200, 40 + quality * 4))
            v_args = ["-c:v", "av1_vaapi", "-qp", str(qp_vaapi)]
        elif self._hw_encoder == "amf" and hw_accel:
            hw_flags = []
            qp_amf = max(8, min(52, 10 + quality))
            v_args = ["-c:v", "av1_amf", "-qp_i", str(qp_amf), "-qp_p", str(qp_amf)]
        else:
            p_map = {"p1":"12", "p2":"10", "p3":"8", "p4":"6", "p5":"4", "p6":"2", "p7":"0"}
            modern_preset = p_map.get(preset, "6")
            pix_fmt = "yuv420p10le" if hdr_info else "yuv420p"
            v_args = ["-c:v", "libsvtav1", "-pix_fmt", pix_fmt, "-preset", modern_preset, "-crf", str(quality)]

        if hdr_info and self._hw_encoder != "vaapi":
            color_space = hdr_info.get("color_space", "bt2020nc") or "bt2020nc"
            if color_space in ("unknown", ""):
                color_space = "bt2020nc"
            v_args += [
                "-color_primaries", hdr_info.get("color_primaries", "bt2020"),
                "-color_trc", hdr_info.get("color_transfer", "smpte2084"),
                "-colorspace", color_space,
            ]

        a_args = ["-c:a", "copy"]
        if reencode_audio:
            a_args = ["-c:a", "libopus", "-b:a", "128k", "-af", "aresample=async=1"]

        cmd = ["ffmpeg", "-y", "-stats_period", "0.5"] + hw_flags + ["-i", input_path]
        if vf_before:
            cmd += ["-vf", ",".join(vf_before)]
        cmd += ["-map", "0", "-map_metadata", "0", "-map_chapters", "0", "-fps_mode", "passthrough"] + v_args + a_args + [output_path]

        self.logger.info(f"Engine State [Job {self.job_id}]: Starting encode for {os.path.basename(input_path)}")
        debug(UTILITY_MASS_AV1_ENCODER, f"Job {self.job_id} encode start: {input_path} -> {output_path}")

        STALL_TIMEOUT = 300
        _last_output = [time.time()]
        _watchdog_stop = threading.Event()

        def _watchdog():
            while not _watchdog_stop.is_set():
                _watchdog_stop.wait(30)
                if _watchdog_stop.is_set(): break
                if time.time() - _last_output[0] > STALL_TIMEOUT:
                    self.logger.error(f"Engine Error [Job {self.job_id}]: ffmpeg stalled. Force killing.")
                    with self._lock:
                        if self._current_process: self._current_process.kill()
                    break

        threading.Thread(target=_watchdog, daemon=True).start()

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1, errors='replace')
            with self._lock: self._current_process = proc
            
            details_detected = False
            video_info, audio_info = "Unknown", "Unknown"
            error_log = deque(maxlen=50)

            for raw in self._current_process.stderr:
                _last_output[0] = time.time()
                for line in raw.replace("\r", "\n").split("\n"):
                    if not line.strip(): continue
                    error_log.append(line)
                    
                    if not details_detected:
                        v_match = re.search(r"Stream #.*Video: ([^,]+), [^,]+, (\d+x\d+).*, ([\d.]+) fps", line)
                        if v_match: video_info = f"{v_match.group(1)} | {v_match.group(2)} | {v_match.group(3)} fps"
                        a_match = re.search(r"Stream #.*Audio: ([^,]+), \d+ Hz, ([^,]+)", line)
                        if a_match: audio_info = f"{a_match.group(1)} | {a_match.group(2)}"
                        if video_info != "Unknown" and audio_info != "Unknown" and self.on_details:
                            self.on_details(self.job_id, video_info, audio_info)
                            details_detected = True

                    time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line) or re.search(r"out_time=(\d+):(\d+):(\d+\.?\d*)", line)
                    out_time_ms = re.search(r"out_time_ms=(\d+)", line)
                    if out_time_ms and duration > 0:
                        curr_time = int(out_time_ms.group(1)) / 1_000_000.0
                        percent = min((curr_time / duration) * 100, 100.0)
                        fps_match = re.search(r"fps=\s*([\d.]+)", line)
                        speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                        size_match = re.search(r"size=\s*(\d+)kB", line)
                        if self.on_progress:
                            self.on_progress(self.job_id, EncodingProgress(
                                file_name=os.path.basename(input_path), percent=percent,
                                time_elapsed=f"{int(curr_time//3600):02}:{int((curr_time%3600)//60):02}:{int(curr_time%60):02}",
                                fps=float(fps_match.group(1)) if fps_match else 0.0,
                                speed=float(speed_match.group(1)) if speed_match else 0.0,
                                bytes_processed=int(size_match.group(1)) * 1024 if size_match else 0
                            ))
                    elif time_match and duration > 0:
                        h, m, s = map(float, time_match.groups())
                        curr_time = (h * 3600) + (m * 60) + s
                        percent = min((curr_time / duration) * 100, 100.0)
                        fps_match = re.search(r"fps=\s*([\d.]+)", line)
                        speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                        size_match = re.search(r"size=\s*(\d+)kB", line)
                        if self.on_progress:
                            self.on_progress(self.job_id, EncodingProgress(
                                file_name=os.path.basename(input_path), percent=percent,
                                time_elapsed=f"{int(h):02}:{int(m):02}:{int(s):02}",
                                fps=float(fps_match.group(1)) if fps_match else 0.0,
                                speed=float(speed_match.group(1)) if speed_match else 0.0,
                                bytes_processed=int(size_match.group(1)) * 1024 if size_match else 0
                            ))

            success = False
            if self._current_process:
                self._current_process.wait()
                success = self._current_process.returncode == 0
            if not success:
                self.logger.error(f"FFmpeg failed for {os.path.basename(input_path)}.")
                debug(UTILITY_MASS_AV1_ENCODER, f"FFmpeg failed: {input_path} (returncode={self._current_process.returncode if self._current_process else '?'})")
                # Remove partial output on failure
                if output_path and os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                        debug(UTILITY_MASS_AV1_ENCODER, f"Removed partial: {output_path}")
                    except OSError:
                        pass
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
            with self._lock: self._current_process = None
