"""Bounded previews, loaded off the Tk event thread."""
from collections import deque
from concurrent.futures import Future
import os
import stat
import threading
import warnings

from app.config import Config


class PreviewExecutor:
    """A bounded pool for discardable reads that may stall on remote storage.

    Running reads cannot be interrupted safely, so workers are daemons and
    never keep the process alive after the UI closes. Callers consume Future
    results on the UI thread and discard superseded futures. Workers perform
    no Tk operations. This executor is not suitable for file mutations.
    """

    def __init__(self, max_workers=2, max_pending=8):
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if type(max_pending) is not int or max_pending < 1:
            raise ValueError("max_pending must be a positive integer")
        self._max_pending = max_pending
        self._pending = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._threads = [
            threading.Thread(target=self._worker, name=f"preview-reader-{index + 1}", daemon=True)
            for index in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, function, *args, **kwargs):
        future = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError("Cannot schedule reads after preview shutdown.")
            # Cancelled stale selections should not consume pending capacity.
            self._pending = deque(item for item in self._pending if not item[0].cancelled())
            if len(self._pending) >= self._max_pending:
                future.set_exception(RuntimeError(
                    "Preview workers are busy. Try selecting the file again shortly."
                ))
                return future
            self._pending.append((future, function, args, kwargs))
            self._condition.notify()
        return future

    def _worker(self):
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if not self._pending:
                    return
                future, function, args, kwargs = self._pending.popleft()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def shutdown(self, wait=False, cancel_futures=True):
        with self._condition:
            self._closed = True
            cancelled = list(self._pending) if cancel_futures else []
            if cancel_futures:
                self._pending.clear()
            self._condition.notify_all()
        # Future callbacks must not execute while the executor lock is held.
        for future, _, _, _ in cancelled:
            future.cancel()
        if wait:
            current = threading.current_thread()
            for thread in self._threads:
                if thread is not current:
                    thread.join()


def _open_preview_stream(path):
    """Read without blocking rename/trash while a preview is open on Windows.

    FILE_SHARE_DELETE permits renames as well as deletion; the read handle
    continues to refer to the same file until it closes.
    https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
    """
    if os.name != "nt":
        return open(path, "rb")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    # GENERIC_READ; FILE_SHARE_READ | WRITE | DELETE; OPEN_EXISTING; NORMAL.
    handle = create_file(os.fspath(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close_handle(handle)
        raise
    # Ownership passes to the descriptor, then the Python file object.
    try:
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def load_preview(path):
    """Return (kind, content); image content is a detached Pillow image."""
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return "text", "Select a regular file to preview its contents."
        extension = os.path.splitext(path)[1].lower()
        if extension in Config.IMAGE_EXTENSIONS:
            if info.st_size > 32 * 1024 * 1024:
                return "text", "Image exceeds the 32 MB preview limit. Open the file to view it."
            try:
                from PIL import Image
            except ImportError:
                return "text", "Install Pillow to enable image previews."
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with _open_preview_stream(path) as stream, Image.open(stream) as source:
                    if source.width * source.height > 40_000_000:
                        return "text", "Image exceeds the 40 megapixel preview limit."
                    source.thumbnail((640, 640))
                    return "image", source.convert("RGBA")
        if extension in Config.TEXT_EXTENSIONS or not extension:
            with _open_preview_stream(path) as stream:
                raw = stream.read(32769)
            if b"\x00" in raw:
                return "text", "Binary file — text preview unavailable."
            text = raw[:32768].decode("utf-8-sig", errors="replace")
            if len(raw) > 32768:
                text += "\n\n[Preview limited to the first 32 KB]"
            return "text", text or "Empty file."
        return "text", f"No built-in preview for {extension or 'this file type'}.\nDouble-click the file to open it."
    except (OSError, ValueError, Warning) as error:
        return "text", f"Preview unavailable: {error}"
