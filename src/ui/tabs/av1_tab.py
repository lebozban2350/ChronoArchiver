import customtkinter as ctk
import os
import platform
import threading
import time
import psutil
import subprocess
from tkinter import filedialog, messagebox
import concurrent.futures
from core.av1_engine import AV1EncoderEngine, EncodingProgress
from core.av1_settings import AV1Settings
from ui.theme import BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, ACCENT, TEXT_PRIMARY, TEXT_MUTED, SEPARATOR, FONT_MAIN, FONT_HEADER


class ThreadSlot(ctk.CTkFrame):
    """Represents a high-density monitoring slot for a single encoding thread."""
    def __init__(self, master, thread_id):
        super().__init__(master, fg_color=BG_TERTIARY, corner_radius=6,
                         border_width=1, border_color=SEPARATOR)
        self.thread_id = thread_id

        self.lbl_title = ctk.CTkLabel(
            self, text=f"THREAD {thread_id}",
            font=(FONT_HEADER[0], 9, "bold"), text_color=TEXT_MUTED)
        self.lbl_title.pack(anchor="w", padx=8, pady=(4, 0))

        self.progress = ctk.CTkProgressBar(self, height=12, progress_color=ACCENT)
        self.progress.pack(fill="x", padx=8, pady=4)
        self.progress.set(0)

        self.info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.info_frame.pack(fill="x", padx=8, pady=(0, 4))

        self.codec_frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        self.codec_frame.pack(side="left", fill="both", expand=True)

        self.lbl_vid = ctk.CTkLabel(
            self.codec_frame, text="VIDEO: -",
            font=(FONT_MAIN[0], 8), text_color=TEXT_MUTED, anchor="w", height=10)
        self.lbl_vid.pack(fill="x")
        self.lbl_aud = ctk.CTkLabel(
            self.codec_frame, text="AUDIO: -",
            font=(FONT_MAIN[0], 8), text_color=TEXT_MUTED, anchor="w", height=10)
        self.lbl_aud.pack(fill="x")

        self.lbl_speed = ctk.CTkLabel(
            self.info_frame, text="0.0x",
            font=(FONT_HEADER[0], 11, "bold"), text_color=ACCENT)
        self.lbl_speed.pack(side="right", padx=(5, 0))

    def update(self, filename, percent, vid_info, aud_info, speed):
        short = (filename[:20] + "...") if len(filename) > 20 else filename
        self.lbl_title.configure(text=f"T{self.thread_id}: {short}")
        self.progress.set(percent / 100)
        if vid_info:
            self.lbl_vid.configure(text=f"VID: {vid_info}")
        if aud_info:
            self.lbl_aud.configure(text=f"AUD: {aud_info}")
        self.lbl_speed.configure(text=f"{speed:.2f}x")

    def reset(self):
        self.lbl_title.configure(text=f"THREAD {self.thread_id}")
        self.progress.set(0)
        self.lbl_vid.configure(text="VIDEO: -")
        self.lbl_aud.configure(text="AUDIO: -")
        self.lbl_speed.configure(text="0.0x")


def _hint(parent, text):
    """Compact muted hint label — same style as the original Mass AV1 Encoder."""
    ctk.CTkLabel(
        parent, text=text,
        font=(FONT_MAIN[0], 8), text_color="#444444", anchor="w"
    ).pack(anchor="w", padx=(22, 0))


