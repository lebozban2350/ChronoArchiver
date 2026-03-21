import os
import sys
import urllib.request
import json
import threading
import webbrowser
import pathlib
import customtkinter as ctk
from tkinter import messagebox
from version import __version__, APP_NAME

GITHUB_API_URL = "https://api.github.com/repos/UnDadFeated/ChronoArchiver/releases/latest"
AUR_PACKAGE_URL = "https://aur.archlinux.org/packages/chronoarchiver"

class UpdaterEngine:
    def __init__(self, app_window, logger_callback):
        self.app = app_window
        self.logger = logger_callback

    def check_for_updates(self, manual=True):
        def _check():
            try:
                latest_version = None
                update_source = "GitHub"
                
                # 1. Try AUR if on Linux
                if sys.platform != "win32":
                    try:
                        self.logger("UPDATER: Checking AUR for updates...")
                        aur_rpc = f"https://aur.archlinux.org/rpc/v5/info?arg[]={APP_NAME.lower().replace(' ', '')}"
                        req = urllib.request.Request(aur_rpc, headers={"User-Agent": "ChronoArchiver"})
                        with urllib.request.urlopen(req, timeout=10) as response:
                            data = json.loads(response.read().decode())
                            if data.get("resultcount", 0) > 0:
                                raw_version = data["results"][0]["Version"]
                                # Strip pkgrel if present (e.g. 3.0.9-1 -> 3.0.9)
                                latest_version = raw_version.split('-')[0]
                                # Ensure 'v' prefix for consistency with __version__
                                if not latest_version.startswith('v'):
                                    latest_version = 'v' + latest_version
                                update_source = "AUR"
                                self.logger(f"UPDATER: Found version {latest_version} on AUR.")
                    except Exception as e:
                        self.logger(f"UPDATER: AUR check skipped/failed: {e}")

                # 2. Fallback to GitHub if latest_version still unknown
                if not latest_version:
                    self.logger("UPDATER: Connecting to GitHub Releases API...")
                    req = urllib.request.Request(GITHUB_API_URL, headers={"User-Agent": "ChronoArchiver"})
                    with urllib.request.urlopen(req, timeout=10) as response:
                        self.logger("UPDATER: Metadata received. Parsing version info...")
                        data = json.loads(response.read().decode())
                        latest_version = data.get("tag_name", "")
                        update_source = "GitHub"

                if not latest_version:
                    raise ValueError("Could not determine latest version from any source.")
                
                self.logger(f"UPDATER: Latest version found: {latest_version} ({update_source})")
                
                def parse_version(v_str):
                    # Remove 'v' prefix, split by '.', and convert to integers
                    try:
                        return tuple(map(int, v_str.lstrip('v').split('.')))
                    except:
                        return (0, 0, 0)

                v_latest = parse_version(latest_version)
                v_current = parse_version(__version__)

                if v_latest <= v_current:
                    self.logger(f"UPDATER: App is already up to date (Local: {__version__}).")
                    if manual:
                        self.app.after(0, lambda: messagebox.showinfo("No Updates", f"You are on the latest version ({__version__})."))
                    return

                self.logger(f"UPDATER: New Update Available from {update_source}! {latest_version}")
                
                # If from GitHub, we might have a changelog. AUR doesn't really have a 'body' in RPC.
                changelog_body = ""
                if update_source == "GitHub":
                    changelog_body = data.get("body", "").strip()
                
                if not changelog_body:
                    changelog_body = f"A new version ({latest_version}) is available on {update_source}."

                if len(changelog_body) > 800:
                    changelog_body = changelog_body[:797] + "..."

                self.app.after(0, lambda: self._show_update_dialog(latest_version, changelog_body))
                
            except Exception as e:
                self.logger(f"Update Check Error: {e}")
                if manual:
                    self.app.after(0, lambda: messagebox.showerror("Update Error", f"Failed to check for updates:\n{e}"))

        threading.Thread(target=_check, daemon=True).start()

    def _show_update_dialog(self, version, changelog):
        dialog = ctk.CTkToplevel(self.app)
        dialog.title("Update Available")
        dialog.geometry("500x400")
        dialog.transient(self.app)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.app.winfo_x() + (self.app.winfo_width() // 2) - (500 // 2)
        y = self.app.winfo_y() + (self.app.winfo_height() // 2) - (400 // 2)
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text=f"Version {version} is available!", font=("Inter", 16, "bold")).pack(pady=(20, 10))
        
        textbox = ctk.CTkTextbox(dialog, width=460, height=240, fg_color="#1e1e1e", text_color="#e8e8e8", wrap="word")
        textbox.pack(padx=20, pady=(0, 20))
        textbox.insert("0.0", changelog)
        textbox.configure(state="disabled")
        
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        def on_update():
            dialog.destroy()
            if sys.platform == "win32":
                webbrowser.open("https://github.com/UnDadFeated/ChronoArchiver/releases/latest")
            else:
                if pathlib.Path('/usr/bin/yay').exists():
                    webbrowser.open(AUR_PACKAGE_URL)
                else:
                    webbrowser.open("https://github.com/UnDadFeated/ChronoArchiver/releases/latest")
                
        def on_skip():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text="Skip", width=100, fg_color="#3a3a3a", hover_color="#4a4a4a", command=on_skip).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Update Now", width=100, fg_color="#4a7fe0", hover_color="#5a8ff0", command=on_update).pack(side="right", padx=10)
