import customtkinter as ctk
import os
import pathlib
import threading
from tkinter import filedialog, messagebox
import concurrent.futures
from core.av1_engine import AV1EncoderEngine, EncodingProgress
from core.av1_settings import AV1Settings
from ui.theme import BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, ACCENT, TEXT_PRIMARY, TEXT_MUTED, SEPARATOR, FONT_MAIN, FONT_HEADER

class AV1EncoderTab(ctk.CTkFrame):
    def __init__(self, master, log_callback, file_logger):
        super().__init__(master, fg_color="transparent")
        self.log_callback = log_callback
        self.file_logger = file_logger
        self.settings = AV1Settings()
        self.engine = AV1EncoderEngine()
        
        self.is_encoding = False
        self.stop_event = threading.Event()
        self.active_worker_engines = set()
        self.worker_lock = threading.Lock()

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # === Top: Configuration ===
        self.frame_top = ctk.CTkFrame(self, fg_color=BG_SECONDARY)
        self.frame_top.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Paths
        self.path_container = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.path_container.pack(fill="x", padx=10, pady=10)
        
        # Source
        self.label_src = ctk.CTkLabel(self.path_container, text="SOURCE:", font=FONT_HEADER, text_color=TEXT_MUTED, width=80, anchor="w")
        self.label_src.grid(row=0, column=0, padx=(0,10), pady=2)
        self.entry_src = ctk.CTkEntry(self.path_container, placeholder_text="Source directory...", fg_color=BG_TERTIARY, border_color=SEPARATOR, border_width=1)
        self.entry_src.grid(row=0, column=1, sticky="ew", pady=2)
        self.entry_src.insert(0, self.settings.get("source_folder"))
        self.btn_browse_src = ctk.CTkButton(self.path_container, text="Browse", width=80, fg_color=ACCENT, command=self.browse_source)
        self.btn_browse_src.grid(row=0, column=2, padx=(10,0), pady=2)
        
        # Target
        self.label_dst = ctk.CTkLabel(self.path_container, text="TARGET:", font=FONT_HEADER, text_color=TEXT_MUTED, width=80, anchor="w")
        self.label_dst.grid(row=1, column=0, padx=(0,10), pady=2)
        self.entry_dst = ctk.CTkEntry(self.path_container, placeholder_text="Target directory...", fg_color=BG_TERTIARY, border_color=SEPARATOR, border_width=1)
        self.entry_dst.grid(row=1, column=1, sticky="ew", pady=2)
        self.entry_dst.insert(0, self.settings.get("target_folder"))
        self.btn_browse_dst = ctk.CTkButton(self.path_container, text="Browse", width=80, fg_color=ACCENT, command=self.browse_target)
        self.btn_browse_dst.grid(row=1, column=2, padx=(10,0), pady=2)
        
        self.path_container.grid_columnconfigure(1, weight=1)

        # Settings Controls (Horizontal)
        self.ctrl_container = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.ctrl_container.pack(fill="x", padx=10, pady=(0, 10))
        
        # Quality
        ctk.CTkLabel(self.ctrl_container, text="QUALITY (CQ):", font=FONT_MAIN, text_color=TEXT_MUTED).pack(side="left", padx=(0,5))
        self.slider_quality = ctk.CTkSlider(self.ctrl_container, from_=0, to=63, width=150, command=self.on_quality_change)
        self.slider_quality.set(self.settings.get("quality"))
        self.slider_quality.pack(side="left", padx=(0, 10))
        self.lbl_quality_val = ctk.CTkLabel(self.ctrl_container, text=str(self.settings.get("quality")), font=FONT_MAIN, text_color=ACCENT, width=30)
        self.lbl_quality_val.pack(side="left", padx=(0, 20))
        
        # Preset
        ctk.CTkLabel(self.ctrl_container, text="PRESET:", font=FONT_MAIN, text_color=TEXT_MUTED).pack(side="left", padx=(0,5))
        self.combo_preset = ctk.CTkComboBox(self.ctrl_container, values=["p1", "p2", "p3", "p4", "p5", "p6", "p7"], width=80, command=self.on_preset_change)
        self.combo_preset.set(self.settings.get("preset"))
        self.combo_preset.pack(side="left", padx=(0, 20))
        
        # Threads
        ctk.CTkLabel(self.ctrl_container, text="THREADS:", font=FONT_MAIN, text_color=TEXT_MUTED).pack(side="left", padx=(0,5))
        self.combo_jobs = ctk.CTkComboBox(self.ctrl_container, values=["1", "2", "4"], width=60, command=self.on_jobs_change)
        self.combo_jobs.set(str(self.settings.get("concurrent_jobs")))
        self.combo_jobs.pack(side="left", padx=(0, 10))

        # === Middle: Dashboard / Progress ===
        self.frame_mid = ctk.CTkFrame(self, fg_color=BG_SECONDARY)
        self.frame_mid.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        self.label_queue = ctk.CTkLabel(self.frame_mid, text="ENCODING QUEUE", font=FONT_HEADER, text_color=TEXT_MUTED)
        self.label_queue.pack(anchor="w", padx=10, pady=5)
        
        self.scroll_queue = ctk.CTkScrollableFrame(self.frame_mid, fg_color=BG_TERTIARY)
        self.scroll_queue.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # === Bottom: Actions ===
        self.frame_bot = ctk.CTkFrame(self, fg_color=BG_SECONDARY)
        self.frame_bot.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        self.master_progress = ctk.CTkProgressBar(self.frame_bot, height=12, progress_color=ACCENT)
        self.master_progress.pack(fill="x", padx=10, pady=(10, 5))
        self.master_progress.set(0)
        
        self.btn_panel = ctk.CTkFrame(self.frame_bot, fg_color="transparent")
        self.btn_panel.pack(fill="x", padx=10, pady=(0, 10))
        
        self.btn_start = ctk.CTkButton(self.btn_panel, text="START ENCODING", font=FONT_HEADER, fg_color="#064e3b", hover_color="#065f46", height=40, command=self.start_encoding)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.btn_stop = ctk.CTkButton(self.btn_panel, text="STOP", font=FONT_HEADER, fg_color="#450a0a", hover_color="#7f1d1d", height=40, state="disabled", command=self.stop_encoding)
        self.btn_stop.pack(side="right")

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
        val = int(val)
        self.lbl_quality_val.configure(text=str(val))
        self.settings.set("quality", val)

    def on_preset_change(self, val):
        self.settings.set("preset", val)

    def on_jobs_change(self, val):
        self.settings.set("concurrent_jobs", int(val))

    def start_encoding(self):
        src = self.entry_src.get()
        dst = self.entry_dst.get()
        if not src or not dst:
            messagebox.showerror("Error", "Please select source and target directories.")
            return
        
        self.is_encoding = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.log_callback("Starting AV1 Encoding Job...")
        
        # Threaded scanning and encoding
        threading.Thread(target=self._run_job, args=(src, dst), daemon=True).start()

    def stop_encoding(self):
        self.is_encoding = False
        self.engine.cancel()
        
        # Stop all active worker engines
        with self.worker_lock:
            for eng in self.active_worker_engines:
                eng.cancel()
        
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.log_callback("Encoding stopped by user.")

    def _run_job(self, src, dst):
        self.log_callback("Scanning for video files...")
        files = list(self.engine.scan_files(src))
        if not files:
            self.log_callback("No compatible files found.")
            self.after(0, self.stop_encoding)
            return
        
        self.log_callback(f"Found {len(files)} files to encode.")
        
        total_files = len(files)
        processed = 0
        counter_lock = threading.Lock()
        concurrent_jobs = self.settings.get("concurrent_jobs", 1)
        
        def encode_worker(file_info):
            if not self.is_encoding: return
            file_path, size = file_info
            filename = os.path.basename(file_path)
            
            # Create target path
            if self.settings.get("maintain_structure"):
                rel_path = os.path.relpath(file_path, src)
                target_path = os.path.join(dst, os.path.splitext(rel_path)[0] + "_av1.mkv")
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
            else:
                target_path = os.path.join(dst, os.path.splitext(filename)[0] + "_av1.mkv")
            
            self.after(0, lambda f=filename: self.log_callback(f"Encoding: {f}"))
            
            # Use a fresh engine per thread to avoid state collision
            worker_engine = AV1EncoderEngine()
            
            with self.worker_lock:
                if not self.is_encoding: return
                self.active_worker_engines.add(worker_engine)
            
            try:
                success, _, _ = worker_engine.encode_file(
                    file_path, target_path, 
                    quality=self.settings.get("quality"),
                    preset=self.settings.get("preset"),
                    reencode_audio=self.settings.get("reencode_audio")
                )
            finally:
                with self.worker_lock:
                    self.active_worker_engines.discard(worker_engine)
            
            nonlocal processed
            with counter_lock:
                processed += 1
                prog = processed / total_files
                self.after(0, lambda p=prog: self.master_progress.set(p))
            
            if success:
                self.after(0, lambda f=filename: self.log_callback(f"Finished: {f}"))
            else:
                self.after(0, lambda f=filename: self.log_callback(f"Failed: {f}"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_jobs) as executor:
            executor.map(encode_worker, files)
        
        self.after(0, self.stop_encoding)
        self.after(0, lambda: self.log_callback("Batch encoding process complete."))
