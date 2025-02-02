#!/usr/bin/env python
"""
Next-Level Ultra-Ultra-Advanced File Manager

Features:
  - Multi-Tab Interface: Browse multiple directories concurrently.
  - Menu Bar (File, Edit, View, Help) with operations: Refresh, Quit, Theme Switching, Add Favorite.
  - Favorites Panel for quick access to frequently used directories.
  - Breadcrumb Navigation for current directory.
  - Advanced Filtering with regex and recursive search toggles.
  - Sortable file list via ttk.Treeview (Name, Size, Modified).
  - Dual-Pane Mode for file copy/move between source and destination.
  - Context Menu with operations: Open, Rename, Delete, Copy, Move, Tag, Properties.
  - Dual Preview: Image thumbnail preview, text preview for text files, and video preview placeholder.
  - File Details Pane showing metadata and session-only file tags.
  - Status Bar displaying current directory, file count, and messages.
  - Operation Log Console showing a history of file operations.
  - Asynchronous Directory Scanning using threads (to keep UI responsive).
  - Keyboard Shortcuts: Enter (open), F2 (rename), Delete (delete).
  
Requires Pillow (pip install Pillow)
"""

import os, sys, fnmatch, re, time, shutil, threading, queue
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
from tkinter.constants import BOTH, END, LEFT, RIGHT, TOP, BOTTOM, X, Y
from PIL import Image, ImageTk

