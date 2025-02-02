#!/usr/bin/env python
"""
Enhanced File Manager with further innovations:
 - Breadcrumb navigation for directory paths.
 - ttk.Treeview for file listing with columns (Name, Size, Modified).
 - Clickable column headers for sorting files.
 - Context menu (right-click) with file operations.
 - File preview pane (for images) and details pane.
 - Keyboard shortcuts: Enter (open), F2 (rename), Delete (delete).
 - Robust error handling and confirmations.
"""

import os
import sys
import fnmatch
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel, PhotoImage
from tkinter.constants import BOTH, END, LEFT, RIGHT, TOP, BOTTOM, X, Y
from PIL import Image, ImageTk  # Requires Pillow

# Global state to remember last used directory and filter pattern
dialogstates = {}

class AdvancedFileDialog:
    title = "Advanced File Manager"

    def __init__(self, master, title=None):
        if title is None:
            title = self.title
        self.master = master
        self.directory = None
        self.sort_by = "Name"   # Default sort column
        self.sort_reverse = False  # Ascending by default
        self.current_preview = None

        # Main top-level window
        self.top = Toplevel(master)
        self.top.title(title)
        self.top.iconname(title)
        self.top.geometry("1100x700")
        self.top.minsize(800, 500)

        # --- Breadcrumb Navigation ---
        self.breadcrumb_frame = ttk.Frame(self.top)
        self.breadcrumb_frame.pack(side=TOP, fill=X, padx=5, pady=5)
        self.breadcrumb_label = ttk.Label(self.breadcrumb_frame, text="Path: ")
        self.breadcrumb_label.pack(side=LEFT)
        self.breadcrumb_links = []  # To hold clickable breadcrumb items

        # --- Filter/Search Entry ---
        self.filter_frame = ttk.Frame(self.top)
        self.filter_frame.pack(side=TOP, fill=X, padx=5)
        self.filter_entry = ttk.Entry(self.filter_frame)
        self.filter_entry.pack(side=LEFT, fill=X, expand=True)
        self.filter_entry.bind('<Return>', self.filter_command)
        self.filter_button = ttk.Button(self.filter_frame, text="Filter", command=self.filter_command)
        self.filter_button.pack(side=LEFT, padx=5)

        # --- Main Panes ---
        self.main_pane = ttk.PanedWindow(self.top, orient=tk.HORIZONTAL)
        self.main_pane.pack(expand=True, fill=BOTH, padx=5, pady=5)

        # Left pane: Directory list (simple listbox with multi-selection)
        self.dir_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(self.dir_frame, weight=1)
        ttk.Label(self.dir_frame, text="Directories").pack(anchor="w")
        self.dir_listbox = tk.Listbox(self.dir_frame, exportselection=0, selectmode=tk.SINGLE)
        self.dir_scroll = ttk.Scrollbar(self.dir_frame, orient=tk.VERTICAL, command=self.dir_listbox.yview)
        self.dir_listbox.config(yscrollcommand=self.dir_scroll.set)
        self.dir_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        self.dir_scroll.pack(side=RIGHT, fill=Y)
        self.dir_listbox.bind('<ButtonRelease-1>', self.dir_select_event)
        self.dir_listbox.bind('<Double-ButtonRelease-1>', self.dir_double_event)

        # Center pane: File list as a Treeview with columns: Name, Size, Modified
        self.file_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(self.file_frame, weight=3)
        columns = ("Name", "Size", "Modified")
        self.file_tree = ttk.Treeview(self.file_frame, columns=columns, show="headings", selectmode="extended")
        for col in columns:
            self.file_tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            self.file_tree.column(col, anchor="w")
        self.file_tree.pack(expand=True, fill=BOTH)
        self.file_scroll = ttk.Scrollbar(self.file_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=self.file_scroll.set)
        self.file_scroll.pack(side=RIGHT, fill=Y)
        self.file_tree.bind('<ButtonRelease-1>', self.file_select_event)
        self.file_tree.bind('<Double-ButtonRelease-1>', self.file_double_event)
        self.file_tree.bind("<Button-3>", self.file_right_click_event)  # Right-click context menu

        # --- Right pane: Preview and File Details ---
        self.preview_frame = ttk.Frame(self.main_pane, width=300)
        self.main_pane.add(self.preview_frame, weight=1)
        ttk.Label(self.preview_frame, text="Preview").pack(anchor="w")
        self.preview_canvas = tk.Canvas(self.preview_frame, bg="gray", width=280, height=280)
        self.preview_canvas.pack(padx=5, pady=5)
        ttk.Label(self.preview_frame, text="File Details:").pack(anchor="w", padx=5)
        self.details_text = tk.Text(self.preview_frame, height=8, wrap="word")
        self.details_text.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.details_text.config(state="disabled")

        # --- Bottom Frame: Action Buttons and Selection Entry ---
        self.bottom_frame = ttk.Frame(self.top)
        self.bottom_frame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
        self.selection_entry = ttk.Entry(self.bottom_frame)
        self.selection_entry.pack(side=LEFT, fill=X, expand=True, padx=5)
        self.selection_entry.bind('<Return>', self.ok_event)

        self.open_button = ttk.Button(self.bottom_frame, text="OPEN", command=self.ok_command)
        self.open_button.pack(side=LEFT, padx=5)
        self.rename_button = ttk.Button(self.bottom_frame, text="RENAME FILE", command=self.rename_command)
        self.rename_button.pack(side=LEFT, padx=5)
        self.delete_button = ttk.Button(self.bottom_frame, text="DELETE FILE", command=self.delete_command)
        self.delete_button.pack(side=LEFT, padx=5)
        self.cancel_button = ttk.Button(self.bottom_frame, text="Cancel", command=self.cancel_command)
        self.cancel_button.pack(side=RIGHT, padx=5)

        # --- Keyboard shortcuts ---
        self.top.bind('<F2>', lambda e: self.rename_command())
        self.top.bind('<Delete>', lambda e: self.delete_command())
        self.top.bind('<Return>', lambda e: self.ok_command())

        # --- Context Menu for File Operations ---
        self.context_menu = tk.Menu(self.top, tearoff=0)
        self.context_menu.add_command(label="Open", command=lambda: self.open_selected_file())
        self.context_menu.add_command(label="Rename", command=lambda: self.rename_command())
        self.context_menu.add_command(label="Delete", command=lambda: self.delete_command())
        self.context_menu.add_command(label="Properties", command=lambda: self.show_properties())

    # ---------- Main Functionality ----------
    def go(self, dir_or_file=os.curdir, pattern="*", default="", key=None):
        """Initialize the file manager and run the main loop."""
        if key and key in dialogstates:
            self.directory, pattern = dialogstates[key]
        else:
            dir_or_file = os.path.expanduser(dir_or_file)
            if os.path.isdir(dir_or_file):
                self.directory = dir_or_file
            else:
                self.directory, default = os.path.split(dir_or_file)
        self.set_filter(self.directory, pattern)
        self.selection_entry.delete(0, END)
        self.selection_entry.insert(END, default)
        self.filter_command()
        self.top.wait_visibility()
        self.top.grab_set()
        self.how = None
        self.master.mainloop()  # Wait until quit() is called
        if key:
            directory, pattern = self.get_filter()
            if self.how:
                directory = os.path.dirname(self.how)
            dialogstates[key] = directory, pattern
        self.top.destroy()
        return self.how

    def update_breadcrumbs(self):
        """Update the clickable breadcrumb navigation based on current directory."""
        # Clear previous breadcrumbs
        for widget in self.breadcrumb_frame.winfo_children():
            if widget != self.breadcrumb_label:
                widget.destroy()
        # Split directory and create clickable labels
        parts = os.path.normpath(self.directory).split(os.sep)
        # For Windows absolute paths, preserve drive letter (e.g., C:\)
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
            sep = ttk.Label(self.breadcrumb_frame, text=" > ")
            sep.pack(side=LEFT)

    def breadcrumb_click(self, path):
        """Handle click on a breadcrumb; navigate to that directory."""
        if os.path.isdir(path):
            self.directory = path
            self.set_filter(self.directory, "*")
            self.filter_command()

    def set_filter(self, dir, pat):
        """Update the filter entry field."""
        if not os.path.isabs(dir):
            try:
                pwd = os.getcwd()
            except OSError:
                pwd = None
            if pwd:
                dir = os.path.join(pwd, dir)
                dir = os.path.normpath(dir)
        self.filter_entry.delete(0, END)
        self.filter_entry.insert(END, os.path.join(dir or os.curdir, pat or "*"))
        self.update_breadcrumbs()

    def get_filter(self):
        """Extract directory and pattern from filter entry."""
        filter_text = self.filter_entry.get().strip()
        filter_text = os.path.expanduser(filter_text)
        if filter_text == "":
            filter_text = os.path.join(os.curdir, "*")
        if filter_text[-1:] == os.sep or os.path.isdir(filter_text):
            filter_text = os.path.join(filter_text, "*")
        return os.path.split(filter_text)

    def filter_command(self, event=None):
        """Update directories and file list based on filter."""
        dir, pat = self.get_filter()
        try:
            names = os.listdir(dir)
        except OSError as e:
            messagebox.showerror("Directory Error", f"Cannot open directory {dir}:\n{e}")
            self.master.bell()
            return
        self.directory = dir
        self.set_filter(dir, pat)
        # Update directory listbox (list directories only, with '..' for parent)
        self.dir_listbox.delete(0, END)
        self.dir_listbox.insert(END, os.pardir)
        subdirs = []
        files = []
        for name in names:
            fullname = os.path.join(dir, name)
            if os.path.isdir(fullname):
                subdirs.append(name)
            elif fnmatch.fnmatch(name, pat):
                files.append(name)
        subdirs.sort()
        files.sort()
        for sub in subdirs:
            self.dir_listbox.insert(END, sub)
        # Update file tree (Name, Size, Modified)
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        for name in files:
            fullpath = os.path.join(dir, name)
            size = os.path.getsize(fullpath)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fullpath)))
            self.file_tree.insert("", END, values=(name, self.human_readable_size(size), mtime))
        self.preview_canvas.delete("all")
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", END)
        self.details_text.config(state="disabled")
        # Update selection entry (clear it)
        self.selection_entry.delete(0, END)

    def human_readable_size(self, size, decimal_places=1):
        """Convert size in bytes to human-readable format."""
        for unit in ['B','KB','MB','GB','TB']:
            if size < 1024:
                return f"{size:.{decimal_places}f} {unit}"
            size /= 1024
        return f"{size:.{decimal_places}f} PB"

    # ---------- Event Handlers ----------
    def dir_select_event(self, event):
        """Handle selection in the directory listbox."""
        selection = self.dir_listbox.curselection()
        if selection:
            subdir = self.dir_listbox.get(selection[0])
            new_dir = os.path.normpath(os.path.join(self.directory, subdir))
            if os.path.isdir(new_dir):
                self.directory = new_dir
                # Keep same filter pattern
                _, pat = self.get_filter()
                self.set_filter(new_dir, pat)
                self.filter_command()

    def dir_double_event(self, event):
        """Double-click in directory list also triggers filtering."""
        self.filter_command()

    def file_select_event(self, event):
        """Handle selection in the file tree: update selection entry, preview, and details."""
        selected = self.file_tree.selection()
        if selected:
            item = self.file_tree.item(selected[0])
            file = item["values"][0]
            self.selection_entry.delete(0, END)
            self.selection_entry.insert(END, os.path.join(self.directory, file))
            self.show_preview(os.path.join(self.directory, file))
            self.show_details(os.path.join(self.directory, file))
        else:
            self.preview_canvas.delete("all")
            self.details_text.config(state="normal")
            self.details_text.delete("1.0", END)
            self.details_text.config(state="disabled")

    def file_double_event(self, event):
        """Double-click on file opens it if it exists."""
        selected = self.file_tree.selection()
        if selected:
            item = self.file_tree.item(selected[0])
            file = item["values"][0]
            fullpath = os.path.join(self.directory, file)
            if os.path.isfile(fullpath):
                self.open_file(fullpath)

    def file_right_click_event(self, event):
        """Show context menu on right-click in file tree."""
        iid = self.file_tree.identify_row(event.y)
        if iid:
            self.file_tree.selection_set(iid)
            self.context_menu.post(event.x_root, event.y_root)

    def ok_event(self, event):
        self.ok_command()

    # ---------- Commands ----------
    def ok_command(self):
        """Open the selected file(s) with the system default program."""
        selected = self.file_tree.selection()
        if selected:
            for iid in selected:
                item = self.file_tree.item(iid)
                file = item["values"][0]
                fullpath = os.path.join(self.directory, file)
                if os.path.isfile(fullpath):
                    self.open_file(fullpath)
            self.quit(self.selection_entry.get())
        else:
            messagebox.showinfo("No Selection", "Please select a file to open.")

    def delete_command(self):
        """Delete the selected file(s) after confirmation."""
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showwarning("No File", "No file selected for deletion.")
            return
        confirm = messagebox.askyesno("Delete Confirmation", "Are you sure you want to delete the selected file(s)?")
        if confirm:
            for iid in selected:
                item = self.file_tree.item(iid)
                file = item["values"][0]
                fullpath = os.path.join(self.directory, file)
                try:
                    if os.path.exists(fullpath) and os.path.isfile(fullpath):
                        os.remove(fullpath)
                except Exception as e:
                    messagebox.showerror("Deletion Error", f"Error deleting {fullpath}:\n{e}")
            self.filter_command()

    def rename_command(self):
        """Rename the selected file (exactly one must be selected)."""
        selected = self.file_tree.selection()
        if not selected or len(selected) != 1:
            messagebox.showwarning("Select One File", "Please select exactly one file to rename.")
            return
        item = self.file_tree.item(selected[0])
        file = item["values"][0]
        fullpath = os.path.join(self.directory, file)
        new_name = simpledialog.askstring("Rename File", f"Enter new name for {file}:")
        if new_name and new_name != file:
            new_fullpath = os.path.join(self.directory, new_name)
            try:
                os.rename(fullpath, new_fullpath)
                self.filter_command()
            except Exception as e:
                messagebox.showerror("Rename Error", f"Error renaming file:\n{e}")

    def open_selected_file(self):
        """Open the file currently selected in the file tree."""
        selected = self.file_tree.selection()
        if selected:
            item = self.file_tree.item(selected[0])
            file = item["values"][0]
            fullpath = os.path.join(self.directory, file)
            self.open_file(fullpath)

    def show_properties(self):
        """Display a properties dialog for the selected file."""
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo("No Selection", "No file selected.")
            return
        item = self.file_tree.item(selected[0])
        file = item["values"][0]
        fullpath = os.path.join(self.directory, file)
        if os.path.isfile(fullpath):
            size = os.path.getsize(fullpath)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fullpath)))
            info = f"File: {fullpath}\nSize: {self.human_readable_size(size)}\nModified: {mtime}"
            messagebox.showinfo("File Properties", info)

    def cancel_command(self):
        """Cancel and quit the dialog."""
        self.quit(None)

    def quit(self, how):
        self.how = how
        self.master.quit()

    def open_file(self, path):
        """Open a file using the system default program."""
        try:
            if sys.platform.startswith('darwin'):
                os.system(f"open '{path}'")
            elif os.name == 'nt':
                os.startfile(path)
            elif os.name == 'posix':
                os.system(f"xdg-open '{path}'")
        except Exception as e:
            messagebox.showerror("Open File Error", f"Could not open file:\n{e}")

    # ---------- Preview and Details ----------
    def show_preview(self, filepath):
        """If the file is an image, display a thumbnail in the preview pane."""
        self.preview_canvas.delete("all")
        ext = os.path.splitext(filepath)[1].lower()
        if os.path.isfile(filepath) and ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
            try:
                image = Image.open(filepath)
                image.thumbnail((280, 280))
                self.current_preview = ImageTk.PhotoImage(image)
                # Center the image on the canvas
                canvas_width = self.preview_canvas.winfo_width()
                canvas_height = self.preview_canvas.winfo_height()
                self.preview_canvas.create_image(canvas_width//2, canvas_height//2, image=self.current_preview)
            except Exception as e:
                self.preview_canvas.create_text(140, 140, text="Preview Error", fill="white")
        else:
            self.preview_canvas.create_text(140, 140, text="No Preview", fill="white")

    def show_details(self, filepath):
        """Display file details such as size, modification date, and type in the details pane."""
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", END)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(filepath)))
            ftype = os.path.splitext(filepath)[1].lower() or "Unknown"
            details = (f"Path: {filepath}\n"
                       f"Size: {self.human_readable_size(size)}\n"
                       f"Modified: {mtime}\n"
                       f"Type: {ftype}")
            self.details_text.insert(END, details)
        else:
            self.details_text.insert(END, "No file details available.")
        self.details_text.config(state="disabled")

    # ---------- Sorting ----------
    def sort_by_column(self, col):
        """Sort the file list by the given column."""
        # Toggle sort order if sorting by the same column
        if self.sort_by == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_by = col
            self.sort_reverse = False
        # Gather file items
        items = []
        for iid in self.file_tree.get_children():
            item = self.file_tree.item(iid)["values"]
            items.append((iid, item))
        # Determine sort key
        if col == "Name":
            key_func = lambda t: t[1][0].lower()
        elif col == "Size":
            # Convert size from human-readable back to number may be tricky; instead, sort by file size from disk.
            key_func = lambda t: os.path.getsize(os.path.join(self.directory, t[1][0]))
        elif col == "Modified":
            key_func = lambda t: os.path.getmtime(os.path.join(self.directory, t[1][0]))
        else:
            key_func = lambda t: t[1][0].lower()
        items.sort(key=key_func, reverse=self.sort_reverse)
        # Rearrange items in treeview
        for index, (iid, _) in enumerate(items):
            self.file_tree.move(iid, '', index)

def test():
    """Simple test program for the Advanced File Manager."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    fd = AdvancedFileDialog(root)
    loadfile = fd.go(key="advanced")
    if loadfile:
        print("Selected file:", loadfile)
    else:
        print("No file selected.")

if __name__ == '__main__':
    test()
