import os
import threading
import queue
import fnmatch
import re
import time
from app.utils.formatters import human_readable_size

class Scanner(threading.Thread):
    def __init__(self, directory, pattern, use_regex, recursive, result_queue, log_callback):
        super().__init__()
        self.directory = directory
        self.pattern = pattern
        self.use_regex = use_regex
        self.recursive = recursive
        self.result_queue = result_queue
        self.log_callback = log_callback
        self.stop_event = threading.Event()
        self.daemon = True

    def stop(self):
        self.stop_event.set()

    def run(self):
        results = []
        try:
            # Optimization: Use os.scandir which is faster than os.listdir/os.walk
            # because it retrieves file attributes in one syscall on many OSes.
            
            if self.recursive:
                for root, dirs, files in os.walk(self.directory):
                    if self.stop_event.is_set():
                        break
                    for name in files:
                        if self.match(name):
                             # We only need minimal info here, but for sorting/display we might need stats.
                             # For performance in recursive search, we might just store paths and stat later on demand,
                             # OR stat now. Let's start with paths.
                             results.append(os.path.join(root, name))
            else:
                try:
                    with os.scandir(self.directory) as it:
                        for entry in it:
                            if self.stop_event.is_set():
                                break
                            if entry.is_file():
                                if self.match(entry.name):
                                    # Create a lightweight object or tuple
                                    results.append(entry.path)
                except OSError as e:
                     self.log_callback(f"Access denied or error: {e}")

            if not self.stop_event.is_set():
                self.log_callback(f"Scanned {len(results)} items in {self.directory}")
                self.result_queue.put(results)
                
        except Exception as e:
            self.log_callback(f"Error scanning directory: {e}")

    def match(self, name):
        if self.use_regex:
            try:
                return re.search(self.pattern, name)
            except re.error:
                return False
        else:
            return fnmatch.fnmatch(name, self.pattern)
