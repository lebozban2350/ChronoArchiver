import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import pathlib
from ui.app import BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, ACCENT, TEXT_PRIMARY, TEXT_MUTED, SEPARATOR, FONT_MAIN, FONT_HEADER
import shutil
from PIL import Image
from core.organizer import OrganizerEngine
from core.scanner import ScannerEngine

import webbrowser

class OrganizerTab(ctk.CTkFrame):
    def __init__(self, master, log_callback, file_logger):
        super().__init__(master)
        # Make logger thread-safe
        self.log_callback = log_callback
        self.file_logger = file_logger
        
        def safe_log(msg):
            if hasattr(self, 'chk_log_output') and not self.chk_log_output.get():
                return
            self.after(0, lambda: self.log_callback(msg))
            
        self.engine = OrganizerEngine(safe_log)
        
        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # === Left Column: Config ===
        self.frame_config = ctk.CTkFrame(self)
        self.frame_config.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        # Source
        ctk.CTkLabel(self.frame_config, text="SELECT FOLDER TO ORGANIZE...", font=FONT_HEADER, text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(10,0))
        
        self.path_frame = ctk.CTkFrame(self.frame_config, fg_color="transparent")
        self.path_frame.pack(fill="x", padx=10, pady=5)
        
        self.entry_path = ctk.CTkEntry(self.path_frame, placeholder_text="Select folder...", fg_color=BG_TERTIARY, border_color=SEPARATOR, border_width=1, corner_radius=4, font=FONT_MAIN)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.btn_browse = ctk.CTkButton(self.path_frame, text="...", width=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=self.browse_source)
        self.btn_browse.pack(side="right")

        # Options
        ctk.CTkLabel(self.frame_config, text="ORGANIZE", font=FONT_HEADER, text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(20,0))
        self.chk_photos = ctk.CTkCheckBox(self.frame_config, text="Photos", onvalue=True, offvalue=False)
        self.chk_photos.select()
        self.chk_photos.pack(anchor="w", padx=20, pady=5)
        
        self.chk_videos = ctk.CTkCheckBox(self.frame_config, text="Videos", onvalue=True, offvalue=False)
        self.chk_videos.select()
        self.chk_videos.pack(anchor="w", padx=20, pady=5)

        # === Right Column: Action ===
        self.frame_action = ctk.CTkFrame(self)
        self.frame_action.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(self.frame_action, text="EXECUTION MODE", font=FONT_HEADER, text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(10,0))
        
        # Options Frame (Horizontal)
        self.opts_frame = ctk.CTkFrame(self.frame_action, fg_color="transparent")
        self.opts_frame.pack(anchor="w", padx=20, pady=10)

        self.chk_dry_run = ctk.CTkSwitch(self.opts_frame, text="Dry Run (Simulation)")
        self.chk_dry_run.select()
        self.chk_dry_run.pack(side="left", padx=(0, 20))

        self.chk_flat_folders = ctk.CTkSwitch(self.opts_frame, text="Flat Folders (YYYY-MM)")
        self.chk_flat_folders.pack(side="left", padx=(0, 20))

        self.chk_log_output = ctk.CTkCheckBox(self.opts_frame, text="Log Output", onvalue=True, offvalue=False)
        self.chk_log_output.select()
        self.chk_log_output.pack(side="left")
        
        ctk.CTkLabel(self.frame_action, text="Recommmended for first run.", text_color=TEXT_MUTED, font=FONT_MAIN).pack(anchor="w", padx=55, pady=0)

        self.button_frame = ctk.CTkFrame(self.frame_action, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=20, pady=(30, 0))

        self.btn_start = ctk.CTkButton(self.button_frame, text="Start Organization", height=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=self.start_organize)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_stop = ctk.CTkButton(self.button_frame, text="Stop", height=40, width=60, font=FONT_MAIN, corner_radius=6, fg_color="#c0392b", hover_color="#962d22", state="disabled", command=self.stop_organize)
        self.btn_stop.pack(side="right", padx=(5, 0))

        # Progress
        self.progress_bar = ctk.CTkProgressBar(self.frame_action)
        self.progress_bar.pack(fill="x", padx=20, pady=10)
        self.progress_bar.set(0)
        self.lbl_progress = ctk.CTkLabel(self.frame_action, text="Ready", text_color=TEXT_MUTED)
        self.lbl_progress.pack(pady=5)

    def browse_source(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, path)

    def stop_organize(self):
        self.engine.cancel()
        self.btn_stop.configure(state="disabled")
        self.lbl_progress.configure(text="Stopping...")

    def start_organize(self):
        path = self.entry_path.get()
        if not path or not pathlib.Path(path).is_dir():
            messagebox.showerror("Error", "Invalid Source Directory")
            return
            
        dry_run = bool(self.chk_dry_run.get())
        use_flat_folders = bool(self.chk_flat_folders.get())
        
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar.set(0)
        self.lbl_progress.configure(text="Scanning files...")
        
        def on_progress(current, total, filename=""):
            # Thread-safe update
            self.after(0, lambda: self.update_progress(current, total, filename))

        def run():
            try:
                self.engine.organize(path, dry_run=dry_run, use_flat_folders=use_flat_folders, progress_callback=on_progress)
            finally:
                self.after(0, self.on_finished)
            
        threading.Thread(target=run, daemon=True).start()

    def on_finished(self):
        self.btn_start.configure(state="normal", text="Start Organization")
        self.btn_stop.configure(state="disabled")
        self.lbl_progress.configure(text="Finished.")

    def update_progress(self, current, total, filename=""):
        if total > 0:
            self.progress_bar.set(current / total)
            self.lbl_progress.configure(text=f"Organizing... {current}/{total} ({filename})")


