import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

from app.core.preview import load_preview
from app.core.scanner import Scanner, sort_entries
from app.ui.widgets import Breadcrumb, StatusBar
from app.ui.visualizer import DiskVisualizer
from app.utils.formatters import human_readable_size
from app.utils.icons import Icons


class FileManagerTab(ttk.Frame):
    def __init__(self, parent_notebook, directory, main_window):
        super().__init__(parent_notebook)
        self.main_window = main_window
        self.directory = os.path.abspath(directory)
        self.engine = main_window.engine
        self.sort_by = "Name"
        self.sort_reverse = False
        self.use_regex = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)
        self.show_hidden = tk.BooleanVar(value=main_window.state.show_hidden)
        self.filter_var = tk.StringVar()
        self.address_var = tk.StringVar(value=self.directory)
        self._history = [self.directory]
        self._history_index = 0
        self._entries = {}
        self._items = {}
        self._scan_id = 0
        self._scanning = False
        self._busy = False
        self._closed = False
        self._restore_selection = set()
        self._preview_future = None
        self._navigation_future = None
        self._navigation_request = None
        self.scanner = None
        self.scan_queue = queue.Queue(maxsize=8)
        self._setup_ui()
        self.update_navigation()
        self.refresh()
        self._poll_id = self.after(60, self._poll)

    def _setup_ui(self):
        top = ttk.Frame(self, padding=(8, 8))
        top.pack(fill=tk.X)
        navigation = ttk.Frame(top)
        navigation.pack(fill=tk.X)
        self.back_button = ttk.Button(navigation, text="←", width=3, command=self.go_back)
        self.back_button.pack(side=tk.LEFT)
        self.forward_button = ttk.Button(navigation, text="→", width=3, command=self.go_forward)
        self.forward_button.pack(side=tk.LEFT, padx=3)
        self.up_button = ttk.Button(navigation, text="↑", width=3, command=self.go_up)
        self.up_button.pack(side=tk.LEFT, padx=(0, 6))
        self.address_entry = ttk.Entry(navigation, textvariable=self.address_var)
        self.address_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.address_entry.bind("<Return>", lambda e: self.navigate_to(self.address_var.get()))
        ttk.Button(navigation, text="Go", command=lambda: self.navigate_to(self.address_var.get())).pack(side=tk.LEFT, padx=4)
        self.favorite_button = ttk.Button(navigation, text="☆ Favorite", command=self.toggle_favorite)
        self.favorite_button.pack(side=tk.LEFT)
        self.breadcrumb = Breadcrumb(top, self.directory, self.navigate_to)
        self.breadcrumb.pack(fill=tk.X, pady=(8, 6))
        toolbar = ttk.Frame(top)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        self.action_buttons = {}
        for label, action in [
            ("New folder", self.create_folder), ("Copy", self.copy_selected),
            ("Cut", self.cut_selected), ("Paste", self.paste),
            ("Rename", self.rename_selected), ("Trash", self.delete_selected),
            ("Properties", self.show_properties),
        ]:
            button = ttk.Button(toolbar, text=label, command=action)
            button.pack(side=tk.LEFT, padx=(0, 4))
            self.action_buttons[label] = button
        filters = ttk.Frame(top)
        filters.pack(fill=tk.X)
        ttk.Label(filters, text="Search").pack(side=tk.LEFT, padx=(0, 8))
        self.filter_entry = ttk.Entry(filters, textvariable=self.filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.filter_entry.bind("<Return>", lambda e: self.refresh())
        self.filter_entry.bind("<Escape>", lambda e: self.clear_search())
        ttk.Button(filters, text="Search", command=self.refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(filters, text="Clear", command=self.clear_search).pack(side=tk.LEFT)
        self.stop_button = ttk.Button(filters, text="Stop", command=self.stop_scan)
        self.stop_button.pack(side=tk.LEFT, padx=4)
        for label, variable, command in [
            ("Regex", self.use_regex, self.refresh),
            ("Subfolders", self.recursive, self.refresh),
            ("Hidden", self.show_hidden, self.hidden_changed),
        ]:
            ttk.Checkbutton(filters, text=label, variable=variable, command=command).pack(side=tk.LEFT, padx=3)
        ttk.Label(top, text="Search by name, wildcard (*.pdf), or regular expression. Enable Subfolders to search below this folder.", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))

        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=8)
        tree_frame = ttk.Frame(self.paned)
        self.paned.add(tree_frame, weight=4)
        columns = ("Name", "Size", "Modified", "Type", "Location")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        for column in columns:
            self.tree.heading(column, text=column, command=lambda c=column: self.sort_column(c))
            self.tree.column(column, anchor="w", width=110, minwidth=65)
        self.tree.column("Name", width=290, minwidth=140)
        self.tree.column("Size", width=95, anchor="e")
        self.tree.column("Modified", width=150)
        self.tree.column("Type", width=90)
        self.tree.column("Location", width=200)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.empty_label = ttk.Label(tree_frame, text="", anchor="center")
        self.tree.bind("<Double-Button-1>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Button-3>", self.context_menu)
        self.tree.bind("<Button-2>", self.context_menu)
        for sequence, action in {
            "<Return>": self.open_selected, "<F2>": self.rename_selected,
            "<Delete>": self.delete_selected, "<Control-c>": self.copy_selected,
            "<Control-x>": self.cut_selected, "<Control-v>": self.paste,
            "<Control-a>": self.select_all,
        }.items():
            self.tree.bind(sequence, lambda e, command=action: self.main_window._shortcut(command))

        self.notebook_preview = ttk.Notebook(self.paned, width=300)
        self.paned.add(self.notebook_preview, weight=1)
        preview = ttk.Frame(self.notebook_preview, padding=10)
        self.notebook_preview.add(preview, text="Preview")
        self.preview_title = ttk.Label(preview, text="Select a file", font=("Segoe UI", 11, "bold"), wraplength=270)
        self.preview_title.pack(fill=tk.X, pady=(0, 8))
        self.preview_text = ScrolledText(preview, wrap=tk.WORD, width=30, state="disabled", relief=tk.FLAT, font=("Consolas", 10))
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas = tk.Canvas(preview, highlightthickness=0, width=280, height=300)
        self.preview_canvas.bind("<Configure>", self._draw_image)
        self._image = None
        self.tk_img = None
        self.visualizer = DiskVisualizer(self.notebook_preview, self.directory)
        self.notebook_preview.add(self.visualizer, text="File sizes")
        self.status = StatusBar(self)
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=4, before=self.paned)
        self._show_text("Select a file to preview its contents.")

    def navigate_to(self, path, record=True, history_index=None):
        path = os.path.expandvars(os.path.expanduser(path.strip().strip('"')))
        if not os.path.isabs(path):
            path = os.path.join(self.directory, path)
        path = os.path.abspath(path)
        if self._navigation_future:
            self._navigation_future.cancel()
        self._navigation_request = (path, record, history_index)
        self._navigation_future = self.main_window.navigation_executor.submit(os.path.isdir, path)
        self.status.set_message(f"Opening {path}…")

    def _finish_navigation(self, path, record, history_index):
        changed = os.path.normcase(path) != os.path.normcase(self.directory)
        if changed and record:
            self._history = self._history[:self._history_index + 1] + [path]
            self._history_index += 1
        if history_index is not None:
            self._history_index = history_index
        self.directory = path
        if changed:
            self.filter_var.set("")
            self.recursive.set(False)
        self.address_var.set(path)
        self.breadcrumb.update_path(path)
        self.visualizer.update_path(path)
        self.main_window.notebook.tab(self, text=os.path.basename(path) or path)
        self.main_window.state.add_to_history(path, validated=True)
        self.update_navigation()
        self.refresh()

    def update_navigation(self):
        self.back_button.configure(state="normal" if self._history_index > 0 else "disabled")
        self.forward_button.configure(state="normal" if self._history_index < len(self._history) - 1 else "disabled")
        self.up_button.configure(state="normal" if os.path.dirname(self.directory) != self.directory else "disabled")
        favorite = any(os.path.normcase(self.directory) == os.path.normcase(path) for path in self.main_window.state.favorites)
        self.favorite_button.configure(text="★ Favorited" if favorite else "☆ Favorite")

    def go_back(self):
        if self._history_index > 0:
            target = self._history_index - 1
            self.navigate_to(self._history[target], record=False, history_index=target)

    def go_forward(self):
        if self._history_index + 1 < len(self._history):
            target = self._history_index + 1
            self.navigate_to(self._history[target], record=False, history_index=target)

    def go_up(self):
        self.navigate_to(os.path.dirname(self.directory))

    def focus_address(self):
        self.address_entry.focus_set()
        self.address_entry.selection_range(0, tk.END)

    def focus_search(self):
        self.filter_entry.focus_set()
        self.filter_entry.selection_range(0, tk.END)

    def clear_search(self):
        self.filter_var.set("")
        self.refresh()

    def toggle_hidden(self):
        self.show_hidden.set(not self.show_hidden.get())
        self.hidden_changed()

    def hidden_changed(self):
        self.main_window.state.show_hidden = self.show_hidden.get()
        self.main_window.state.save()
        self.refresh()

    def toggle_favorite(self):
        state = self.main_window.state
        if any(os.path.normcase(self.directory) == os.path.normcase(path) for path in state.favorites):
            state.remove_favorite(self.directory)
        else:
            state.add_favorite(self.directory)
        self.main_window.refresh_favorites()
        for tab in self.master.winfo_children():
            if isinstance(tab, FileManagerTab):
                tab.update_navigation()

    def refresh(self):
        if self._closed:
            return
        self._restore_selection = set(self.selected_paths())
        if self.scanner:
            self.scanner.stop()
        self._scan_id += 1
        self.scan_queue = queue.Queue(maxsize=8)
        self._entries.clear()
        self._items.clear()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self._clear_preview()
        self.visualizer.set_entries([])
        self.tree.configure(displaycolumns=("Name", "Size", "Modified", "Type", "Location") if self.recursive.get() else ("Name", "Size", "Modified", "Type"))
        self.empty_label.place_forget()
        self.status.set_message("Scanning…")
        self._scanning = True
        self.stop_button.configure(state="normal")
        self.scanner = Scanner(self.directory, self.filter_var.get().strip(), self.use_regex.get(),
            self.recursive.get(), self.scan_queue, None, scan_id=self._scan_id, show_hidden=self.show_hidden.get())
        self.scanner.start()
        self._update_actions()

    def stop_scan(self):
        if self.scanner and self._scanning:
            self.scanner.stop()
            self.status.set_message("Stopping scan…")

    def _poll(self):
        if self._closed:
            return
        if self._navigation_future and self._navigation_future.done():
            future, self._navigation_future = self._navigation_future, None
            path, record, history_index = self._navigation_request
            try:
                if not future.result():
                    raise OSError(f"Folder not found or unavailable:\n{path}")
            except Exception as error:
                messagebox.showerror("Cannot open folder", str(error), parent=self)
                self.address_var.set(self.directory)
                self.status.set_message("Folder could not be opened.")
            else:
                self._finish_navigation(path, record, history_index)
        for _ in range(3):
            try:
                event = self.scan_queue.get_nowait()
            except queue.Empty:
                break
            if event.get("scan_id") != self._scan_id:
                continue
            if event["type"] == "batch":
                self.populate_tree(event["entries"])
                self.status.set_message(f"Scanning… {len(self._entries):,} items")
            elif event["type"] in ("done", "error"):
                self._scanning = False
                self.stop_button.configure(state="disabled")
                self._apply_sort()
                self.visualizer.set_entries(list(self._entries.values()))
                if event["type"] == "error":
                    text = event["message"]
                    self.log(text)
                else:
                    self.main_window.state.add_to_history(self.directory, validated=True)
                    folders = sum(entry.is_dir for entry in self._entries.values())
                    total = sum(entry.size or 0 for entry in self._entries.values() if not entry.is_dir and not entry.is_link)
                    text = f"{len(self._entries):,} items · {folders:,} folders · {human_readable_size(total)} in files"
                    if event.get("cancelled"):
                        text += " · scan stopped"
                    if event.get("errors"):
                        text += f" · {len(event['errors'])} access issue(s), see activity"
                        for error in event["errors"]:
                            self.log(error)
                self.status.set_message(text)
                if not self._entries:
                    self.empty_label.configure(text=event["message"] if event["type"] == "error" else "No items to show.\nTry clearing search or showing hidden files.")
                    self.empty_label.place(relx=0.5, rely=0.4, anchor="center")
                self._update_actions()
        if self._preview_future and self._preview_future.done():
            future, self._preview_future = self._preview_future, None
            try:
                kind, content = future.result()
            except Exception as error:
                kind, content = "text", f"Preview unavailable: {error}"
            if kind == "image":
                self._image = content
                self.preview_text.pack_forget()
                self.preview_canvas.pack(fill=tk.BOTH, expand=True)
                self._draw_image()
            else:
                self._show_text(content)
        self._poll_id = self.after(60, self._poll)

    def populate_tree(self, entries):
        for entry in entries:
            if entry.path in self._entries:
                continue
            self._entries[entry.path] = entry
            size = "—" if entry.is_dir or entry.size is None else human_readable_size(entry.size)
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.mtime)) if entry.mtime is not None else "—"
            kind = "Link" if entry.is_link else "Folder" if entry.is_dir else os.path.splitext(entry.name)[1].lower() or "File"
            location = os.path.relpath(os.path.dirname(entry.path), self.directory)
            item = self.tree.insert("", "end", values=(f"{Icons.get_icon(entry.name, entry.is_dir)} {entry.name}", size, modified, kind, location))
            self._items[item] = entry
            if entry.path in self._restore_selection:
                self.tree.selection_add(item)

    def sort_column(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_by == column else False
        self.sort_by = column
        self._apply_sort()

    def _apply_sort(self):
        entries = sort_entries(list(self._entries.values()), self.sort_by, self.sort_reverse)
        ids = {entry.path: item for item, entry in self._items.items()}
        for index, entry in enumerate(entries):
            self.tree.move(ids[entry.path], "", index)
        for column in self.tree["columns"]:
            arrow = (" ▼" if self.sort_reverse else " ▲") if column == self.sort_by else ""
            self.tree.heading(column, text=column + arrow)

    def selected_paths(self):
        return [self._items[item].path for item in self.tree.selection() if item in self._items]

    def _operation_paths(self):
        paths = self.selected_paths()
        # A recursive search can select both a folder and its children.
        directories = [p for p in paths if self._entries[p].is_dir and not self._entries[p].is_link]
        return [p for p in paths if not any(p != directory and os.path.commonpath([p, directory]) == directory for directory in directories)]

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.open_selected()

    def open_selected(self):
        paths = self.selected_paths()
        if paths:
            path = paths[0]
            if self._entries[path].is_dir:
                self.navigate_to(path)
            else:
                self.open_file(path)

    def open_file(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        except OSError as error:
            messagebox.showerror("Cannot open file", str(error), parent=self)

    def on_select(self, event=None):
        paths = self.selected_paths()
        total = sum(self._entries[p].size or 0 for p in paths if p in self._entries and not self._entries[p].is_dir and not self._entries[p].is_link)
        self.status.set_info(f"{len(paths)} selected · {human_readable_size(total)}" if paths else "")
        self._update_actions()
        if len(paths) == 1:
            self.preview_title.configure(text=os.path.basename(paths[0]) or paths[0])
            self.update_preview(paths[0])
        elif paths:
            self._clear_preview(f"{len(paths)} items selected.")
        else:
            self._clear_preview()

    def update_preview(self, path):
        if self._preview_future:
            self._preview_future.cancel()
        self._show_text("Loading preview…")
        self._preview_future = self.main_window.preview_executor.submit(load_preview, path)

    def _clear_preview(self, message="Select a file to preview its contents."):
        if self._preview_future:
            self._preview_future.cancel()
            self._preview_future = None
        self.preview_title.configure(text="Preview")
        self._show_text(message)

    def _show_text(self, text):
        self._image = None
        self.tk_img = None
        self.preview_canvas.pack_forget()
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    def _draw_image(self, event=None):
        if self._image is None:
            return
        from PIL import ImageTk
        image = self._image.copy()
        width, height = max(1, self.preview_canvas.winfo_width()), max(1, self.preview_canvas.winfo_height())
        image.thumbnail((width, height))
        self.tk_img = ImageTk.PhotoImage(image, master=self)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(width // 2, height // 2, image=self.tk_img)

    def _update_actions(self):
        count = len(self.selected_paths())
        for label, button in self.action_buttons.items():
            enabled = not self._busy
            if label in ("Copy", "Cut", "Trash", "Properties"):
                enabled = enabled and count > 0
            elif label == "Rename":
                enabled = enabled and count == 1
            elif label == "Paste":
                enabled = enabled and bool(self.main_window.state.clipboard)
            button.configure(state="normal" if enabled else "disabled")

    def context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item and item not in self.tree.selection():
            self.tree.selection_set(item)
        self.tree.focus_set()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=self.open_selected, state="normal" if self.selected_paths() else "disabled")
        paths = self.selected_paths()
        if len(paths) == 1 and self._entries[paths[0]].is_dir:
            menu.add_command(label="Open in new tab", command=lambda: self.main_window.new_tab(paths[0]))
        menu.add_separator()
        self._update_actions()
        for label, action in [("Copy", self.copy_selected), ("Cut", self.cut_selected), ("Paste", self.paste), ("Rename", self.rename_selected), ("Trash", self.delete_selected), ("New folder", self.create_folder), ("Properties", self.show_properties)]:
            menu.add_command(label="Move to Trash / Recycle Bin" if label == "Trash" else label, command=action, state=str(self.action_buttons[label]["state"]))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            menu.destroy()

    def _set_clipboard(self, operation):
        paths = self._operation_paths()
        if paths and not self._busy:
            self.main_window.state.clipboard = {"paths": tuple(paths), "operation": operation}
            self.log(f"{len(paths)} item(s) ready to {operation}. Navigate to a destination and paste.")
            for tab in self.master.winfo_children():
                if isinstance(tab, FileManagerTab):
                    tab._update_actions()

    def copy_selected(self):
        self._set_clipboard("copy")

    def cut_selected(self):
        self._set_clipboard("move")

    def paste(self):
        clipboard = self.main_window.state.clipboard
        if not clipboard or self._busy:
            return
        target = self.directory
        action = self.engine.move if clipboard["operation"] == "move" else self.engine.copy
        self._run_operation("Move" if clipboard["operation"] == "move" else "Copy",
            list(clipboard["paths"]), lambda p: action(p, target), clipboard=clipboard)

    def create_folder(self):
        if self._busy:
            return
        name = simpledialog.askstring("New folder", "Folder name:", parent=self)
        if name:
            try:
                self.engine.validate_name(name)
            except ValueError as error:
                messagebox.showerror("Invalid name", str(error), parent=self)
                return
            path = os.path.join(self.directory, name)
            self._run_operation("Create folder", [path], self.engine.create_folder)

    def rename_selected(self):
        paths = self.selected_paths()
        if self._busy or len(paths) != 1:
            return
        source = paths[0]
        name = simpledialog.askstring("Rename", "New name:", initialvalue=os.path.basename(source), parent=self)
        if name and name != os.path.basename(source):
            try:
                self.engine.validate_name(name)
            except ValueError as error:
                messagebox.showerror("Invalid name", str(error), parent=self)
                return
            target = os.path.join(os.path.dirname(source), name)
            rename = self.engine.rename
            self._run_operation("Rename", [source], lambda p: rename(p, target))

    def delete_selected(self):
        paths = self._operation_paths()
        if self._busy or not paths:
            return
        names = "\n".join(os.path.basename(path) for path in paths[:6])
        if len(paths) > 6:
            names += f"\n… and {len(paths) - 6} more"
        if messagebox.askyesno("Move to Trash / Recycle Bin",
                f"Move {len(paths)} item(s) to the system trash?\n\n{names}\n\nYou can restore them using your system's trash.", parent=self):
            self._run_operation("Move to Trash", paths, self.engine.delete)

    def _run_operation(self, label, paths, action, clipboard=None):
        self._busy = True
        self._update_actions()
        self.status.set_message(f"{label}…")

        def work():
            completed, errors = [], []
            for path in paths:
                try:
                    completed.append((path, action(path)))
                except Exception as error:
                    errors.append(f"{path}: {error}")
            return {"completed": completed, "errors": errors}

        def finished(result):
            if result is not None:
                completed = result["completed"]
                if clipboard and clipboard["operation"] == "move" and self.main_window.state.clipboard is clipboard:
                    moved = {source for source, _ in completed}
                    remaining = tuple(p for p in clipboard["paths"] if p not in moved)
                    self.main_window.state.clipboard = {"paths": remaining, "operation": "move"} if remaining else None
                self.log(f"{label}: {len(completed)} completed, {len(result['errors'])} failed")
                if result["errors"]:
                    for error in result["errors"]:
                        self.log(error)
                    messagebox.showerror(f"{label}: some items failed", "\n\n".join(result["errors"][:8]), parent=self.main_window)
            if not self._closed:
                self._busy = False
            self.main_window.refresh_tabs()

        self.main_window.submit_operation(label, work, finished)

    def show_properties(self):
        paths = self.selected_paths()
        if not paths:
            return
        entries = [self._entries[path] for path in paths]
        folders = sum(entry.is_dir for entry in entries)
        total = sum(entry.size or 0 for entry in entries if not entry.is_dir and not entry.is_link)
        details = f"{len(entries)} item(s) · {folders} folder(s)\nFile bytes: {total:,} ({human_readable_size(total)})\nFolder contents and link targets excluded."
        if len(entries) == 1:
            entry = entries[0]
            modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.mtime)) if entry.mtime is not None else "Unknown"
            details += f"\n\nPath: {entry.path}\nModified: {modified}\nSymbolic link / junction: {'Yes' if entry.is_link else 'No'}"
        messagebox.showinfo("Properties", details, parent=self)

    def log(self, message):
        self.main_window.log(message)

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        if self.scanner:
            self.scanner.stop()
        if self._preview_future:
            self._preview_future.cancel()
        if self._navigation_future:
            self._navigation_future.cancel()
        if hasattr(self, "_poll_id"):
            self.after_cancel(self._poll_id)
        # Release Tcl-owned objects on this thread, even if an operation future
        # temporarily retains the tab's Python callbacks after it closes.
        self.tk_img = None
        self.use_regex = self.recursive = self.show_hidden = None
        self.filter_var = self.address_var = None
        super().destroy()
