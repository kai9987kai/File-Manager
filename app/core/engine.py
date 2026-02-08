import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

class Engine:
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.executor = ThreadPoolExecutor(max_workers=4)

    def submit_task(self, func, *args, **kwargs):
        return self.executor.submit(self._wrap_task, func, *args, **kwargs)

    def _wrap_task(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.log_callback(f"Error in background task: {e}")
            raise e

    def copy(self, src, dst):
        self.log_callback(f"Starting copy: {src} -> {dst}")
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
             shutil.copytree(src, os.path.join(dst, os.path.basename(src)))
        self.log_callback(f"Finished copy: {src} -> {dst}")

    def move(self, src, dst):
        self.log_callback(f"Starting move: {src} -> {dst}")
        shutil.move(src, dst)
        self.log_callback(f"Finished move: {src} -> {dst}")

    def delete(self, path):
        self.log_callback(f"Deleting: {path}")
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        self.log_callback(f"Deleted: {path}")

    def rename(self, src, dst):
        self.log_callback(f"Renaming: {src} -> {dst}")
        os.rename(src, dst)
        self.log_callback(f"Renamed: {src} -> {dst}")
        
    def create_folder(self, path):
         self.log_callback(f"Creating folder: {path}")
         os.makedirs(path, exist_ok=True)
         self.log_callback(f"Created folder: {path}")