# Global dialog state
dialogstates = {}
TEXT_EXTENSIONS = {".txt", ".py", ".log", ".md", ".csv", ".json", ".xml"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

# Utility: Convert size in bytes to human-readable format.
def human_readable_size(size, dec_places=1):
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024:
            return f"{size:.{dec_places}f} {unit}"
        size /= 1024
    return f"{size:.{dec_places}f} PB"

# Logger mixin to log messages to a Text widget.
class LoggerMixin:
    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        self.log_console.config(state="normal")
        self.log_console.insert(END, f"[{timestamp}] {message}\n")
        self.log_console.see(END)
        self.log_console.config(state="disabled")

# Asynchronous directory scanning thread.
class DirScanner(threading.Thread):
    def __init__(self, directory, pattern, use_regex, recursive, result_queue, log_callback):
        super().__init__()
        self.directory = directory
        self.pattern = pattern
        self.use_regex = use_regex
        self.recursive = recursive
        self.result_queue = result_queue
        self.log_callback = log_callback
        self.daemon = True

    def run(self):
        results = []
        try:
            if self.recursive:
                for root, dirs, files in os.walk(self.directory):
                    for name in files:
                        if self.use_regex:
                            try:
                                if re.search(self.pattern, name):
                                    results.append(os.path.join(root, name))
                            except re.error:
                                continue
                        else:
                            if fnmatch.fnmatch(name, self.pattern):
                                results.append(os.path.join(root, name))
            else:
                for name in os.listdir(self.directory):
                    fullpath = os.path.join(self.directory, name)
                    if os.path.isfile(fullpath):
                        if self.use_regex:
                            try:
                                if re.search(self.pattern, name):
                                    results.append(fullpath)
                            except re.error:
                                continue
                        else:
                            if fnmatch.fnmatch(name, self.pattern):
                                results.append(fullpath)
            self.log_callback(f"Scanned {len(results)} file(s) in {self.directory}")
        except Exception as e:
            self.log_callback(f"Error scanning directory: {e}")
        self.result_queue.put(results)

# Main File Manager class with multi-tab and logging support.
class NextLevelFileManager(LoggerMixin):
    def __init__(self, master, title="Next-Level File Manager"):
        self.master = master
        self.title = title
        self.theme = tk.StringVar(value="Light")
        self.file_tags = {}  # session file tags
        self.favorites = []  # list of favorite directories

        # Create main window
        self.top = Toplevel(master)
        self.top.title(self.title)
        self.top.iconname(self.title)
        self.top.geometry("1400x900")
        self.top.minsize(1100, 700)

        # Build Menu Bar
        self.menu_bar = tk.Menu(self.top)
        self.top.config(menu=self.menu_bar)
        self.build_menu()

        # Create Notebook for multi-tab interface
        self.notebook = ttk.Notebook(self.top)
        self.notebook.pack(expand=True, fill=BOTH)

        # Favorites Panel on the left
        self.favorites_frame = ttk.Frame(self.top)
        self.favorites_frame.pack(side=LEFT, fill=Y, padx=5, pady=5)
        ttk.Label(self.favorites_frame, text="Favorites").pack(anchor="w")
        self.favorites_list = tk.Listbox(self.favorites_frame, height=10)
        self.favorites_list.pack(fill=Y, expand=True)
        self.favorites_list.bind('<Double-ButtonRelease-1>', self.favorites_open)

        # Log Console at the bottom
        self.log_console = tk.Text(self.top, height=8, state="disabled", bg="#f0f0f0")
        self.log_console.pack(side=BOTTOM, fill=X, padx=5, pady=5)

        # Create initial tab
        self.create_tab(os.getcwd())

        # Apply theme
        self.apply_theme()

    def build_menu(self):
        # File Menu
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="New Tab", command=lambda: self.create_tab(os.getcwd()))
        file_menu.add_command(label="Add Favorite", command=self.add_favorite)
        file_menu.add_command(label="Close Tab", command=self.close_current_tab)
        file_menu.add_separator()
        file_menu.add_command(label="Refresh", command=self.refresh_current_tab)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.top.quit)
        self.menu_bar.add_cascade(label="File", menu=file_menu)
        # Edit Menu
        edit_menu = tk.Menu(self.menu_bar, tearoff=0)
        edit_menu.add_command(label="Rename", command=lambda: self.current_tab().rename_command())
        edit_menu.add_command(label="Delete", command=lambda: self.current_tab().delete_command())
        edit_menu.add_command(label="Copy", command=lambda: self.current_tab().copy_command())
        edit_menu.add_command(label="Move", command=lambda: self.current_tab().move_command())
        edit_menu.add_command(label="Tag", command=lambda: self.current_tab().tag_command())
        self.menu_bar.add_cascade(label="Edit", menu=edit_menu)
        # View Menu
        view_menu = tk.Menu(self.menu_bar, tearoff=0)
        view_menu.add_command(label="Toggle Dual Pane", command=lambda: self.current_tab().toggle_dual_pane())
        view_menu.add_command(label="Switch Theme", command=self.switch_theme)
        view_menu.add_command(label="Toggle Recursive Search", command=lambda: self.current_tab().toggle_recursive())
        self.menu_bar.add_cascade(label="View", menu=view_menu)
        # Help Menu
        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", self.title))
        self.menu_bar.add_cascade(label="Help", menu=help_menu)

    def create_tab(self, directory):
        tab = FileManagerTab(self.notebook, directory, self)
        self.notebook.add(tab.frame, text=directory)
        self.notebook.select(tab.frame)
        self.log(f"Created new tab for: {directory}")

    def current_tab(self):
        cur = self.notebook.select()
        for tab in self.notebook.winfo_children():
            if str(tab) == cur:
                return tab.file_manager_tab
        return None

    def close_current_tab(self):
        cur = self.notebook.select()
        if cur:
            self.notebook.forget(cur)
            self.log("Closed current tab.")

    def refresh_current_tab(self):
        tab = self.current_tab()
        if tab:
            tab.refresh()

    def add_favorite(self):
        tab = self.current_tab()
        if tab:
            fav = tab.directory
            if fav not in self.favorites:
                self.favorites.append(fav)
                self.favorites_list.insert(END, fav)
                self.log(f"Added favorite: {fav}")

    def favorites_open(self, event):
        selection = self.favorites_list.curselection()
        if selection:
            fav = self.favorites_list.get(selection[0])
            self.create_tab(fav)

    def switch_theme(self):
        if self.theme.get() == "Light":
            self.theme.set("Dark")
        else:
            self.theme.set("Light")
        self.apply_theme()
        self.log(f"Switched to {self.theme.get()} theme.")

    def apply_theme(self):
        style = ttk.Style()
        if self.theme.get() == "Dark":
            style.theme_use('clam')
            style.configure(".", background="#2e2e2e", foreground="white", fieldbackground="#4d4d4d")
            self.top.configure(background="#2e2e2e")
            self.log_console.configure(bg="#3e3e3e", fg="white")
        else:
            style.theme_use('default')
            style.configure(".", background="SystemButtonFace", foreground="black", fieldbackground="white")
            self.top.configure(background="SystemButtonFace")
            self.log_console.configure(bg="#f0f0f0", fg="black")

