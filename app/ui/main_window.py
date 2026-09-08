import logging
import os
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from app.config import Config
from app.core.engine import Engine
from app.core.preview import PreviewExecutor
from app.core.state import AppState
from app.ui.tabs import FileManagerTab
from app.ui.palette import CommandPalette


class MainWindow(tk.Tk):
    def __init__(self, directory=None):
        super().__init__()
        self.title(Config.APP_TITLE)
        icon = Path(__file__).resolve().parents[1] / "assets" / "file-manager.ico"
        if os.name == "nt" and icon.is_file():
            self.iconbitmap(default=str(icon))
        self.geometry(f"{Config.DEFAULT_WIDTH}x{Config.DEFAULT_HEIGHT}")
        self.minsize(Config.MIN_WIDTH, Config.MIN_HEIGHT)
        self.state = AppState()
        self._closing = False
        self._logs = queue.Queue()
        self._jobs = []
        self.engine = Engine(self._logs.put)
        self.preview_executor = PreviewExecutor(max_workers=2)
        self.navigation_executor = PreviewExecutor(max_workers=2)
        Config.apply_theme(self, self.state.current_theme)
        self._setup_layout()
        self._setup_menu()
        self.new_tab(directory or os.getcwd())
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        bindings = {
            "<Control-p>": self.show_palette,
            "<Control-t>": self.new_tab,
            "<Control-w>": self.close_current_tab,
            "<Control-l>": lambda: self._active("focus_address"),
            "<Control-f>": lambda: self._active("focus_search"),
            "<Control-h>": lambda: self._active("toggle_hidden"),
            "<Control-Shift-N>": lambda: self._active("create_folder"),
            "<Alt-Left>": lambda: self._active("go_back"),
            "<Alt-Right>": lambda: self._active("go_forward"),
            "<Alt-Up>": lambda: self._active("go_up"),
            "<F5>": self.refresh_active,
        }
        for sequence, action in bindings.items():
            self.bind(sequence, lambda event, command=action: self._shortcut(command))
        self._poll_id = self.after(80, self._poll)

    @staticmethod
    def _shortcut(command):
        command()
        return "break"

    def _active(self, method):
        tab = self.get_active_tab()
        if tab:
            getattr(tab, method)()

    def _setup_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        for label, shortcut, command in [
            ("New Tab", "Ctrl+T", self.new_tab),
            ("Close Tab", "Ctrl+W", self.close_current_tab),
            ("New Folder", "Ctrl+Shift+N", lambda: self._active("create_folder")),
        ]:
            file_menu.add_command(label=label, accelerator=shortcut, command=command)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)
        menubar.add_cascade(label="File", menu=file_menu)
        view = tk.Menu(menubar, tearoff=0)
        view.add_command(label="Refresh", accelerator="F5", command=self.refresh_active)
        view.add_command(label="Command Palette", accelerator="Ctrl+P", command=self.show_palette)
        view.add_command(label="Toggle Hidden Files", accelerator="Ctrl+H", command=lambda: self._active("toggle_hidden"))
        themes = tk.Menu(view, tearoff=0)
        self.theme_var = tk.StringVar(value=self.state.current_theme)
        for name in Config.THEMES:
            themes.add_radiobutton(label=name, variable=self.theme_var, value=name, command=lambda t=name: self.switch_theme(t))
        view.add_cascade(label="Theme", menu=themes)
        menubar.add_cascade(label="View", menu=view)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _setup_layout(self):
        header = ttk.Frame(self, padding=(16, 10))
        header.pack(fill=tk.X)
        ttk.Label(header, text="FILE MANAGER", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        self.activity = ttk.Label(header, text="Ready")
        self.activity.pack(side=tk.RIGHT)
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8)
        sidebar = ttk.Frame(main, width=180, padding=8)
        main.add(sidebar, weight=0)
        ttk.Label(sidebar, text="QUICK ACCESS", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 10))
        home = os.path.expanduser("~")
        paths = [("Home", home)] + [(name, os.path.join(home, name)) for name in ("Desktop", "Downloads", "Documents", "Pictures")]
        for label, path in paths:
            if os.path.isdir(path):
                ttk.Button(sidebar, text=label, command=lambda p=path: self.open_location(p)).pack(fill=tk.X, pady=2)
        ttk.Separator(sidebar).pack(fill=tk.X, pady=14)
        ttk.Label(sidebar, text="FAVORITES", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 8))
        self.favorites_frame = ttk.Frame(sidebar)
        self.favorites_frame.pack(fill=tk.X)
        self.refresh_favorites()
        ttk.Button(sidebar, text="Recent folders", command=self.show_recent).pack(fill=tk.X, pady=14)
        self.notebook = ttk.Notebook(main)
        main.add(self.notebook, weight=1)
        log_frame = ttk.Frame(self, padding=(12, 5))
        log_frame.pack(side=tk.BOTTOM, fill=tk.X, before=main)
        ttk.Label(log_frame, text="ACTIVITY", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=3, state="disabled", relief=tk.FLAT, wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill=tk.X)

    def open_location(self, directory):
        tab = self.get_active_tab()
        if tab:
            tab.navigate_to(directory)
        else:
            self.new_tab(directory)

    def new_tab(self, directory=None):
        if directory is None:
            active = self.get_active_tab()
            directory = active.directory if active else os.path.expanduser("~")
        directory = os.path.abspath(os.path.expanduser(directory))
        tab = FileManagerTab(self.notebook, directory, self)
        self.notebook.add(tab, text=os.path.basename(directory) or directory)
        self.notebook.select(tab)
        Config.apply_theme(self, self.state.current_theme)
        return tab

    def close_current_tab(self):
        tab = self.get_active_tab()
        if tab:
            tab.destroy()

    def get_active_tab(self):
        selected = self.notebook.select()
        return self.nametowidget(selected) if selected else None

    def refresh_active(self):
        self._active("refresh")

    def refresh_tabs(self):
        for child in self.notebook.winfo_children():
            if isinstance(child, FileManagerTab):
                child.refresh()

    def refresh_favorites(self):
        for child in self.favorites_frame.winfo_children():
            child.destroy()
        if not self.state.favorites:
            ttk.Label(self.favorites_frame, text="Use ☆ Favorite to pin\na folder here.", justify=tk.LEFT).pack(anchor="w")
        for path in self.state.favorites:
            row = ttk.Frame(self.favorites_frame)
            row.pack(fill=tk.X, pady=2)
            name = os.path.basename(path) or path
            ttk.Button(row, text=name[:22], command=lambda p=path: self.open_location(p)).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(row, text="×", width=2, command=lambda p=path: self.remove_favorite(p)).pack(side=tk.RIGHT)

    def remove_favorite(self, path):
        self.state.remove_favorite(path)
        self.refresh_favorites()
        for tab in self.notebook.winfo_children():
            if isinstance(tab, FileManagerTab):
                tab.update_navigation()

    def show_recent(self):
        actions = [(path, lambda p=path: self.open_location(p)) for path in reversed(self.state.history)]
        CommandPalette(self, lambda: actions)

    def switch_theme(self, name):
        self.state.current_theme = name
        self.theme_var.set(name)
        self.state.save()
        Config.apply_theme(self, name)
        self.log(f"Theme: {name}")

    def show_palette(self):
        actions = [
            ("New Tab", self.new_tab), ("Close Tab", self.close_current_tab),
            ("Refresh", self.refresh_active), ("Go Back", lambda: self._active("go_back")),
            ("Go Forward", lambda: self._active("go_forward")), ("Go to Parent Folder", lambda: self._active("go_up")),
            ("Focus Address", lambda: self._active("focus_address")), ("Search Files", lambda: self._active("focus_search")),
            ("New Folder", lambda: self._active("create_folder")), ("Toggle Hidden Files", lambda: self._active("toggle_hidden")),
            ("Toggle Favorite", lambda: self._active("toggle_favorite")),
        ]
        actions += [(f"Theme: {name}", lambda n=name: self.switch_theme(n)) for name in Config.THEMES]
        actions += [(f"Favorite: {path}", lambda p=path: self.open_location(p)) for path in self.state.favorites]
        actions += [(f"Recent: {path}", lambda p=path: self.open_location(p)) for path in reversed(self.state.history)]
        CommandPalette(self, lambda: actions)

    def show_shortcuts(self):
        messagebox.showinfo("Keyboard shortcuts",
            "Ctrl+T / Ctrl+W     New / close tab\n"
            "Ctrl+L / Ctrl+F     Address / search\n"
            "Alt+Left / Right   Back / forward\n"
            "Alt+Up                  Parent folder\n"
            "F5 / Ctrl+H           Refresh / hidden files\n"
            "Ctrl+P                   Command palette\n"
            "Ctrl+Shift+N         New folder\n\n"
            "In the file list:\n"
            "Ctrl+A                   Select all\n"
            "Ctrl+C / X / V       Copy / cut / paste\n"
            "F2                           Rename\n"
            "Delete                    Move to Trash / Recycle Bin\n"
            "Enter                      Open selection", parent=self)

    def submit_operation(self, label, function, on_complete=None):
        future = self.engine.submit_task(function)
        self._jobs.append((label, future, on_complete))
        self.activity.configure(text=f"{len(self._jobs)} operation(s) running")
        return future

    def _poll(self):
        if self._closing:
            return
        for _ in range(100):
            try:
                self._log_ui(self._logs.get_nowait())
            except queue.Empty:
                break
        pending = []
        for label, future, callback in self._jobs:
            if not future.done():
                pending.append((label, future, callback))
                continue
            try:
                result = future.result()
            except Exception as error:
                self.log(f"{label} failed: {error}")
                messagebox.showerror(label, str(error), parent=self)
                result = None
            if callback:
                try:
                    callback(result)
                except Exception:
                    logging.exception("Operation completion callback failed")
        self._jobs = pending
        self.activity.configure(text=f"{len(pending)} operation(s) running" if pending else "Ready")
        self._poll_id = self.after(80, self._poll)

    def log(self, message):
        # Workers only touch the queue; all Tk calls stay on the event thread.
        self._logs.put(str(message))

    def _log_ui(self, message):
        logging.info(message)
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"› {message}\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 500:
            self.log_text.delete("1.0", "100.0")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def close_app(self):
        if self._jobs:
            messagebox.showinfo("File operations running", "Wait for file operations to finish before closing the app.", parent=self)
            return
        self.destroy()

    def destroy(self):
        if self._closing:
            return
        self._closing = True
        if hasattr(self, "_poll_id"):
            self.after_cancel(self._poll_id)
        for tab in self.notebook.winfo_children():
            tab.destroy()
        self.state.save()
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        self.navigation_executor.shutdown(wait=False, cancel_futures=True)
        self.engine.shutdown(wait=False)
        self.engine.log_callback = None
        self.theme_var = None
        super().destroy()
