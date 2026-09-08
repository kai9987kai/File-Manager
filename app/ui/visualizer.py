"""A size chart over the browser's existing listing, with no filesystem I/O."""

import os
import tkinter as tk
from tkinter import ttk

from app.utils.formatters import human_readable_size


class DiskVisualizer(ttk.Frame):
    MAX_BARS = 8

    def __init__(self, master, path, **kwargs):
        super().__init__(master, **kwargs)
        self.path = path
        self.data_cache = None
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_resize)
        self.bind("<<ThemeChanged>>", self.on_resize)

    def update_path(self, path):
        self.path = path
        self.data_cache = None
        self.draw()

    def set_entries(self, entries):
        """Use the metadata already fetched for the current browser listing.

        Directories and links are excluded: directory entry sizes do not
        describe their contents, and link sizes do not describe target usage.
        """
        items = []
        excluded = 0
        for entry in entries:
            if entry.is_dir or entry.is_link:
                excluded += 1
                continue
            if type(entry.size) is not int or entry.size < 0:
                continue
            items.append({"name": entry.name, "size": entry.size, "path": entry.path})
        items.sort(key=lambda item: (-item["size"], item["name"].casefold()))
        self.data_cache = {
            "items": items,
            "total": sum(item["size"] for item in items),
            "excluded": excluded,
        }
        self.draw()

    def refresh(self):
        """Redraw cached metadata; the browser owns asynchronous refreshes."""
        self.draw()

    def on_resize(self, event=None):
        self.draw()

    @staticmethod
    def _shorten(text, character_limit):
        if len(text) <= character_limit:
            return text
        return text[:max(1, character_limit - 1)] + "…"

    def draw(self):
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 240)
        height = max(self.canvas.winfo_height(), 220)
        style = ttk.Style(self)
        background = style.lookup("Treeview", "background") or "white"
        foreground = style.lookup("Treeview", "foreground") or "#172033"
        self.canvas.configure(bg=background)
        margin = 18
        available = width - margin * 2
        title = os.path.basename(os.path.normpath(self.path)) or str(self.path)
        self.canvas.create_text(
            margin, 20, anchor="w", text=self._shorten(title, max(12, int(available / 8))),
            fill=foreground, font=("TkDefaultFont", 12, "bold"),
        )
        self.canvas.create_text(
            margin, 49, anchor="nw", width=available,
            text="Listed files only · folder contents excluded", fill=foreground,
        )
        if self.data_cache is None:
            self.canvas.create_text(
                width / 2, 122, width=available, text="Waiting for file listing…", fill=foreground,
            )
            return
        items = self.data_cache["items"]
        total = self.data_cache["total"]
        count = len(items)
        self.canvas.create_text(
            margin, 95, anchor="w", fill=foreground,
            text=f"{human_readable_size(total)} across {count} file{'s' if count != 1 else ''}",
            font=("TkDefaultFont", 10, "bold"),
        )
        if not items:
            self.canvas.create_text(
                width / 2, 153, width=available, fill=foreground,
                text="No regular files in this listing.\nFolders and links are excluded.",
            )
            return
        if total == 0:
            self.canvas.create_text(
                width / 2, 153, width=available, fill=foreground,
                text=f"All {count} listed file{'s are' if count != 1 else ' is'} empty (0 bytes).",
            )
            return
        # Leave room for readable labels even when the preview panel is short.
        capacity = min(self.MAX_BARS, max(1, int((height - 153) / 48)))
        shown = items[:capacity]
        maximum = items[0]["size"]
        for index, item in enumerate(shown):
            y = 125 + index * 48
            size_text = human_readable_size(item["size"])
            name_space = max(6, int((available - len(size_text) * 7 - 16) / 7))
            self.canvas.create_text(
                margin, y, anchor="w", text=self._shorten(item["name"], name_space), fill=foreground,
            )
            self.canvas.create_text(width - margin, y, anchor="e", text=size_text, fill=foreground)
            self.canvas.create_rectangle(
                margin, y + 13, width - margin, y + 23, fill="#dbe5f3", outline="",
            )
            if item["size"]:
                self.canvas.create_rectangle(
                    margin, y + 13, margin + max(2, available * item["size"] / maximum), y + 23,
                    fill="#3478c9", outline="",
                )
        remaining = len(items) - len(shown)
        if remaining:
            remainder_size = sum(item["size"] for item in items[len(shown):])
            self.canvas.create_text(
                margin, 125 + len(shown) * 48, anchor="w", fill=foreground,
                text=f"{remaining} more file{'s' if remaining != 1 else ''} · {human_readable_size(remainder_size)}",
            )