class AIScannerTab(ctk.CTkFrame):
    def __init__(self, master, log_callback, file_logger):
        super().__init__(master)
        self.log_callback = log_callback
        self.file_logger = file_logger
        
        def safe_log(msg):
            if hasattr(self, 'chk_log_output') and not self.chk_log_output.get():
                return
            self.after(0, lambda: self.log_callback(msg))
            
        self.scanner = ScannerEngine(safe_log)
        
        # Internal State
        self.keep_files = []
        self.exclude_files = []
        self.selected_item = None # (list_name, index, file_path)
        
        # Grid Plan:
        # Row 0: Header/Config
        # Row 1: Lists (Left: Keep, Right: Exclude) + Preview
        # Row 2: Actions
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # === Top Config ===
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        
        self.entry_path = ctk.CTkEntry(self.top_frame, placeholder_text="Folder to Scan...", fg_color=BG_TERTIARY, border_color=SEPARATOR, border_width=1, corner_radius=4, font=FONT_MAIN)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0,10))
        
        self.btn_browse = ctk.CTkButton(self.top_frame, text="...", width=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=self.browse_source)
        self.btn_browse.pack(side="left", padx=(0, 10))
        
        # Hardware Selection - Removed (Default GPU)
        
        # Keep Animals Checkbox
        self.chk_keep_animals = ctk.CTkCheckBox(self.top_frame, text="Keep Animals", width=20, onvalue=True, offvalue=False)
        self.chk_keep_animals.pack(side="left", padx=15)
        
        # Log Output Checkbox
        self.chk_log_output = ctk.CTkCheckBox(self.top_frame, text="Log Output", width=20, onvalue=True, offvalue=False)
        self.chk_log_output.select()
        self.chk_log_output.pack(side="left", padx=15)
        
        self.btn_scan = ctk.CTkButton(self.top_frame, text="START SCAN", font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=self.start_scan)
        self.btn_scan.pack(side="right", padx=10)
        
        # === Main Lists ===
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.content_frame.grid_columnconfigure(0, weight=1) # Keep
        self.content_frame.grid_columnconfigure(2, weight=1) # Exclude
        self.content_frame.grid_rowconfigure(1, weight=1)

        # Left List (Keep)
        # Left List (Keep - Visual Name, actually contains Excluded/People files)
        ctk.CTkLabel(self.content_frame, text="KEEP (People/Animals)", text_color=TEXT_PRIMARY, font=FONT_HEADER).grid(row=0, column=0, sticky="w")
        
        self.list_keep = ctk.CTkScrollableFrame(self.content_frame, label_text="Files (0)")
        self.list_keep.grid(row=1, column=0, sticky="nsew", padx=(0,5))
        
        # Center Controls
        self.center_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.center_frame.grid(row=1, column=1, padx=5)
        self.btn_mv_right = ctk.CTkButton(self.center_frame, text=">", width=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=lambda: self.move_item("right"))
        self.btn_mv_right.pack(pady=5)
        self.btn_mv_left = ctk.CTkButton(self.center_frame, text="<", width=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=lambda: self.move_item("left"))
        self.btn_mv_left.pack(pady=5)

        # Right List (Excluded)
        # Right List (Excluded - Visual Name, actually contains Keep/NoPeople files)
        ctk.CTkLabel(self.content_frame, text="MOVE (Other)", text_color=TEXT_PRIMARY, font=FONT_HEADER).grid(row=0, column=2, sticky="w")
        self.list_exclude = ctk.CTkScrollableFrame(self.content_frame, label_text="Files (0)")
        self.list_exclude.grid(row=1, column=2, sticky="nsew", padx=(5,0))

        # Preview (Far Right)
        self.preview_frame = ctk.CTkFrame(self.content_frame, width=200)
        self.preview_frame.grid(row=1, column=3, sticky="nsew", padx=(10,0))
        # CRITICAL: Use pack_propagate(False) because children use .pack()
        # This prevents the frame from expanding to fit the image.
        self.preview_frame.pack_propagate(False)
        self.content_frame.grid_columnconfigure(3, weight=1) # Expandable
        
        ctk.CTkLabel(self.preview_frame, text="PREVIEW").pack(pady=5)
        self.lbl_preview = ctk.CTkLabel(self.preview_frame, text="[No Image]", width=180, height=180, fg_color="#222")
        self.lbl_preview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Bind to FRAME not label to avoid jitter loops
        self.preview_frame.bind("<Configure>", self.on_preview_resize)
        self.current_preview_path = None
        self._resize_timer = None
        self._preview_thread_id = 0

        # === Footer Actions ===
        self.footer = ctk.CTkFrame(self)
        self.footer.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        
        self.progress = ctk.CTkProgressBar(self.footer)
        self.progress.pack(side="left", fill="x", expand=True, padx=10, pady=5)
        self.progress.set(0)
        
        # Move Files Button (Far Right)
        self.btn_move_files = ctk.CTkButton(self.footer, text="Move Files (Right Col)", font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", state="disabled", command=self.move_files_action)
        self.btn_move_files.pack(side="right", padx=10, pady=5)

        # Cancel Button (Next to Move Files)
        self.btn_cancel = ctk.CTkButton(self.footer, text="Stop", width=60, font=FONT_MAIN, corner_radius=6, fg_color="#c0392b", hover_color="#962d22", state="disabled", command=self.cancel_scan)
        self.btn_cancel.pack(side="right", padx=5)
        
        self.lbl_status = ctk.CTkLabel(self.footer, text="Ready", text_color=TEXT_MUTED)
        
        # Repack footer
        for widget in self.footer.winfo_children(): widget.pack_forget()

        self.btn_move_files.pack(side="right", padx=10, pady=5)
        self.btn_cancel.pack(side="right", padx=5)
        self.lbl_status.pack(side="left", padx=10)
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

    def on_preview_resize(self, event):
        # Debounce: Cancel previous timer if it exists
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
            
        # Schedule new update in 200ms
        self._resize_timer = self.after(200, lambda: self._delayed_resize(event.width, event.height))

    def _delayed_resize(self, w, h):
        # Adjust for padding (frame width != image width)
        img_w = w - 20 # 10px padding each side
        img_h = h - 30 # approx padding + label text space
        
        if img_w < 50 or img_h < 50: return # Too small
        
        if self.current_preview_path:
            self.show_preview_image(self.current_preview_path, img_w, img_h)

    def browse_source(self):
        path = filedialog.askdirectory()
        if path:
            self.entry_path.delete(0, "end")
            self.entry_path.insert(0, path)

    def cancel_scan(self):
        self.scanner.cancel()
        self.btn_cancel.configure(state="disabled")
        self.lbl_status.configure(text="Stopping...")

    def start_scan(self):
        try:
            # Debug connection
            self.file_logger.info("SCAN: Start Button Clicked")
            
            path = self.entry_path.get()
            self.file_logger.info(f"SCAN: Selected Path: '{path}'")
            
            if not path:
                self.file_logger.error("SCAN: Path is empty")
                messagebox.showerror("Error", "Folder path is empty.\nPlease select a folder.")
                return
                
            if not pathlib.Path(path).exists():
                self.file_logger.error(f"SCAN: Path does not exist: {path}")
                messagebox.showerror("Error", f"Path does not exist:\n{path}")
                return
                
            if not pathlib.Path(path).is_dir():
                self.file_logger.error(f"SCAN: Path is not a directory: {path}")
                messagebox.showerror("Error", f"Path is not a directory:\n{path}")
                return

            use_gpu = True # Always GPU
            keep_animals = bool(self.chk_keep_animals.get())
            self.file_logger.info(f"SCAN: Config - Keep Animals: {keep_animals}")

            self.file_logger.debug("SCAN: Updating UI State - Buttons")
            self.btn_scan.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
            self.btn_move_files.configure(state="disabled")
            
            self.file_logger.debug("SCAN: Clearing internal lists")
            self.keep_files.clear()
            self.exclude_files.clear()
            
            self.file_logger.debug("SCAN: Refreshing Lists UI")
            self.refresh_lists()
            
            self.file_logger.debug("SCAN: Updating Status Label")
            self.lbl_status.configure(text=f"Initializing Scan (GPU/OpenCV)...")
            
            self.file_logger.debug("SCAN: Setting Callbacks")
            self.scanner.progress_callback = self.on_progress
            
            def run():
                try:
                    self.file_logger.info("SCAN: Thread Started EXECUTION")
                    self.scanner.run_scan(path, keep_animals=keep_animals)
                    self.file_logger.info("SCAN: Thread Finished Normally")
                    # Finish call must happen on main thread to be safe with Tk
                    self.after(0, self.on_finished)
                except Exception as e:
                    self.file_logger.exception("SCAN: Thread Crashed")
                    self.after(0, lambda: messagebox.showerror("Error during scan", str(e)))
                    self.after(0, self.on_finished)

            self.file_logger.info("SCAN: Dispatching Thread...")
            threading.Thread(target=run, daemon=True).start()
            self.file_logger.info("SCAN: Thread Dispatched Successfully")

        except Exception as e:
            self.file_logger.exception("SCAN: Main Thread Error in start_scan")
            messagebox.showerror("System Error", f"Failed to start scan:\n{e}")
    
    def on_finished(self):
        # Correctly map Engine -> UI
        # keep_list = Subjects (Keep), others_list = Others (Move)
        self.keep_files = list(self.scanner.keep_list)
        self.exclude_files = list(self.scanner.others_list)
        self.refresh_lists()
        self.btn_scan.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        if self.keep_files:
            self.btn_move_files.configure(state="normal")
        self.lbl_status.configure(text="Scan Complete.")
        self.progress.set(1.0)

    def on_progress(self, current, total, eta, filename=""):
        # We invoke 'after' to update UI safely
        self.after(0, lambda: self.update_progress_ui(current, total, eta, filename))

    def update_progress_ui(self, current, total, eta, filename=""):
        val = current / max(total, 1)
        self.progress.set(val)
        self.lbl_status.configure(text=f"Scanning... {current}/{total} ({int(eta)}s) - {filename}")

    def refresh_lists(self):
        for widget in self.list_keep.winfo_children(): widget.destroy()
        for widget in self.list_exclude.winfo_children(): widget.destroy()

        def add_item(parent, files, list_name):
            for i, f in enumerate(files):
                if i > 500: # Limit UI listing for performance
                    ctk.CTkLabel(parent, text=f"...and {len(files)-500} more").pack()
                    break
                    
                name = pathlib.Path(f).name
                btn = ctk.CTkButton(parent, text=name, fg_color="transparent", border_width=0, anchor="w",
                                  command=lambda f=f, idx=i, ln=list_name: self.select_file(f, idx, ln))
                btn._file_path = f
                btn.pack(fill="x", pady=1)

        # Left List (self.list_keep UI) gets Keep data (Subjects/People)
        # Right List (self.list_exclude UI) gets Exclude data (Others/Move)
        add_item(self.list_keep, self.keep_files, "keep_data") 
        add_item(self.list_exclude, self.exclude_files, "exclude_data")
        
        self.list_keep.configure(label_text=f"Files ({len(self.keep_files)})")
        self.list_exclude.configure(label_text=f"Files ({len(self.exclude_files)})")

    def select_file(self, f, idx, list_name):
        self.selected_item = (list_name, idx, f)
        self.current_preview_path = f
        # Show preview
        try:
            # Use FRAME size for consistency, minus padding
            w = self.preview_frame.winfo_width() - 20
            h = self.preview_frame.winfo_height() - 30
            
            # Fallback if uninitialized
            if w < 50: w = 200
            if h < 50: h = 200
            
            self.show_preview_image(f, w, h)
        except: pass

    def show_preview_image(self, f, w, h):
        # Update current path immediately so we know what's "active"
        self.current_preview_path = f
        self._preview_thread_id += 1
        current_id = self._preview_thread_id
        
        def _load_worker(path, width, height, thread_id):
            try:
                # 1. Load and process in BACKGROUND THREAD
                with Image.open(path) as img:
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")
                    
                    img_copy = img.copy()
                    img_copy.thumbnail((width, height), Image.Resampling.LANCZOS)
                    
                    # Get actual dimensions after resize to PREVENT STRETCHING
                    real_w, real_h = img_copy.size
                    
                    # 2. Schedule UI update on MAIN THREAD
                    # Pass the processed PIL image AND logic dimensions
                    self.after(0, lambda: self._update_preview_ui(path, img_copy, real_w, real_h, thread_id))
            except Exception as e:
                self.file_logger.error(f"PREVIEW LOAD ERROR: {e}")
                self.after(0, lambda: self._update_preview_error(thread_id))

        # Start thread
        threading.Thread(target=_load_worker, args=(f, w, h, current_id), daemon=True).start()

    def _update_preview_error(self, thread_id):
        if thread_id == self._preview_thread_id:
            self.lbl_preview.configure(image=None, text="[Error]")

    def _update_preview_ui(self, path, pil_img, w, h, thread_id):
        # Check race condition: Is this still the file user wants to see?
        if thread_id != self._preview_thread_id or path != self.current_preview_path:
            return # User clicked something else in the meantime, discard this result
            
        try:
            # Create CTkImage on Main Thread (safe)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(w, h))
            self.lbl_preview.configure(image=ctk_img, text="")
        except Exception as e:
            self.file_logger.error(f"PREVIEW UI UPDATE ERROR: {e}")
            self.lbl_preview.configure(image=None, text="[Error]")

    def move_item(self, direction):
        if not self.selected_item: return
        lname, idx, f = self.selected_item
        
        changed = False
        target_name = None
        new_idx = 0
        
        if direction == "right":
            # Moving from Left UI (keep_data) to Right UI (exclude_data)
            # Logic: Remove from keep_files, Add to exclude_files
            if lname == "keep_data":
                 if f in self.keep_files:
                     self.keep_files.remove(f)
                     self.exclude_files.append(f)
                     changed = True
                     target_name = "exclude_data"
                     new_idx = len(self.exclude_files) - 1
                     
        elif direction == "left":
            # Moving from Right UI (exclude_data) to Left UI (keep_data)
            # Logic: Remove from exclude_files, Add to keep_files
            if lname == "exclude_data":
                if f in self.exclude_files:
                    self.exclude_files.remove(f)
                    self.keep_files.append(f)
                    changed = True
                    target_name = "keep_data"
                    new_idx = len(self.keep_files) - 1
        
        if changed:
            source_list = self.list_keep if direction == "right" else self.list_exclude
            target_list = self.list_exclude if direction == "right" else self.list_keep

            # Remove widget from source UI without full redraw
            for widget in source_list.winfo_children():
                if getattr(widget, '_file_path', None) == f:
                    widget.destroy()
                    break

            # Add widget to target UI
            name = pathlib.Path(f).name
            btn = ctk.CTkButton(target_list, text=name, fg_color="transparent", border_width=0, anchor="w",
                              command=lambda f=f, i=new_idx, ln=target_name: self.select_file(f, i, ln))
            btn._file_path = f
            btn.pack(fill="x", pady=1)

            # Update labels
            self.list_keep.configure(label_text=f"Files ({len(self.exclude_files)})")
            self.list_exclude.configure(label_text=f"Files ({len(self.keep_files)})")

        self.selected_item = None

    def move_files_action(self):
        dest_dir = pathlib.Path(self.entry_path.get()) / "Archived_Others"
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            
        # CLEAR PREVIEW to release any potential locks (just in case)
        self.lbl_preview.configure(image=None, text="")
        self.current_preview_path = None
        
        count = 0
        error_count = 0
        
        # Snapshot list to avoid modification during iteration
        files_to_move = list(self.exclude_files)
        
        for f in files_to_move:
            try:
                fname = pathlib.Path(f).name
                target = dest_dir / fname
                
                # Move
                shutil.move(f, target)
                count += 1
                
                # Real-time Log (No Popup)
                self.file_logger.info(f"Moved: {fname} -> {dest_dir}")
                
            except Exception as e:
                self.file_logger.error(f"MOVE ERROR: Failed to move {f} -> {e}")
                error_count += 1
            
        # Final Summary Log
        if count > 0:
            self.log_callback(f"SUCCESS: Successfully moved {count} files to 'Archived_Others' folder.")
            self.file_logger.info(f"SUCCESS: Successfully moved {count} files to 'Archived_Others' folder.")
        else:
            self.log_callback("MOVE FINISHED: No files were moved.")
            self.file_logger.info("MOVE FINISHED: No files were moved.")

        if error_count > 0:
            msg = f"Failed to move {error_count} files (Check logs)."
            messagebox.showwarning("Move Completed with Errors", msg)

        # Clear memory lists and refresh UI to remove "ghost" items
        self.exclude_files.clear() # exclude_files held the items we just moved (Others)
        self.refresh_lists()
        self.btn_move_files.configure(state="disabled")

class DonateTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        
        # Center Content
        self.frame = ctk.CTkFrame(self, fg_color="transparent")
        self.frame.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(self.frame, text="☕", font=FONT_HEADER).pack(pady=10)
        ctk.CTkLabel(self.frame, text="Enjoying the App?", font=FONT_HEADER).pack(pady=5)
        
        ctk.CTkLabel(self.frame, text="ChronoArchiver is completely free.\nIf this tool saved you time, consider buying me a coffee!", 
                     font=FONT_MAIN, text_color=TEXT_MUTED).pack(pady=20)
        
        # Buttons
        self.btn_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.btn_frame.pack(pady=20)
        
        # Custom Links for jscheema@gmail.com
        
        # PayPal: Generic Send
        link_paypal = "https://paypal.me/jscheema"
        
        # Venmo: Deep link or web
        link_venmo = "https://venmo.com/u/jscheema"
        

        
        ctk.CTkButton(self.btn_frame, text="PayPal", width=120, height=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=lambda: webbrowser.open(link_paypal)).grid(row=0, column=0, padx=10)
                      
        ctk.CTkButton(self.btn_frame, text="Venmo", width=120, height=40, font=FONT_MAIN, corner_radius=6, fg_color=ACCENT, hover_color="#5a8ff0", command=lambda: webbrowser.open(link_venmo)).grid(row=0, column=1, padx=10)
                      
        ctk.CTkLabel(self.frame, text="Thank you for your support!", font=FONT_MAIN, text_color="#E04F5F").pack(pady=20)

