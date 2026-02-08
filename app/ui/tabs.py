import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import os
import queue
import time
import shutil
import threading # for some simple non-engine tasks if needed

from app.core.scanner import Scanner
from app.core.engine import Engine
from app.core.state import AppState
from app.ui.widgets import Breadcrumb, StatusBar
from app.ui.visualizer import DiskVisualizer
from app.utils.formatters import human_readable_size
from app.utils.icons import Icons
from app.config import Config

from PIL import Image, ImageTk

class FileManagerTab(ttk.Frame):
    def __init__(self, parent_notebook, directory, main_window):
        super().__init__(parent_notebook)
        self.main_window = main_window
        self.directory = os.path.normpath(directory)
        self.sort_by = "Name"
        self.sort_reverse = False
        
        # State variables
        self.use_regex = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)
        self.show_hidden = tk.BooleanVar(value=False)
        
        # Core components
        self.engine = Engine(self.log)
        self.scan_queue = queue.Queue()
        self.scanner = None
        
        # UI Layout
        self._setup_ui()
        
        # Initial Load
        self.refresh()

    def _setup_ui(self):
        # Top Bar: Breadcrumbs & Filter
        top_frame = ttk.Frame(self)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        self.breadcrumb = Breadcrumb(top_frame, self.directory, self.navigate_to)
        self.breadcrumb.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(side=tk.TOP, fill=tk.X)
        
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.filter_entry.bind('<Return>', lambda e: self.refresh())
        
        ttk.Button(filter_frame, text="Go", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(filter_frame, text="Regex", variable=self.use_regex).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(filter_frame, text="Recursive", variable=self.recursive).pack(side=tk.LEFT, padx=5)

        # Main Split: Treeview / Preview
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        
        # Left: File List
        self.tree_frame = ttk.Frame(self.paned)
        self.paned.add(self.tree_frame, weight=3)
        
        # Columns
        columns = ("Name", "Size", "Modified", "Type")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="extended")
        
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c))
            self.tree.column(col, anchor="w", width=100)
        self.tree.column("Name", width=300)
            
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)
        
        # Bindings
        self.tree.bind('<Double-Button-1>', self.on_double_click)
        self.tree.bind('<ButtonRelease-1>', self.on_select)
        
        # Right: Visualizer / Preview
        self.right_panel = ttk.Frame(self.paned)
        self.paned.add(self.right_panel, weight=1)
        
        self.notebook_preview = ttk.Notebook(self.right_panel)
        self.notebook_preview.pack(fill=tk.BOTH, expand=True)
        
        # Preview Tab
        self.preview_frame = ttk.Frame(self.notebook_preview)
        self.notebook_preview.add(self.preview_frame, text="Preview")
        self.preview_canvas = tk.Canvas(self.preview_frame, bg="white")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Visualizer Tab
        self.visualizer = DiskVisualizer(self.notebook_preview, self.directory)
        self.notebook_preview.add(self.visualizer, text="Visualizer")

        # Bottom: Status
        self.status = StatusBar(self)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def navigate_to(self, path):
        if os.path.exists(path) and os.path.isdir(path):
            self.directory = path
            self.breadcrumb.update_path(path)
            self.visualizer.update_path(path)
            self.refresh()
            AppState().add_to_history(path)
        else:
            messagebox.showerror("Error", f"Path not found: {path}")

    def refresh(self):
        self.status.set_message("Scanning...")
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Stop old scanner if running
        if self.scanner and self.scanner.is_alive():
            self.scanner.stop()
            
        pattern = self.filter_var.get().strip() or "*"
        
        self.scanner = Scanner(
            self.directory, 
            pattern, 
            self.use_regex.get(), 
            self.recursive.get(),
            self.scan_queue,
            self.log
        )
        self.scanner.start()
        self.after(100, self.check_scan_queue)

    def check_scan_queue(self):
        try:
            results = self.scan_queue.get_nowait()
            self.populate_tree(results)
            self.status.set_message(f"Found {len(results)} items.")
        except queue.Empty:
            if self.scanner and self.scanner.is_alive():
                self.after(100, self.check_scan_queue)
            else:
                self.status.set_message("Ready")

    def populate_tree(self, paths):
        # Optimization: Insert in batches? For now, bulk insert
        for path in paths:
            try:
                stat = os.stat(path)
                size = stat.st_size
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                is_dir = os.path.isdir(path)
                
                name = os.path.basename(path)
                ftype = "Folder" if is_dir else os.path.splitext(name)[1]
                icon = Icons.get_icon(name, is_dir)
                
                # Treeview doesn't support images easily in all themes/modes without tweaks
                # We will stick to text for now or simple unicode icons from utility
                display_name = f"{icon} {name}"
                
                self.tree.insert("", "end", values=(display_name, human_readable_size(size), mtime, ftype), tags=(path,)) 
            except OSError:
                continue

    def on_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        
        vals = self.tree.item(item_id, "values")
        tags = self.tree.item(item_id, "tags")
        if tags:
            path = tags[0]
            if os.path.isdir(path):
                self.navigate_to(path)
            else:
                self.open_file(path)

    def on_select(self, event):
        selection = self.tree.selection()
        if selection:
            tags = self.tree.item(selection[0], "tags")
            if tags:
                path = tags[0]
                self.update_preview(path)
                self.status.set_info(path)

    def update_preview(self, path):
        self.preview_canvas.delete("all")
        if not os.path.isfile(path):
            self.preview_canvas.create_text(100, 100, text="No Preview", anchor="nw")
            return
            
        ext = os.path.splitext(path)[1].lower()
        w = self.preview_canvas.winfo_width()
        h = self.preview_canvas.winfo_height()
        
        if ext in Config.IMAGE_EXTENSIONS:
            try:
                img = Image.open(path)
                img.thumbnail((w, h))
                self.tk_img = ImageTk.PhotoImage(img) # Keep ref
                self.preview_canvas.create_image(w//2, h//2, image=self.tk_img)
            except Exception:
                self.preview_canvas.create_text(w//2, h//2, text="Image Error")
        elif ext in Config.TEXT_EXTENSIONS:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read(1000)
                self.preview_canvas.create_text(10, 10, text=content, anchor="nw", width=w-20)
            except Exception:
                 self.preview_canvas.create_text(w//2, h//2, text="Text Error")
        else:
             self.preview_canvas.create_text(w//2, h//2, text=f"No preview for {ext}")

    def open_file(self, path):
        try:
            os.startfile(path)
        except AttributeError:
            import subprocess
            subprocess.call(['xdg-open', path]) # Linux

    def sort_column(self, col):
        # Simplistic sort
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        items.sort(reverse=self.sort_reverse)
        for index, (val, k) in enumerate(items):
            self.tree.move(k, '', index)
        self.sort_reverse = not self.sort_reverse

    def log(self, msg):
        # Bubble up to main window
        if self.main_window:
            self.main_window.log(msg)

    # Operations
    def delete_selected(self):
        selected = self.tree.selection()
        if selected and messagebox.askyesno("Delete", "Are you sure?"):
            for item in selected:
                path = self.tree.item(item, 'tags')[0]
                self.engine.submit_task(self.engine.delete, path)
            self.refresh() # Might need delay or callback
            
    def rename_selected(self):
        selected = self.tree.selection()
        if not selected: return
        path = self.tree.item(selected[0], 'tags')[0]
        new_name = simpledialog.askstring("Rename", "New Name:", initialvalue=os.path.basename(path))
        if new_name:
            new_path = os.path.join(os.path.dirname(path), new_name)
            self.engine.submit_task(self.engine.rename, path, new_path)
            self.refresh()
