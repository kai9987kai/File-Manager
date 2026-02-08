import tkinter as tk
from tkinter import ttk
import os
from app.config import Config

class Breadcrumb(ttk.Frame):
    def __init__(self, master, path, on_click_callback, **kwargs):
        super().__init__(master, **kwargs)
        self.path = path
        self.on_click = on_click_callback
        self.render()

    def update_path(self, path):
        self.path = path
        self.render()

    def render(self):
        for widget in self.winfo_children():
            widget.destroy()

        parts = os.path.normpath(self.path).split(os.sep)
        # Handle Windows drive letter
        if os.name == "nt" and parts[0].endswith(":"):
             parts[0] = parts[0] + os.sep

        current_path = ""
        for i, part in enumerate(parts):
            if part == "": continue
            
            if current_path == "" and os.name == 'nt' and part.endswith(os.sep):
                 current_path = part
            else:
                 current_path = os.path.join(current_path, part)
            
            # Button-like label
            lbl = ttk.Label(self, text=part, cursor="hand2", style="Breadcrumb.TLabel")
            lbl.bind("<Button-1>", lambda e, p=current_path: self.on_click(p))
            lbl.pack(side=tk.LEFT, padx=0)

            if i < len(parts) - 1:
                ttk.Label(self, text=" > ").pack(side=tk.LEFT)

class StatusBar(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.msg_label = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.msg_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.info_label = ttk.Label(self, text="", relief=tk.SUNKEN, anchor=tk.E)
        self.info_label.pack(side=tk.RIGHT, padx=5)

    def set_message(self, msg):
        self.msg_label.config(text=f" {msg}")

    def set_info(self, info):
        self.info_label.config(text=f"{info} ")
