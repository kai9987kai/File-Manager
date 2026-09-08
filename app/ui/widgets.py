import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk


class Breadcrumb(ttk.Frame):
    def __init__(self, master, path, on_click_callback, **kwargs):
        super().__init__(master, **kwargs)
        self.on_click = on_click_callback
        self.update_path(path)

    def update_path(self, path):
        self.path = os.path.abspath(path)
        for widget in self.winfo_children():
            widget.destroy()
        location = Path(self.path)
        ancestors = [*reversed(location.parents), location]
        if len(ancestors) > 5:
            ancestors = [ancestors[0], *ancestors[-4:]]
        for index, ancestor in enumerate(ancestors):
            if index:
                ttk.Label(self, text=" / ").pack(side=tk.LEFT)
            label = ancestor.name or str(ancestor)
            ttk.Button(self, text=label, command=lambda p=str(ancestor): self.on_click(p)).pack(side=tk.LEFT)


class StatusBar(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.msg_label = ttk.Label(self, text="Ready", anchor=tk.W)
        self.msg_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=6)
        self.info_label = ttk.Label(self, text="", anchor=tk.E)
        self.info_label.pack(side=tk.RIGHT, padx=8)

    def set_message(self, msg):
        self.msg_label.config(text=msg)

    def set_info(self, info):
        self.info_label.config(text=info)
