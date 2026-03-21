import customtkinter as ctk
import sys
import pathlib
from core.logger import setup_logger
from core.updater import UpdaterEngine
from version import __version__, APP_NAME
import tkinter as tk

from ui.theme import BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, ACCENT, TEXT_PRIMARY, TEXT_MUTED, SEPARATOR, FONT_MAIN, FONT_HEADER

# Ensure src is in path logic if running raw
sys.path.append(str(pathlib.Path(__file__).parent.parent))

# Import tabs after sys.path update
from ui.tabs import OrganizerTab, AIScannerTab, DonateTab
from ui.tabs.av1_tab import AV1EncoderTab

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.configure(fg_color=BG_PRIMARY)
        self.logger = setup_logger()
        self.logger.info("Initializing Main App Window")
        
        self.updater = UpdaterEngine(self, self.log)

        self.title(f"{APP_NAME} ({__version__})")
        self.geometry("1100x750") # Slightly larger for the new tab
        self.resizable(False, False)

        # Set Icon
        assets_dir = pathlib.Path(__file__).parent.parent / 'assets'
        if sys.platform == 'win32':
            icon_path = assets_dir / 'icon.ico'
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        else:
            icon_path = assets_dir / 'icon.png'
            if icon_path.exists():
                img = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, img)
        
        # Add 12px padding on outer wrapper
        self.main_wrapper = ctk.CTkFrame(self, fg_color="transparent")
        self.main_wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        # PanedWindow
        self.paned_window = tk.PanedWindow(self.main_wrapper, orient="vertical", sashwidth=6, bg=BG_PRIMARY, borderwidth=0)
        self.paned_window.pack(fill="both", expand=True, padx=0, pady=0)

        # === Top Pane: Custom Navigation & Tab View ===
        self.top_frame = ctk.CTkFrame(self.paned_window, fg_color="transparent")
        
        # Navbar (Custom Tab Bar)
        self.navbar = ctk.CTkFrame(self.top_frame, fg_color="transparent", height=40)
        self.navbar.pack(fill="x", padx=0, pady=(0, 5))
        
        self.nav_left = ctk.CTkFrame(self.navbar, fg_color="transparent")
        self.nav_left.pack(side="left", fill="y")
        
        self.nav_right = ctk.CTkFrame(self.navbar, fg_color="transparent")
        self.nav_right.pack(side="right", fill="y")
        
        # Functional Tab Buttons (Left)
        self.nav_buttons = {}
        tab_names = [("Media Organizer", "org"), ("Mass AI Encoder", "av1"), ("AI Scan", "ai")]
        for text, name in tab_names:
            btn = ctk.CTkButton(self.nav_left, text=text, width=140, height=32, corner_radius=6,
                                fg_color="transparent", text_color=TEXT_PRIMARY, hover_color=BG_TERTIARY,
                                command=lambda n=name: self.show_tab(n))
            btn.pack(side="left", padx=(0, 5))
            self.nav_buttons[name] = btn
            
        # Donate Button (Right)
        self.btn_donate = ctk.CTkButton(self.nav_right, text="Donate", width=100, height=32, corner_radius=6,
                                        fg_color="transparent", text_color=ACCENT, hover_color=BG_TERTIARY,
                                        command=lambda: self.show_tab("donate"))
        self.btn_donate.pack(side="right")
        self.nav_buttons["donate"] = self.btn_donate

        # Content Container
        self.content_frame = ctk.CTkFrame(self.top_frame, fg_color=BG_SECONDARY, corner_radius=6)
        self.content_frame.pack(fill="both", expand=True)

        # Init Tab Frames (Initially hidden)
        self.tab_frames = {}
        
        self.tab_frames["org"] = OrganizerTab(self.content_frame, self.log, self.logger, self.set_status, self.set_background)
        self.tab_frames["av1"] = AV1EncoderTab(self.content_frame, self.log, self.logger, self.set_status, self.set_background)
        self.tab_frames["ai"] = AIScannerTab(self.content_frame, self.log, self.logger, self.set_status, self.set_background)
        self.tab_frames["donate"] = DonateTab(self.content_frame)
        
        # Show default tab
        self.show_tab("org")
        
        self.paned_window.add(self.top_frame, minsize=400)
        
        # === Bottom Pane: Log Area ===
        self.bottom_frame = ctk.CTkFrame(self.paned_window, fg_color="transparent")
        
        self.grip_frame = ctk.CTkFrame(self.bottom_frame, fg_color="transparent", height=10)
        self.grip_frame.pack(fill="x", padx=0, pady=0)
        
        self.sep = ctk.CTkFrame(self.grip_frame, height=1, fg_color=SEPARATOR)
        self.sep.pack(fill="x", padx=0, pady=(4, 4))

        self.console_header = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        self.console_header.pack(fill="x", padx=0, pady=(0, 2))
        
        ctk.CTkLabel(self.console_header, text="LOG CONSOLE", font=FONT_HEADER, text_color=TEXT_MUTED, anchor="w").pack(side="left")
        
        self.log_text = ctk.CTkTextbox(self.bottom_frame, height=150, font=("Consolas", 11), fg_color="#141414", text_color="#a8d8a8", corner_radius=4)
        self.log_text.pack(fill="both", expand=True, padx=0, pady=(0, 0))
        
        self.paned_window.add(self.bottom_frame, minsize=100)
        
        # === Global Footer ===
        self.footer_frame = ctk.CTkFrame(self.main_wrapper, fg_color=BG_SECONDARY, height=28, corner_radius=6)
        self.footer_frame.pack(fill="x", padx=0, pady=(10, 0))
        
        self.lbl_status = ctk.CTkLabel(self.footer_frame, text="READY", font=(FONT_MAIN[0], 10, "bold"), text_color=ACCENT)
        self.lbl_status.pack(side="left", padx=15)
        
        self.lbl_background = ctk.CTkLabel(self.footer_frame, text="Idle", font=(FONT_MAIN[0], 10), text_color=TEXT_MUTED)
        self.lbl_background.pack(side="left", expand=True)
        
        self.btn_footer_update = ctk.CTkLabel(self.footer_frame, text="CHECK FOR UPDATES", font=(FONT_MAIN[0], 9, "bold"), text_color=ACCENT, cursor="hand2")
        self.btn_footer_update.pack(side="right", padx=15)
        self.btn_footer_update.bind("<Button-1>", lambda e: self.updater.check_for_updates(manual=True))
        
        self.log(f"Welcome to {APP_NAME} {__version__} (Python Edition)")
        self.log("Ready.")

    def log(self, message):
        def _insert():
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        self.after(0, _insert)

    def show_tab(self, name):
        for f in self.tab_frames.values():
            f.pack_forget()
        for b in self.nav_buttons.values():
            b.configure(fg_color="transparent", text_color=TEXT_PRIMARY)
            
        if name in self.tab_frames:
            self.tab_frames[name].pack(fill="both", expand=True)
            color = ACCENT if name != "donate" else "#9333ea"
            self.nav_buttons[name].configure(fg_color=color, text_color="white")

    def set_status(self, text, color=ACCENT):
        def _update():
            self.lbl_status.configure(text=text.upper(), text_color=color)
        self.after(0, _update)

    def set_background(self, text):
        def _update():
            self.lbl_background.configure(text=text)
        self.after(0, _update)

if __name__ == "__main__":
    app = App()
    app.mainloop()
