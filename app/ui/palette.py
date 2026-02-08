import tkinter as tk
from tkinter import ttk

class CommandPalette(tk.Toplevel):
    def __init__(self, master, actions_callback):
        super().__init__(master)
        self.overrideredirect(True) # Remove window decorations
        self.geometry("600x400")
        
        # Center the window
        # self.eval('tk::PlaceWindow . center') # Doesn't work well with overrideredirect on some OS
        
        # Manually center
        mw = master.winfo_width()
        mh = master.winfo_height()
        mx = master.winfo_rootx()
        my = master.winfo_rooty()
        x = mx + (mw - 600) // 2
        y = my + (mh - 400) // 2
        self.geometry(f"+{x}+{y}")

        self.actions = actions_callback() # List of (name, command)
        self.filtered = self.actions

        self.configure(bg="#333")
        
        self.entry = ttk.Entry(self, font=("Consolas", 14))
        self.entry.pack(fill=tk.X, padx=10, pady=10)
        self.entry.bind("<KeyRelease>", self.filter)
        self.entry.bind("<Return>", self.execute)
        self.entry.bind("<Escape>", lambda e: self.destroy())
        self.entry.focus_set()

        self.listbox = tk.Listbox(self, font=("Consolas", 12), bg="#444", fg="white", relief=tk.FLAT)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.listbox.bind("<Double-Button-1>", self.execute)
        
        self.refresh_list()
        
        # Close on click outside (simplified)
        self.bind("<FocusOut>", lambda e: self.destroy())

    def filter(self, event):
        query = self.entry.get().lower()
        self.filtered = [a for a in self.actions if query in a[0].lower()]
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name, _ in self.filtered:
            self.listbox.insert(tk.END, name)
        if self.filtered:
            self.listbox.select_set(0)

    def execute(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            cmd = self.filtered[index][1]
            self.destroy()
            cmd()
