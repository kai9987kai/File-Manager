import tkinter as tk
from tkinter import ttk
import os
from app.utils.formatters import human_readable_size

class DiskVisualizer(ttk.Frame):
    def __init__(self, master, path, **kwargs):
        super().__init__(master, **kwargs)
        self.path = path
        self.canvas = tk.Canvas(self, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.bind("<Configure>", self.on_resize)
        self.data_cache = None

    def update_path(self, path):
        self.path = path
        self.refresh()

    def refresh(self):
        # Scan directory for sizes (simplified for now, ideally async)
        self.data_cache = self._scan_sizes(self.path)
        self.draw()

    def _scan_sizes(self, path):
        items = []
        total_size = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        size = entry.stat().st_size
                        if entry.is_dir():
                            # Simplified: Recurse 1 level or just take partial size?
                            # For speed, let's just visualise files and immedate folders
                            pass 
                        items.append({'name': entry.name, 'size': size, 'path': entry.path, 'is_dir': entry.is_dir()})
                        total_size += size
                    except OSError:
                        pass
        except OSError:
            pass
        
        items.sort(key=lambda x: x['size'], reverse=True)
        return {'total': total_size, 'items': items}

    def on_resize(self, event):
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        if not self.data_cache or self.data_cache['total'] == 0:
            self.canvas.create_text(self.winfo_width()//2, self.winfo_height()//2, text="Empty or No Access")
            return

        w = self.winfo_width()
        h = self.winfo_height()
        total = self.data_cache['total']
        
        # Simple Treemap algorithm (Squarified is better but Slice-and-Dice is easier to implement quickly)
        # We'll use a vertical stack for now to show relative sizes
        
        y_cursor = 0
        colors = ["#ff9999", "#66b3ff", "#99ff99", "#ffcc99", "#c2c2f0"]
        
        for i, item in enumerate(self.data_cache['items']):
            if item['size'] == 0: continue
            
            fraction = item['size'] / total
            block_h = h * fraction
            
            # Min height to be visible
            if block_h < 2: 
                break 

            color = colors[i % len(colors)]
            x0, y0 = 0, y_cursor
            x1, y1 = w, y_cursor + block_h
            
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="white")
            self.canvas.create_text(w/2, y0 + block_h/2, text=f"{item['name']} ({human_readable_size(item['size'])})")
            
            y_cursor += block_h
