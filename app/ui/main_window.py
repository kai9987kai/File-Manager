import tkinter as tk
from tkinter import ttk, messagebox
import os
from app.config import Config
from app.ui.tabs import FileManagerTab
from app.ui.palette import CommandPalette
from app.core.state import AppState

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(Config.APP_TITLE)
        self.geometry(f"{Config.DEFAULT_WIDTH}x{Config.DEFAULT_HEIGHT}")
        self.minsize(Config.MIN_WIDTH, Config.MIN_HEIGHT)
        
        self.state = AppState()
        Config.apply_theme(self, self.state.current_theme)
        
        self._setup_menu()
        self._setup_layout()
        
        # Initial Tab
        self.new_tab(os.getcwd())
        
        # Bindings
        self.bind("<Control-p>", self.show_palette)
        self.bind("<Control-t>", lambda e: self.new_tab(os.getcwd()))
        self.bind("<Control-w>", lambda e: self.close_current_tab())
        self.bind("<F5>", lambda e: self.refresh_active())

    def _setup_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Tab", accelerator="Ctrl+T", command=lambda: self.new_tab(os.getcwd()))
        file_menu.add_command(label="Close Tab", accelerator="Ctrl+W", command=self.close_current_tab)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Command Palette", accelerator="Ctrl+P", command=self.show_palette)
        
        theme_menu = tk.Menu(view_menu, tearoff=0)
        for theme in Config.THEMES.keys():
            theme_menu.add_command(label=theme, command=lambda t=theme: self.switch_theme(t))
        view_menu.add_cascade(label="Themes", menu=theme_menu)
        
        menubar.add_cascade(label="View", menu=view_menu)

    def _setup_layout(self):
        # Main container with sidebar
        main_container = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Sidebar
        sidebar = ttk.Frame(main_container, width=150)
        main_container.add(sidebar, weight=0) # weight 0 to keep it fixed/small
        
        ttk.Label(sidebar, text="Quick Access", font=("Segoe UI", 10, "bold")).pack(pady=10, padx=5, anchor="w")
        
        # Quick Access Buttons
        paths = [
            ("Desktop", os.path.join(os.path.expanduser("~"), "Desktop")),
            ("Downloads", os.path.join(os.path.expanduser("~"), "Downloads")),
            ("Documents", os.path.join(os.path.expanduser("~"), "Documents")),
            ("Pictures", os.path.join(os.path.expanduser("~"), "Pictures")),
        ]
        
        for name, path in paths:
             if os.path.exists(path):
                btn = ttk.Button(sidebar, text=name, command=lambda p=path: self.new_tab(p))
                btn.pack(fill=tk.X, padx=5, pady=2)

        # Content Area
        self.notebook = ttk.Notebook(main_container)
        main_container.add(self.notebook, weight=4)
        
        # Console / Log pane at bottom
        self.log_text = tk.Text(self, height=5, state="disabled", bg="#f0f0f0")
        self.log_text.pack(side=tk.BOTTOM, fill=tk.X)

    def new_tab(self, directory):
        tab = FileManagerTab(self.notebook, directory, self)
        self.notebook.add(tab, text=os.path.basename(directory) or directory)
        self.notebook.select(tab)

    def close_current_tab(self):
        if self.notebook.select():
            self.notebook.forget(self.notebook.select())

    def refresh_active(self):
        current = self.get_active_tab()
        if current:
            current.refresh()

    def get_active_tab(self):
        selected = self.notebook.select()
        if selected:
            # widget name is returned, need to find instance
            # In tkinter, nametowidget retrieves the widget object
            return self.nametowidget(selected)
        return None

    def switch_theme(self, theme_name):
        self.state.current_theme = theme_name
        Config.apply_theme(self, theme_name)
        self.log(f"Switched theme to {theme_name}")

    def show_palette(self, event=None):
        def get_actions():
            actions = [
                ("New Tab", lambda: self.new_tab(os.getcwd())),
                ("Close Tab", self.close_current_tab),
                ("Switch Theme: Dark", lambda: self.switch_theme("Dark")),
                ("Switch Theme: Light", lambda: self.switch_theme("Light")),
                ("Switch Theme: Midnight", lambda: self.switch_theme("Midnight")),
                ("Quit", self.quit),
            ]
            # Add favorites
            for fav in self.state.favorites:
                 actions.append((f"Open Favorite: {fav}", lambda f=fav: self.new_tab(f)))
            return actions

        CommandPalette(self, get_actions)

    def log(self, message):
        # Schedule UI update on main thread to be thread-safe
        self.after(0, lambda: self._log_ui(message))

    def _log_ui(self, message):
        import logging
        logging.info(message)
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"> {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
