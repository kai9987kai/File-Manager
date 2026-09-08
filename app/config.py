import tkinter as tk
from tkinter import ttk
from app.version import __version__


class Config:
    APP_TITLE = f"File Manager {__version__}"
    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 900
    MIN_WIDTH = 1000
    MIN_HEIGHT = 640
    TEXT_EXTENSIONS = {".txt", ".py", ".log", ".md", ".csv", ".json", ".xml", ".ini", ".yml", ".yaml", ".bat", ".sh", ".js", ".ts", ".css", ".html", ".toml", ".sql", ".ps1", ".gitignore"}
    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp"}
    THEMES = {
        "Light": {"bg": "#f3f5f9", "fg": "#243247", "field_bg": "#ffffff", "console_bg": "#e9edf4", "console_fg": "#34445c"},
        "Dark": {"bg": "#252a34", "fg": "#edf1f7", "field_bg": "#1c212b", "console_bg": "#191e27", "console_fg": "#b7c9e2"},
        "Midnight": {"bg": "#141d32", "fg": "#dce7ff", "field_bg": "#0e1629", "console_bg": "#0a1120", "console_fg": "#b2c8f5"},
    }

    @staticmethod
    def apply_theme(root, theme_name):
        theme = Config.THEMES.get(theme_name, Config.THEMES["Light"])
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=theme["bg"], foreground=theme["fg"], fieldbackground=theme["field_bg"], font=("Segoe UI", 10))
        style.configure("TButton", padding=(8, 5))
        style.configure("TEntry", padding=5)
        style.configure("Treeview", background=theme["field_bg"], foreground=theme["fg"], fieldbackground=theme["field_bg"], rowheight=29, borderwidth=0)
        style.configure("Treeview.Heading", padding=(8, 8), font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#326bd6")], foreground=[("selected", "white")])
        style.map("TButton", background=[("disabled", theme["bg"]), ("active", "#326bd6")], foreground=[("disabled", "#8792a3"), ("active", "white")])
        style.configure("TNotebook.Tab", padding=(10, 6))
        style.map("TNotebook.Tab", background=[("selected", theme["field_bg"]), ("!selected", theme["bg"])], foreground=[("selected", theme["fg"]), ("!selected", theme["fg"])])
        root.configure(background=theme["bg"])

        def recolor(widget):
            if isinstance(widget, (tk.Text, tk.Listbox)):
                widget.configure(bg=theme["field_bg"], fg=theme["fg"], selectbackground="#326bd6", selectforeground="white")
                if isinstance(widget, tk.Text):
                    widget.configure(insertbackground=theme["fg"])
            elif isinstance(widget, tk.Canvas):
                widget.configure(bg=theme["field_bg"])
            for child in widget.winfo_children():
                recolor(child)

        recolor(root)
        return theme
