import os
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
        self.has_cuda = self._check_cuda_support()
        self._current_process: Optional[subprocess.Popen] = None
        self._is_paused = False
        self._lock = threading.Lock()
        self.logger = logging.getLogger("MediaOrganizer")

    def _check_cuda_support(self) -> bool:
        """Checks for NVIDIA AV1 NVENC support via ffmpeg."""
        try:
            output = subprocess.check_output(["ffmpeg", "-encoders"], stderr=subprocess.STDOUT, text=True)
            has_cuda = "av1_nvenc" in output
            self.logger.info(f"CUDA AV1 Support (av1_nvenc): {has_cuda}")
            return has_cuda
        except Exception:
            return False

    def scan_files(self, directory: str, stop_event: Optional[threading.Event] = None) -> Generator[tuple, None, None]:
        """Scans a directory for supported video files, yielding results for real-time feedback."""
        extensions = (".mpg", ".mp4", ".ts", ".avi", ".3gp", ".mkv")
        
        try:
            for root, dirs, filenames in os.walk(directory):
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
                            yield (full_path, size)
                        except OSError:
                            yield (full_path, 0)
        except Exception as e:
            self.logger.error(f"Failed to scan files in {directory}: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Scan error: {directory} — {e}")

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
        encoder = "av1_nvenc" if self.has_cuda else "libsvtav1"
        
        # Preset mapping
        modern_preset = preset
        if self.has_cuda:
            try:
                if not modern_preset.startswith("p") or int(modern_preset[1:]) > 7:
                    modern_preset = "p4"
            except ValueError: modern_preset = "p4"
        else:
            p_map = {"p1":"12", "p2":"10", "p3":"8", "p4":"6", "p5":"4", "p6":"2", "p7":"0"}
            modern_preset = p_map.get(modern_preset, "6")

        hdr_info = self._detect_hdr(input_path)
        pix_fmt = ("p010le" if self.has_cuda else "yuv420p10le") if hdr_info else "yuv420p"

        v_args = ["-c:v", encoder, "-pix_fmt", pix_fmt]
        if self.has_cuda:
            v_args += ["-rc", "vbr", "-cq", str(quality), "-preset", modern_preset]
        else:
            v_args += ["-preset", modern_preset, "-crf", str(quality)]

        if hdr_info:
            color_space = hdr_info.get("color_space", "bt2020nc")
            if not color_space or color_space in ("unknown", ""): color_space = "bt2020nc"
            v_args += [
                "-color_primaries", hdr_info.get("color_primaries", "bt2020"),
                "-color_trc", hdr_info.get("color_transfer", "smpte2084"),
                "-colorspace", color_space,
            ]

        a_args = ["-c:a", "copy"]
        if reencode_audio:
            a_args = ["-c:a", "libopus", "-b:a", "128k", "-af", "aresample=async=1"]

        hw_flags = ["-hwaccel", "cuda" if self.has_cuda else "auto"] if hw_accel else []
        
        cmd = [
            "ffmpeg", "-y",
        ] + hw_flags + [
            "-i", input_path, "-map", "0", "-map_metadata", "0", "-map_chapters", "0", "-fps_mode", "passthrough"
        ] + v_args + a_args + [output_path]

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

            for line in self._current_process.stderr:
                _last_output[0] = time.time()
                if not line: continue
                error_log.append(line)
                
                if not details_detected:
                    v_match = re.search(r"Stream #.*Video: ([^,]+), [^,]+, (\d+x\d+).*, ([\d.]+) fps", line)
                    if v_match: video_info = f"{v_match.group(1)} | {v_match.group(2)} | {v_match.group(3)} fps"
                    a_match = re.search(r"Stream #.*Audio: ([^,]+), \d+ Hz, ([^,]+)", line)
                    if a_match: audio_info = f"{a_match.group(1)} | {a_match.group(2)}"
                    if video_info != "Unknown" and audio_info != "Unknown" and self.on_details:
                        self.on_details(self.job_id, video_info, audio_info)
                        details_detected = True

                time_match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                if time_match and duration > 0:
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
            else:
                debug(UTILITY_MASS_AV1_ENCODER, f"Job {self.job_id} encode success: {os.path.basename(input_path)}")
            return success, input_path, output_path
        except Exception as e:
            self.logger.error(f"Error encoding {input_path}: {e}")
            debug(UTILITY_MASS_AV1_ENCODER, f"Encode exception: {input_path} — {e}")
            return False, input_path, output_path
        finally:
            _watchdog_stop.set()
            with self._lock: self._current_process = None