# The per-tab file manager. Each tab has its own interface.
class FileManagerTab(LoggerMixin):
    def __init__(self, parent_notebook, directory, main_manager):
        self.main_manager = main_manager
        self.directory = directory
        self.dest_directory = directory  # for dual-pane mode (initially same as source)
        self.sort_by = "Name"
        self.sort_reverse = False
        self.use_regex = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)
        self.dual_pane = tk.BooleanVar(value=False)
        self.file_tags = main_manager.file_tags  # shared session tags

        # Build main frame for this tab
        self.frame = ttk.Frame(parent_notebook)
        self.frame.file_manager_tab = self  # attach self to frame for easy access

        # Top area: Breadcrumbs and Filter Frame
        top_frame = ttk.Frame(self.frame)
        top_frame.pack(side=TOP, fill=X, padx=5, pady=5)
        self.breadcrumb_frame = ttk.Frame(top_frame)
        self.breadcrumb_frame.pack(side=TOP, fill=X)
        ttk.Label(self.breadcrumb_frame, text="Path: ").pack(side=LEFT)
        self.update_breadcrumbs()
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(side=TOP, fill=X, pady=5)
        self.filter_entry = ttk.Entry(filter_frame)
        self.filter_entry.pack(side=LEFT, fill=X, expand=True)
        self.filter_entry.insert(0, os.path.join(self.directory, "*"))
        self.filter_entry.bind('<Return>', self.filter_command)
        self.filter_button = ttk.Button(filter_frame, text="Filter", command=self.filter_command)
        self.filter_button.pack(side=LEFT, padx=5)
        self.regex_check = ttk.Checkbutton(filter_frame, text="Regex", variable=self.use_regex)
        self.regex_check.pack(side=LEFT, padx=5)
        self.recursive_check = ttk.Checkbutton(filter_frame, text="Recursive", variable=self.recursive)
        self.recursive_check.pack(side=LEFT, padx=5)
        self.dual_pane_check = ttk.Checkbutton(filter_frame, text="Dual Pane", variable=self.dual_pane, command=self.toggle_dual_pane)
        self.dual_pane_check.pack(side=LEFT, padx=5)

        # Main PanedWindow for source (and optionally destination) and preview/details
        self.main_pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        self.main_pane.pack(expand=True, fill=BOTH, padx=5, pady=5)

        # Left side: Source Panel
        self.source_panel = ttk.Frame(self.main_pane)
        self.main_pane.add(self.source_panel, weight=3)
        self.build_source_panel(self.source_panel)

        # Right side: Preview and Details Panel (vertical)
        self.right_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(self.right_pane, weight=2)
        self.build_preview_details_panel(self.right_pane)

        # Destination Panel (for dual-pane mode; initially hidden)
        self.dest_panel = None

        # Bottom area: Selection Entry, Action Buttons, and Status Bar
        bottom_frame = ttk.Frame(self.frame)
        bottom_frame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
        self.selection_entry = ttk.Entry(bottom_frame)
        self.selection_entry.pack(side=LEFT, fill=X, expand=True, padx=5)
        self.selection_entry.bind('<Return>', self.ok_event)
        self.open_button = ttk.Button(bottom_frame, text="OPEN", command=self.ok_command)
        self.open_button.pack(side=LEFT, padx=5)
        self.rename_button = ttk.Button(bottom_frame, text="RENAME", command=self.rename_command)
        self.rename_button.pack(side=LEFT, padx=5)
        self.delete_button = ttk.Button(bottom_frame, text="DELETE", command=self.delete_command)
        self.delete_button.pack(side=LEFT, padx=5)
        self.copy_button = ttk.Button(bottom_frame, text="COPY", command=self.copy_command)
        self.copy_button.pack(side=LEFT, padx=5)
        self.move_button = ttk.Button(bottom_frame, text="MOVE", command=self.move_command)
        self.move_button.pack(side=LEFT, padx=5)
        self.tag_button = ttk.Button(bottom_frame, text="TAG", command=self.tag_command)
        self.tag_button.pack(side=LEFT, padx=5)
        self.status_label = ttk.Label(bottom_frame, text="Status: Ready", anchor="w")
        self.status_label.pack(side=RIGHT, padx=5)

        # Bind keyboard shortcuts
        self.frame.bind_all('<F2>', lambda e: self.rename_command())
        self.frame.bind_all('<Delete>', lambda e: self.delete_command())
        self.frame.bind_all('<Return>', lambda e: self.ok_command())

        # Context Menu for file operations
        self.context_menu = tk.Menu(self.frame, tearoff=0)
        self.context_menu.add_command(label="Open", command=lambda: self.open_selected_file())
        self.context_menu.add_command(label="Rename", command=lambda: self.rename_command())
        self.context_menu.add_command(label="Delete", command=lambda: self.delete_command())
        self.context_menu.add_command(label="Copy", command=lambda: self.copy_command())
        self.context_menu.add_command(label="Move", command=lambda: self.move_command())
        self.context_menu.add_command(label="Tag", command=lambda: self.tag_command())
        self.context_menu.add_command(label="Properties", command=lambda: self.show_properties())

        # Asynchronous scan queue
        self.scan_queue = queue.Queue()
        self.filter_command()  # initial scan

    def build_source_panel(self, parent):
        ttk.Label(parent, text="Source Files").pack(anchor="w")
        columns = ("Name", "Size", "Modified")
        self.file_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        for col in columns:
            self.file_tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            self.file_tree.column(col, anchor="w")
        self.file_tree.pack(expand=True, fill=BOTH)
        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=RIGHT, fill=Y)
        self.file_tree.bind('<ButtonRelease-1>', self.file_select_event)
        self.file_tree.bind('<Double-ButtonRelease-1>', self.file_double_event)
        self.file_tree.bind("<Button-3>", self.file_right_click_event)

    def build_preview_details_panel(self, parent):
        # Preview Panel
        preview_frame = ttk.Frame(parent)
        parent.add(preview_frame, weight=1)
        ttk.Label(preview_frame, text="Preview").pack(anchor="w")
        self.preview_canvas = tk.Canvas(preview_frame, bg="gray", width=300, height=300)
        self.preview_canvas.pack(padx=5, pady=5)
        # Details Panel
        details_frame = ttk.Frame(parent)
        parent.add(details_frame, weight=1)
        ttk.Label(details_frame, text="File Details").pack(anchor="w", padx=5)
        self.details_text = tk.Text(details_frame, height=8, wrap="word")
        self.details_text.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.details_text.config(state="disabled")

    def update_breadcrumbs(self):
        # Clear existing breadcrumbs
        for widget in self.breadcrumb_frame.winfo_children():
            widget.destroy()
        parts = os.path.normpath(self.directory).split(os.sep)
        if os.name == "nt" and parts[0].endswith(":"):
            parts[0] = parts[0] + os.sep
        path_so_far = ""
        for part in parts:
            if part == "":
                continue
            path_so_far = os.path.join(path_so_far, part)
            link = ttk.Label(self.breadcrumb_frame, text=part, foreground="blue", cursor="hand2")
            link.pack(side=LEFT)
            link.bind("<Button-1>", lambda e, p=path_so_far: self.breadcrumb_click(p))
            ttk.Label(self.breadcrumb_frame, text=" > ").pack(side=LEFT)

    def breadcrumb_click(self, path):
        if os.path.isdir(path):
            self.directory = path
            self.filter_entry.delete(0, END)
            self.filter_entry.insert(0, os.path.join(self.directory, "*"))
            self.filter_command()

    def toggle_recursive(self):
        self.recursive.set(not self.recursive.get())
        self.filter_command()

    def toggle_dual_pane(self):
        if self.dual_pane.get():
            if not self.dest_panel:
                self.dest_panel = self.build_destination_panel(ttk.Frame(self.frame))
                self.main_pane.add(self.dest_panel, weight=3)
                self.dest_directory = os.getcwd()
                self.refresh_dest_panel()
        else:
            if self.dest_panel:
                self.main_pane.forget(self.dest_panel)
                self.dest_panel = None

    def build_destination_panel(self, parent):
        ttk.Label(parent, text="Destination Files").pack(anchor="w")
        self.dest_tree = ttk.Treeview(parent, columns=("Name", "Size", "Modified"), show="headings", selectmode="browse")
        for col in ("Name", "Size", "Modified"):
            self.dest_tree.heading(col, text=col, command=lambda c=col: self.sort_dest_by_column(c))
            self.dest_tree.column(col, anchor="w")
        self.dest_tree.pack(expand=True, fill=BOTH)
        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.dest_tree.yview)
        self.dest_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=RIGHT, fill=Y)
        self.dest_tree.bind('<ButtonRelease-1>', self.dest_select_event)
        self.dest_tree.bind('<Double-ButtonRelease-1>', self.dest_double_event)
        return parent

    def refresh_dest_panel(self):
        if not self.dest_panel:
            return
        self.dest_tree.delete(*self.dest_tree.get_children())
        try:
            names = os.listdir(self.dest_directory)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open destination {self.dest_directory}:\n{e}")
            return
        dirs = [d for d in names if os.path.isdir(os.path.join(self.dest_directory, d))]
        dirs.sort()
        for d in dirs:
            fullpath = os.path.join(self.dest_directory, d)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fullpath)))
            self.dest_tree.insert("", END, values=(d, "", mtime))
        self.status_label.config(text=f"Destination: {self.dest_directory}")

    def file_select_event(self, event):
        selected = self.file_tree.selection()
        if selected:
            item = self.file_tree.item(selected[0])
            filename = item["values"][0]
            fullpath = os.path.join(self.directory, filename)
            self.selection_entry.delete(0, END)
            self.selection_entry.insert(END, fullpath)
            self.show_preview(fullpath)
            self.show_details(fullpath)
        else:
            self.preview_canvas.delete("all")
            self.details_text.config(state="normal")
            self.details_text.delete("1.0", END)
            self.details_text.config(state="disabled")

    def file_double_event(self, event):
        selected = self.file_tree.selection()
        if selected:
            item = self.file_tree.item(selected[0])
            filename = item["values"][0]
            fullpath = os.path.join(self.directory, filename)
            if os.path.isfile(fullpath):
                self.open_file(fullpath)

    def file_right_click_event(self, event):
        iid = self.file_tree.identify_row(event.y)
        if iid:
            self.file_tree.selection_set(iid)
            self.context_menu.post(event.x_root, event.y_root)

    def dest_select_event(self, event):
        selected = self.dest_tree.selection()
        if selected:
            item = self.dest_tree.item(selected[0])
            dirname = item["values"][0]
            new_dest = os.path.join(self.dest_directory, dirname)
            if os.path.isdir(new_dest):
                self.dest_directory = new_dest
                self.refresh_dest_panel()

    def dest_double_event(self, event):
        self.dest_select_event(event)

    def filter_command(self, event=None):
        # Use asynchronous scanning to avoid UI freeze
        filt = self.filter_entry.get().strip()
        filt = os.path.expanduser(filt)
        if filt == "":
            filt = os.path.join(os.curdir, "*")
        if filt[-1:] == os.sep or os.path.isdir(filt):
            filt = os.path.join(filt, "*")
        _, pattern = os.path.split(filt)
        self.status_label.config(text="Scanning...")
        scanner = DirScanner(self.directory, pattern, self.use_regex.get(), self.recursive.get(), self.scan_queue, lambda msg: self.main_manager.log(msg))
        scanner.start()
        self.frame.after(100, self.check_scan_queue)

    def check_scan_queue(self):
        try:
            results = self.scan_queue.get_nowait()
            self.populate_file_tree(results)
        except queue.Empty:
            self.frame.after(100, self.check_scan_queue)

    def populate_file_tree(self, file_list):
        self.file_tree.delete(*self.file_tree.get_children())
        files = []
        for fullpath in file_list:
            name = os.path.basename(fullpath)
            try:
                size = os.path.getsize(fullpath)
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fullpath)))
            except Exception:
                size = 0
                mtime = ""
            files.append((name, size, mtime))
        files.sort(key=lambda t: t[0].lower())
        for name, size, mtime in files:
            self.file_tree.insert("", END, values=(name, human_readable_size(size), mtime))
        self.status_label.config(text=f"{len(files)} file(s) in {self.directory}")

    def show_preview(self, filepath):
        self.preview_canvas.delete("all")
        ext = os.path.splitext(filepath)[1].lower()
        if os.path.isfile(filepath):
            if ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
                try:
                    image = Image.open(filepath)
                    image.thumbnail((300, 300))
                    self.current_preview = ImageTk.PhotoImage(image)
                    cw = self.preview_canvas.winfo_width()
                    ch = self.preview_canvas.winfo_height()
                    self.preview_canvas.create_image(cw//2, ch//2, image=self.current_preview)
                except Exception as e:
                    self.preview_canvas.create_text(150, 150, text="Image Preview Error", fill="white")
            elif ext in TEXT_EXTENSIONS:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read(500)
                    self.preview_canvas.create_text(150, 150, text=content, fill="white", width=280)
                except Exception as e:
                    self.preview_canvas.create_text(150, 150, text="Text Preview Error", fill="white")
            elif ext in VIDEO_EXTENSIONS:
                self.preview_canvas.create_text(150, 150, text="Video Preview Not Implemented", fill="white")
            else:
                self.preview_canvas.create_text(150, 150, text="No Preview Available", fill="white")
        else:
            self.preview_canvas.create_text(150, 150, text="No File", fill="white")

    def show_details(self, filepath):
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", END)
        if os.path.isfile(filepath):
            try:
                size = os.path.getsize(filepath)
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(filepath)))
            except Exception:
                size, mtime = 0, ""
            ftype = os.path.splitext(filepath)[1].lower() or "Unknown"
            tag = self.file_tags.get(filepath, "None")
            details = (f"Path: {filepath}\n"
                       f"Size: {human_readable_size(size)}\n"
                       f"Modified: {mtime}\n"
                       f"Type: {ftype}\n"
                       f"Tag: {tag}")
            self.details_text.insert(END, details)
        else:
            self.details_text.insert(END, "No file details available.")
        self.details_text.config(state="disabled")

    def ok_event(self, event):
        self.ok_command()

    def ok_command(self):
        selected = self.file_tree.selection()
        if selected:
            for iid in selected:
                item = self.file_tree.item(iid)
                filename = item["values"][0]
                fullpath = os.path.join(self.directory, filename)
                if os.path.isfile(fullpath):
                    self.open_file(fullpath)
            self.main_manager.log(f"Opened file(s) from {self.directory}")
        else:
            messagebox.showinfo("No Selection", "Please select a file to open.")

    def delete_command(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showwarning("No File", "No file selected for deletion.")
            return
        if messagebox.askyesno("Delete Confirmation", "Are you sure you want to delete the selected file(s)?"):
            for iid in selected:
                item = self.file_tree.item(iid)
                filename = item["values"][0]
                fullpath = os.path.join(self.directory, filename)
                try:
                    if os.path.exists(fullpath) and os.path.isfile(fullpath):
                        os.remove(fullpath)
                        self.main_manager.log(f"Deleted: {fullpath}")
                except Exception as e:
                    messagebox.showerror("Deletion Error", f"Error deleting {fullpath}:\n{e}")
            self.filter_command()

    def rename_command(self):
        selected = self.file_tree.selection()
        if not selected or len(selected) != 1:
            messagebox.showwarning("Select One File", "Please select exactly one file to rename.")
            return
        item = self.file_tree.item(selected[0])
        filename = item["values"][0]
        fullpath = os.path.join(self.directory, filename)
        new_name = simpledialog.askstring("Rename File", f"Enter new name for {filename}:")
        if new_name and new_name != filename:
            new_fullpath = os.path.join(self.directory, new_name)
            try:
                os.rename(fullpath, new_fullpath)
                self.main_manager.log(f"Renamed: {fullpath} -> {new_fullpath}")
                self.filter_command()
            except Exception as e:
                messagebox.showerror("Rename Error", f"Error renaming file:\n{e}")

    def open_file(self, path):
        try:
            if sys.platform.startswith('darwin'):
                os.system(f"open '{path}'")
            elif os.name == 'nt':
                os.startfile(path)
            elif os.name == 'posix':
                os.system(f"xdg-open '{path}'")
        except Exception as e:
            messagebox.showerror("Open File Error", f"Could not open file:\n{e}")

    def copy_command(self):
        if self.dual_pane.get():
            selected = self.file_tree.selection()
            if not selected:
                messagebox.showwarning("No File", "No file selected to copy.")
                return
            for iid in selected:
                item = self.file_tree.item(iid)
                filename = item["values"][0]
                src = os.path.join(self.directory, filename)
                dst = os.path.join(self.dest_directory, filename)
                try:
                    shutil.copy2(src, dst)
                    self.main_manager.log(f"Copied: {src} -> {dst}")
                except Exception as e:
                    messagebox.showerror("Copy Error", f"Error copying {filename}:\n{e}")
            self.refresh_dest_panel()
        else:
            messagebox.showinfo("Dual Pane Mode", "Enable Dual Pane Mode to copy files between directories.")

    def move_command(self):
        if self.dual_pane.get():
            selected = self.file_tree.selection()
            if not selected:
                messagebox.showwarning("No File", "No file selected to move.")
                return
            for iid in selected:
                item = self.file_tree.item(iid)
                filename = item["values"][0]
                src = os.path.join(self.directory, filename)
                dst = os.path.join(self.dest_directory, filename)
                try:
                    shutil.move(src, dst)
                    self.main_manager.log(f"Moved: {src} -> {dst}")
                except Exception as e:
                    messagebox.showerror("Move Error", f"Error moving {filename}:\n{e}")
            self.filter_command()
            self.refresh_dest_panel()
        else:
            messagebox.showinfo("Dual Pane Mode", "Enable Dual Pane Mode to move files between directories.")

    def tag_command(self):
        selected = self.file_tree.selection()
        if not selected or len(selected) != 1:
            messagebox.showwarning("Select One File", "Please select exactly one file to tag.")
            return
        item = self.file_tree.item(selected[0])
        filename = item["values"][0]
        fullpath = os.path.join(self.directory, filename)
        tag = simpledialog.askstring("Tag File", f"Enter a tag for {filename}:")
        if tag is not None:
            self.file_tags[fullpath] = tag
            self.main_manager.log(f"Tagged {fullpath} with '{tag}'")
            self.show_details(fullpath)

    def show_properties(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo("No Selection", "No file selected.")
            return
        item = self.file_tree.item(selected[0])
        filename = item["values"][0]
        fullpath = os.path.join(self.directory, filename)
        if os.path.isfile(fullpath):
            try:
                size = os.path.getsize(fullpath)
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fullpath)))
            except Exception:
                size, mtime = 0, ""
            tag = self.file_tags.get(fullpath, "None")
            info = f"File: {fullpath}\nSize: {human_readable_size(size)}\nModified: {mtime}\nTag: {tag}"
            messagebox.showinfo("File Properties", info)

    def sort_by_column(self, col):
        if self.sort_by == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_by = col
            self.sort_reverse = False
        items = []
        for iid in self.file_tree.get_children():
            item = self.file_tree.item(iid)["values"]
            items.append((iid, item))
        if col == "Name":
            key_func = lambda t: t[1][0].lower()
        elif col == "Size":
            key_func = lambda t: os.path.getsize(os.path.join(self.directory, t[1][0]))
        elif col == "Modified":
            key_func = lambda t: os.path.getmtime(os.path.join(self.directory, t[1][0]))
        else:
            key_func = lambda t: t[1][0].lower()
        items.sort(key=key_func, reverse=self.sort_reverse)
        for index, (iid, _) in enumerate(items):
            self.file_tree.move(iid, '', index)

    def sort_dest_by_column(self, col):
        items = []
        for iid in self.dest_tree.get_children():
            item = self.dest_tree.item(iid)["values"]
            items.append((iid, item))
        key_func = lambda t: t[1][0].lower()
        items.sort(key=key_func)
        for index, (iid, _) in enumerate(items):
            self.dest_tree.move(iid, '', index)

    def refresh(self):
        self.filter_command()

# Test Runner
def test():
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    manager = NextLevelFileManager(root)
    root.mainloop()

if __name__ == '__main__':
    test()