class AV1EncoderTab(ctk.CTkFrame):
    def __init__(self, master, log_callback, file_logger, status_callback, background_callback):
        super().__init__(master, fg_color="transparent")
        self.log_callback      = log_callback
        self.file_logger       = file_logger
        self.status_callback   = status_callback
        self.background_callback = background_callback
        self.settings = AV1Settings()
        self.engine   = AV1EncoderEngine()

        self.is_encoding      = False
        self.is_paused        = False
        self.start_time       = 0.0
        self.total_space_saved = 0
        self.active_worker_engines: set = set()
        self.worker_lock      = threading.Lock()

        self.gpu_usage_cache  = "N/A"
        self.last_gpu_check   = 0.0

        self.slots: list[ThreadSlot] = []
        self.job_to_slot: dict = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── TOP STRIP ──────────────────────────────────────────────────────────
        self.frame_top = ctk.CTkFrame(self, fg_color=BG_SECONDARY)
        self.frame_top.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        # 4 columns: Directories | Configuration | Options | Metrics
        self.frame_top.grid_columnconfigure(0, weight=3)
        self.frame_top.grid_columnconfigure(1, weight=2)
        self.frame_top.grid_columnconfigure(2, weight=2)
        self.frame_top.grid_columnconfigure(3, weight=0)

        # ── 1. DIRECTORIES ────────────────────────────────────────────────────
        self.frame_paths = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.frame_paths.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.frame_paths, text="DIRECTORIES",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 4))

        # Source row — entry + Browse side by side
        src_row = ctk.CTkFrame(self.frame_paths, fg_color="transparent")
        src_row.pack(fill="x", pady=(0, 0))
        self.entry_src = ctk.CTkEntry(
            src_row, placeholder_text="Source directory...",
            fg_color=BG_TERTIARY, border_width=1)
        self.entry_src.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_src.insert(0, self.settings.get("source_folder"))
        ctk.CTkButton(
            src_row, text="Browse", width=70, height=28, fg_color=ACCENT,
            command=self.browse_source
        ).pack(side="right")

        ctk.CTkLabel(
            self.frame_paths,
            text="Source — local path or network share",
            font=(FONT_MAIN[0], 9), text_color=TEXT_MUTED, anchor="w"
        ).pack(fill="x", pady=(1, 6))

        # Target row — entry + Browse side by side
        dst_row = ctk.CTkFrame(self.frame_paths, fg_color="transparent")
        dst_row.pack(fill="x", pady=(0, 0))
        self.entry_dst = ctk.CTkEntry(
            dst_row, placeholder_text="Target directory...",
            fg_color=BG_TERTIARY, border_width=1)
        self.entry_dst.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_dst.insert(0, self.settings.get("target_folder"))
        ctk.CTkButton(
            dst_row, text="Browse", width=70, height=28, fg_color=ACCENT,
            command=self.browse_target
        ).pack(side="right")

        ctk.CTkLabel(
            self.frame_paths,
            text="Target — AV1 encoded output destination",
            font=(FONT_MAIN[0], 9), text_color=TEXT_MUTED, anchor="w"
        ).pack(fill="x", pady=(1, 0))

        # ── 2. CONFIGURATION ──────────────────────────────────────────────────
        self.frame_config = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.frame_config.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.frame_config, text="CONFIGURATION",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 4))

        cfg = ctk.CTkFrame(self.frame_config, fg_color="transparent")
        cfg.pack(fill="both", expand=True)
        cfg.grid_columnconfigure(1, weight=1)

        # Quality
        ctk.CTkLabel(cfg, text="Quality:", font=FONT_MAIN, text_color=TEXT_MUTED
                     ).grid(row=0, column=0, sticky="w", pady=3)
        q_inner = ctk.CTkFrame(cfg, fg_color="transparent")
        q_inner.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.slider_quality = ctk.CTkSlider(
            q_inner, from_=0, to=63, width=90, command=self.on_quality_change)
        self.slider_quality.set(self.settings.get("quality"))
        self.slider_quality.pack(side="left")
        self.lbl_quality_val = ctk.CTkLabel(
            q_inner, text=str(self.settings.get("quality")),
            font=FONT_MAIN, text_color=ACCENT, width=28)
        self.lbl_quality_val.pack(side="left", padx=4)
        ctk.CTkLabel(
            q_inner, text="CQ level — lower = better",
            font=(FONT_MAIN[0], 8), text_color="#444444"
        ).pack(side="left")

        # Preset
        ctk.CTkLabel(cfg, text="Preset:", font=FONT_MAIN, text_color=TEXT_MUTED
                     ).grid(row=1, column=0, sticky="w", pady=3)
        preset_options = [
            "P7: Deep Archival", "P6: High Quality", "P5: Balanced",
            "P4: Standard",      "P3: Fast",         "P2: Draft",
            "P1: Preview"
        ]
        self.combo_preset = ctk.CTkComboBox(
            cfg, values=preset_options, width=155, command=self.on_preset_change)
        curr_p = self.settings.get("preset").upper()
        found = next((x for x in preset_options if x.startswith(curr_p)), "P4: Standard")
        self.combo_preset.set(found)
        self.combo_preset.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=3)

        # Threads
        ctk.CTkLabel(cfg, text="Threads:", font=FONT_MAIN, text_color=TEXT_MUTED
                     ).grid(row=2, column=0, sticky="w", pady=3)
        t_inner = ctk.CTkFrame(cfg, fg_color="transparent")
        t_inner.grid(row=2, column=1, sticky="w", padx=(5, 0))
        self.combo_jobs = ctk.CTkComboBox(
            t_inner, values=["1", "2", "4"], width=65, command=self.on_jobs_change)
        self.combo_jobs.set(str(self.settings.get("concurrent_jobs")))
        self.combo_jobs.pack(side="left")
        ctk.CTkLabel(
            t_inner, text="Parallel encoding slots",
            font=(FONT_MAIN[0], 8), text_color="#444444"
        ).pack(side="left", padx=4)

        # Optimize Audio
        ctk.CTkLabel(cfg, text="", font=FONT_MAIN).grid(row=3, column=0)  # spacer
        self.check_audio = ctk.CTkCheckBox(
            cfg, text="Optimize Audio",
            font=(FONT_MAIN[0], 10),
            command=lambda: self.settings.set("reencode_audio", bool(self.check_audio.get())))
        if self.settings.get("reencode_audio"):
            self.check_audio.select()
        self.check_audio.grid(row=3, column=1, sticky="w", padx=(5, 0), pady=3)

        ctk.CTkLabel(
            cfg, text="Re-encode PCM/unsupported to Opus",
            font=(FONT_MAIN[0], 8), text_color="#444444", anchor="w"
        ).grid(row=4, column=1, sticky="w", padx=(26, 0))

        # ── 3. OPTIONS ────────────────────────────────────────────────────────
        self.frame_options = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.frame_options.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.frame_options, text="OPTIONS",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 4))

        # Use a plain frame (no scrollbar) with tight spacing
        opt = ctk.CTkFrame(self.frame_options, fg_color="transparent")
        opt.pack(fill="both", expand=True)

        # Keep Subdirs
        self.check_subdirs = ctk.CTkCheckBox(
            opt, text="Keep Subdirs", font=(FONT_MAIN[0], 10),
            command=lambda: self.settings.set("maintain_structure", bool(self.check_subdirs.get())))
        self.check_subdirs.pack(anchor="w", pady=(2, 0))
        if self.settings.get("maintain_structure"):
            self.check_subdirs.select()
        _hint(opt, "Mirror source folder tree in target")

        # Shutdown When Done
        self.check_shutdown = ctk.CTkCheckBox(
            opt, text="Shutdown When Done", font=(FONT_MAIN[0], 10),
            command=lambda: self.settings.set("shutdown_on_finish", bool(self.check_shutdown.get())))
        self.check_shutdown.pack(anchor="w", pady=(4, 0))
        if self.settings.get("shutdown_on_finish"):
            self.check_shutdown.select()
        _hint(opt, "Power off system after queue finishes")

        # HW Accelerated Decode
        self.check_hwaccel = ctk.CTkCheckBox(
            opt, text="HW Accelerated Decode", font=(FONT_MAIN[0], 10),
            command=lambda: self.settings.set("hw_accel_decode", bool(self.check_hwaccel.get())))
        self.check_hwaccel.pack(anchor="w", pady=(4, 0))
        if self.settings.get("hw_accel_decode"):
            self.check_hwaccel.select()
        _hint(opt, "Use GPU for demux / decode stage")

        # Skip Short Clips — checkbox + HH MM SS on same row
        skip_row = ctk.CTkFrame(opt, fg_color="transparent")
        skip_row.pack(anchor="w", fill="x", pady=(4, 0))
        self.check_skip = ctk.CTkCheckBox(
            skip_row, text="Skip Short Clips", font=(FONT_MAIN[0], 10),
            command=self.toggle_skip_fields)
        self.check_skip.pack(side="left")
        if self.settings.get("rejects_enabled"):
            self.check_skip.select()

        self.entry_skip_h = ctk.CTkEntry(skip_row, width=26, height=20, font=(FONT_MAIN[0], 9))
        self.entry_skip_h.pack(side="left", padx=(6, 2))
        self.entry_skip_h.insert(0, str(self.settings.get("rejects_h")))

        self.entry_skip_m = ctk.CTkEntry(skip_row, width=26, height=20, font=(FONT_MAIN[0], 9))
        self.entry_skip_m.pack(side="left", padx=2)
        self.entry_skip_m.insert(0, str(self.settings.get("rejects_m")))

        self.entry_skip_s = ctk.CTkEntry(skip_row, width=26, height=20, font=(FONT_MAIN[0], 9))
        self.entry_skip_s.pack(side="left", padx=2)
        self.entry_skip_s.insert(0, str(self.settings.get("rejects_s")))

        _hint(opt, "Skip files shorter than HH:MM:SS threshold")

        # Delete Source on Success
        self.check_del = ctk.CTkCheckBox(
            opt, text="Delete Source on Success",
            font=(FONT_MAIN[0], 10), text_color="#ef4444",
            command=self.on_delete_toggle)
        self.check_del.pack(anchor="w", pady=(4, 0))
        if self.settings.get("delete_on_success"):
            self.check_del.select()

        self.check_del_confirm = ctk.CTkCheckBox(
            opt, text="Confirm Delete Safety",
            font=(FONT_MAIN[0], 9), text_color=TEXT_MUTED,
            command=self.on_delete_toggle)
        self.check_del_confirm.pack(anchor="w", padx=(20, 0))
        if self.settings.get("delete_on_success_confirm"):
            self.check_del_confirm.select()
        _hint(opt, "Both boxes must be checked to enable")

        # Initialise skip field states
        self.toggle_skip_fields()

        # ── 4. METRICS ────────────────────────────────────────────────────────
        self.frame_metrics = ctk.CTkFrame(self.frame_top, fg_color="transparent", width=110)
        self.frame_metrics.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")
        self.frame_metrics.pack_propagate(False)

        ctk.CTkLabel(
            self.frame_metrics, text="METRICS",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 6))

        self.lbl_cpu = ctk.CTkLabel(
            self.frame_metrics, text="CPU: 0%",
            font=(FONT_MAIN[0], 10), anchor="w")
        self.lbl_cpu.pack(fill="x", pady=1)

        self.lbl_gpu = ctk.CTkLabel(
            self.frame_metrics, text="GPU: N/A",
            font=(FONT_MAIN[0], 10), anchor="w")
        self.lbl_gpu.pack(fill="x", pady=1)

        self.lbl_ram = ctk.CTkLabel(
            self.frame_metrics, text="RAM: 0%",
            font=(FONT_MAIN[0], 10), anchor="w")
        self.lbl_ram.pack(fill="x", pady=1)

        threading.Thread(target=self._metrics_loop, daemon=True).start()

        # ── MIDDLE: Thread slots + Queue ──────────────────────────────────────
        self.frame_mid = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_mid.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.frame_mid.grid_columnconfigure(0, weight=3)
        self.frame_mid.grid_columnconfigure(1, weight=1)
        self.frame_mid.grid_rowconfigure(0, weight=1)

        self.frame_slots_container = ctk.CTkFrame(self.frame_mid, fg_color=BG_SECONDARY)
        self.frame_slots_container.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        ctk.CTkLabel(
            self.frame_slots_container, text="ACTIVE THREADS",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", padx=10, pady=5)

        self.frame_slots = ctk.CTkFrame(self.frame_slots_container, fg_color="transparent")
        self.frame_slots.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for i in range(4):
            slot = ThreadSlot(self.frame_slots, i + 1)
            slot.pack(fill="x", pady=2)
            self.slots.append(slot)
            if i >= self.settings.get("concurrent_jobs"):
                slot.pack_forget()

        self.frame_queue = ctk.CTkFrame(self.frame_mid, fg_color=BG_SECONDARY)
        self.frame_queue.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(
            self.frame_queue, text="QUEUE",
            font=FONT_HEADER, text_color=TEXT_MUTED
        ).pack(anchor="w", padx=10, pady=5)
        self.scroll_queue = ctk.CTkScrollableFrame(
            self.frame_queue, fg_color=BG_TERTIARY, corner_radius=0)
        self.scroll_queue.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ── BOTTOM: Progress strip + buttons ──────────────────────────────────
        self.frame_bot = ctk.CTkFrame(self, fg_color=BG_SECONDARY)
        self.frame_bot.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")

        metric_strip = ctk.CTkFrame(self.frame_bot, fg_color="transparent")
        metric_strip.pack(fill="x", padx=10, pady=(6, 0))

        self.lbl_elapsed = ctk.CTkLabel(
            metric_strip, text="ELAPSED: 00:00:00",
            font=(FONT_MAIN[0], 10, "bold"), text_color=TEXT_MUTED)
        self.lbl_elapsed.pack(side="left")

        self.lbl_saved = ctk.CTkLabel(
            metric_strip, text="SPACE SAVED: 0 MB",
            font=(FONT_MAIN[0], 10, "bold"), text_color="#10b981")
        self.lbl_saved.pack(side="left", padx=20)

        self.lbl_eta = ctk.CTkLabel(
            metric_strip, text="ETA: --:--:--",
            font=(FONT_MAIN[0], 10, "bold"), text_color=ACCENT)
        self.lbl_eta.pack(side="right")

        self.master_progress = ctk.CTkProgressBar(
            self.frame_bot, height=14, progress_color="#059669")
        self.master_progress.pack(fill="x", padx=10, pady=5)
        self.master_progress.set(0)

        self.lbl_master_stats = ctk.CTkLabel(
            self.frame_bot, text="0/0 Files Processed (0%)",
            font=(FONT_MAIN[0], 10), text_color=TEXT_MUTED)
        self.lbl_master_stats.pack(pady=(0, 4))

        btn_row = ctk.CTkFrame(self.frame_bot, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        self.btn_start = ctk.CTkButton(
            btn_row, text="START ENCODING", font=FONT_HEADER,
            fg_color="#064e3b", hover_color="#065f46", height=40,
            command=self.start_encoding)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_pause = ctk.CTkButton(
            btn_row, text="PAUSE", font=FONT_HEADER,
            fg_color=BG_TERTIARY, hover_color=BG_SECONDARY,
            width=100, height=40, state="disabled",
            command=self.toggle_pause)
        self.btn_pause.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            btn_row, text="STOP", font=FONT_HEADER,
            fg_color="#450a0a", hover_color="#7f1d1d",
            height=40, state="disabled",
            command=self.stop_encoding)
        self.btn_stop.pack(side="right", padx=(5, 0))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def browse_source(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_src.delete(0, "end")
            self.entry_src.insert(0, path)
            self.settings.set("source_folder", path)

    def browse_target(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_dst.delete(0, "end")
            self.entry_dst.insert(0, path)
            self.settings.set("target_folder", path)

    def on_quality_change(self, val):
        self.lbl_quality_val.configure(text=str(int(val)))
        self.settings.set("quality", int(val))

    def on_preset_change(self, val):
        p_val = val.split(":")[0].lower()   # "P4: Standard" → "p4"
        self.settings.set("preset", p_val)

    def on_jobs_change(self, val):
        num = int(val)
        self.settings.set("concurrent_jobs", num)
        for i, slot in enumerate(self.slots):
            if i < num:
                slot.pack(fill="x", pady=2)
            else:
                slot.pack_forget()

    def toggle_skip_fields(self):
        enabled = bool(self.check_skip.get())
        self.settings.set("rejects_enabled", enabled)
        state = "normal" if enabled else "disabled"
        self.entry_skip_h.configure(state=state)
        self.entry_skip_m.configure(state=state)
        self.entry_skip_s.configure(state=state)

    def on_delete_toggle(self):
        self.settings.set("delete_on_success",         bool(self.check_del.get()))
        self.settings.set("delete_on_success_confirm", bool(self.check_del_confirm.get()))

    # ── Metrics loop ──────────────────────────────────────────────────────────

    def _metrics_loop(self):
        while True:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                if time.time() - self.last_gpu_check > 5:
                    self.gpu_usage_cache = self._get_gpu_usage()
                    self.last_gpu_check  = time.time()
                gpu = self.gpu_usage_cache
                self.after(0, lambda c=cpu, g=gpu, r=ram: (
                    self.lbl_cpu.configure(text=f"CPU: {c}%"),
                    self.lbl_gpu.configure(text=f"GPU: {g}"),
                    self.lbl_ram.configure(text=f"RAM: {r}%"),
                ))
            except Exception:
                pass
            time.sleep(2)

    def _get_gpu_usage(self) -> str:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                stderr=subprocess.STDOUT, text=True).strip()
            return f"{out}%"
        except Exception:
            return "N/A"

    # ── Pause / Stop ──────────────────────────────────────────────────────────

    def toggle_pause(self):
        if not self.is_encoding:
            return
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.configure(text="RESUME", fg_color=ACCENT)
            with self.worker_lock:
                for eng in self.active_worker_engines:
                    eng.pause()
            self.log_callback("Encoding paused.")
        else:
            self.btn_pause.configure(text="PAUSE", fg_color=BG_TERTIARY)
            with self.worker_lock:
                for eng in self.active_worker_engines:
                    eng.resume()
            self.log_callback("Encoding resumed.")

    def start_encoding(self):
        src = self.entry_src.get()
        dst = self.entry_dst.get()
        if not src or not dst:
            messagebox.showerror("Error", "Please select source and target directories.")
            return

        self.is_encoding       = True
        self.is_paused         = False
        self.start_time        = time.time()
        self.total_space_saved = 0

        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="PAUSE", fg_color=BG_TERTIARY)
        self.btn_stop.configure(state="normal")
        self.log_callback("Batch process started.")
        self.status_callback("ENCODING", "#059669")

        threading.Thread(target=self._run_job,      args=(src, dst), daemon=True).start()
        threading.Thread(target=self._update_timer,                   daemon=True).start()

    def stop_encoding(self):
        self.is_encoding = False
        self.is_paused   = False
        with self.worker_lock:
            for eng in self.active_worker_engines:
                eng.cancel()
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="PAUSE")
        self.btn_stop.configure(state="disabled")
        for slot in self.slots:
            slot.reset()
        self.status_callback("READY")
        self.background_callback("Idle")

    def _update_timer(self):
        while self.is_encoding:
            elapsed = int(time.time() - self.start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            self.after(0, lambda h=h, m=m, s=s:
                       self.lbl_elapsed.configure(text=f"ELAPSED: {h:02}:{m:02}:{s:02}"))
            time.sleep(1)

    # ── Main job runner ───────────────────────────────────────────────────────

    def _run_job(self, src: str, dst: str):
        self.log_callback("Scanning for video files...")
        files = list(self.engine.scan_files(src))
        if not files:
            self.log_callback("No compatible files found.")
            self.after(0, self.stop_encoding)
            return

        self.log_callback(f"Found {len(files)} files to encode.")
        self.after(0, self._populate_queue_list, [os.path.basename(f[0]) for f in files])

        total_files = len(files)
        processed_count = [0]
        counter_lock = threading.Lock()

        # Build skip threshold
        reject_threshold = 0
        if self.settings.get("rejects_enabled"):
            try:
                h = int(self.entry_skip_h.get() or 0)
                m = int(self.entry_skip_m.get() or 0)
                s = int(self.entry_skip_s.get() or 0)
                reject_threshold = h * 3600 + m * 60 + s
            except ValueError:
                pass

        def encode_worker(file_info, slot_idx):
            if not self.is_encoding:
                return
            file_path, size = file_info

            # Skip short clips
            if reject_threshold > 0:
                duration = self.engine._get_video_duration(file_path)
                if duration < reject_threshold:
                    self.log_callback(
                        f"Skipping {os.path.basename(file_path)} "
                        f"(duration {duration:.1f}s < {reject_threshold}s)")
                    with counter_lock:
                        processed_count[0] += 1
                        self.after(
                            0, self._update_master_ui,
                            processed_count[0], total_files,
                            processed_count[0] / total_files)
                    return

            worker_engine = AV1EncoderEngine(job_id=slot_idx)
            worker_engine.on_progress = lambda j, p: self.after(
                0, lambda p=p, si=slot_idx:
                self.slots[si].update(p.file_name, p.percent, None, None, p.speed))
            worker_engine.on_details = lambda j, v, a: self.after(
                0, lambda v=v, a=a, si=slot_idx:
                self.slots[si].update("", 0, v, a, 0))

            with self.worker_lock:
                if not self.is_encoding:
                    return
                self.active_worker_engines.add(worker_engine)
                if self.is_paused:
                    worker_engine.pause()

            filename = os.path.basename(file_path)
            if self.settings.get("maintain_structure"):
                rel   = os.path.relpath(file_path, src)
                tpath = os.path.join(dst, os.path.splitext(rel)[0] + "_av1.mkv")
                os.makedirs(os.path.dirname(tpath), exist_ok=True)
            else:
                tpath = os.path.join(dst, os.path.splitext(filename)[0] + "_av1.mkv")

            try:
                success, _, out_p = worker_engine.encode_file(
                    file_path, tpath,
                    self.settings.get("quality"),
                    self.settings.get("preset"),
                    self.settings.get("reencode_audio"),
                    hw_accel=self.settings.get("hw_accel_decode"),
                )
                if success and self.is_encoding:
                    try:
                        saved = size - os.path.getsize(out_p)
                        with counter_lock:
                            self.total_space_saved += max(0, saved)
                            mb = self.total_space_saved // (1024 * 1024)
                            self.after(
                                0, lambda mb=mb:
                                self.lbl_saved.configure(text=f"SPACE SAVED: {mb} MB"))
                    except OSError:
                        pass

                    if (self.settings.get("delete_on_success") and
                            self.settings.get("delete_on_success_confirm")):
                        try:
                            os.remove(file_path)
                            self.log_callback(f"Deleted source: {filename}")
                        except Exception as e:
                            self.log_callback(f"Delete failed ({filename}): {e}")
            finally:
                with self.worker_lock:
                    self.active_worker_engines.discard(worker_engine)
                with counter_lock:
                    processed_count[0] += 1
                    prog = processed_count[0] / total_files
                    self.after(0, self._update_master_ui, processed_count[0], total_files, prog)

        concurrent_jobs = self.settings.get("concurrent_jobs", 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_jobs) as executor:
            for i, fi in enumerate(files):
                executor.submit(encode_worker, fi, i % concurrent_jobs)

        self.after(0, self.stop_encoding)
        self.log_callback("Batch process complete.")

        if self.settings.get("shutdown_on_finish"):
            self.log_callback("Shutting down system as requested...")
            if platform.system() == "Windows":
                os.system("shutdown /s /t 60")
            else:
                os.system("shutdown -h +1")

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _populate_queue_list(self, filenames):
        for w in self.scroll_queue.winfo_children():
            w.destroy()
        for f in filenames:
            ctk.CTkLabel(
                self.scroll_queue, text=f,
                font=(FONT_MAIN[0], 9), text_color=TEXT_PRIMARY, anchor="w"
            ).pack(fill="x", padx=5)

    def _update_master_ui(self, count, total, prog):
        self.master_progress.set(prog)
        self.lbl_master_stats.configure(
            text=f"{count}/{total} Files Processed ({int(prog * 100)}%)")
        if prog > 0:
            elapsed   = time.time() - self.start_time
            remaining = int(elapsed / prog - elapsed)
            h, m, s   = remaining // 3600, (remaining % 3600) // 60, remaining % 60
            self.lbl_eta.configure(text=f"ETA: {h:02}:{m:02}:{s:02}")
