import tkinter as tk
from tkinter import ttk


class CommandPalette(tk.Toplevel):
    def __init__(self, master, actions_callback):
        super().__init__(master)
        self.title("Command palette")
        self.transient(master)
        self.resizable(False, False)
        self.geometry(f"600x400+{master.winfo_rootx() + max(0, (master.winfo_width() - 600) // 2)}+{master.winfo_rooty() + max(0, (master.winfo_height() - 400) // 2)}")
        self.actions = actions_callback()
        self.filtered = self.actions
        ttk.Label(self, text="Type to find an action or folder", padding=(12, 10)).pack(anchor="w")
        self.entry = ttk.Entry(self, font=("Segoe UI", 13))
        self.entry.pack(fill=tk.X, padx=12)
        self.entry.bind("<KeyRelease>", self.filter)
        self.entry.bind("<Down>", lambda event: self.move_selection(1))
        self.entry.bind("<Up>", lambda event: self.move_selection(-1))
        self.listbox = tk.Listbox(self, font=("Segoe UI", 11), relief=tk.FLAT, exportselection=False, activestyle="none")
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        self.listbox.bind("<Double-Button-1>", self.execute)
        self.bind("<Return>", self.execute)
        self.bind("<Escape>", lambda event: self.destroy())
        self.hint = ttk.Label(self, text="", padding=(12, 4))
        self.hint.pack(anchor="w")
        self.refresh_list()
        self.grab_set()
        self._focus_id = self.after_idle(self.entry.focus_set)

    def destroy(self):
        if hasattr(self, "_focus_id"):
            self.after_cancel(self._focus_id)
        super().destroy()

    def filter(self, event=None):
        if event and event.keysym in {"Up", "Down", "Return", "Escape"}:
            return
        query = self.entry.get().casefold()
        self.filtered = [action for action in self.actions if query in action[0].casefold()]
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name, _ in self.filtered:
            self.listbox.insert(tk.END, name)
        if self.filtered:
            self.listbox.select_set(0)
            self.listbox.activate(0)
        self.hint.configure(text=f"{len(self.filtered)} actions · ↑ ↓ to choose · Enter to run · Esc to close" if self.filtered else "No matching actions.")

    def move_selection(self, delta):
        if self.filtered:
            selected = self.listbox.curselection()
            index = max(0, min(len(self.filtered) - 1, (selected[0] if selected else 0) + delta))
            self.listbox.selection_clear(0, tk.END)
            self.listbox.select_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
        return "break"

    def execute(self, event=None):
        selected = self.listbox.curselection()
        if selected:
            command = self.filtered[selected[0]][1]
            self.destroy()
            command()
        return "break"
