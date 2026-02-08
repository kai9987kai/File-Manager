import tkinter as tk
from tkinter import ttk

class Config:
    APP_TITLE = "Next-Level File Manager"
    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 900
    MIN_WIDTH = 1100
    MIN_HEIGHT = 700
    
    # File Extensions
    TEXT_EXTENSIONS = {".txt", ".py", ".log", ".md", ".csv", ".json", ".xml", ".ini", ".yml", ".yaml", ".bat", ".sh"}
    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp"}
    
    # Themes
    THEMES = {
        "Light": {
            "style": "default",
            "bg": "SystemButtonFace",
            "fg": "black",
            "field_bg": "white",
            "console_bg": "#f0f0f0",
            "console_fg": "black"
        },
        "Dark": {
            "style": "clam",
            "bg": "#2e2e2e",
            "fg": "#e0e0e0",
            "field_bg": "#4d4d4d",
            "console_bg": "#1e1e1e",
            "console_fg": "#00ff00" # Hacker green for console
        },
         "Midnight": {
            "style": "clam",
            "bg": "#0f0f1a", # Deep blue/black
            "fg": "#a0a0ff",
            "field_bg": "#1a1a2e",
            "console_bg": "#050510",
            "console_fg": "#ff00ff" # Neon pink
        }
    }

    @staticmethod
    def apply_theme(root, theme_name):
        theme = Config.THEMES.get(theme_name, Config.THEMES["Light"])
        style = ttk.Style()
        
        if theme["style"] != "default":
            style.theme_use(theme["style"])
        
        # Configure global styles
        style.configure(".", background=theme["bg"], foreground=theme["fg"], fieldbackground=theme["field_bg"])
        style.configure("Treeview", background=theme["field_bg"], foreground=theme["fg"], fieldbackground=theme["field_bg"])
        style.map("Treeview", background=[("selected", "#0078d7")], foreground=[("selected", "white")])
        
        # Specific widget configurations
        root.configure(background=theme["bg"])
        
        return theme
