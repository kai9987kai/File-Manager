"""Background file operations with explicit conflicts and recoverable deletion."""

import errno
import os
import re
import shutil
import stat
import threading
from concurrent.futures import ThreadPoolExecutor


class Engine:
    """Share one instance; log callbacks must be thread-safe, e.g. Queue.put."""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="file-operation")
        self._operation_lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._closed = False

    def _log(self, message):
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                # Reporting cannot turn a completed operation into a failure.
                pass

    def submit_task(self, func, *args, **kwargs):
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("The file operation engine has been shut down.")
            return self.executor.submit(self._wrap_task, func, *args, **kwargs)

    def _wrap_task(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as error:
            self._log(f"File operation failed: {error}")
            raise

    def shutdown(self, wait=False):
        """Cancel queued work; an operation already running can finish."""
        with self._lifecycle_lock:
            self._closed = True
        self.executor.shutdown(wait=wait, cancel_futures=True)

    @staticmethod
    def validate_name(name):
        """Validate a portable single filename, including Windows device names."""
        if not isinstance(name, str) or not name or name in {".", ".."}:
            raise ValueError("Enter a file or folder name.")
        if name[-1] in {" ", "."} or any(ord(char) < 32 for char in name):
            raise ValueError("Names cannot end with a space or dot or contain control characters.")
        if any(char in '<>:"/\\|?*' for char in name):
            raise ValueError('Names cannot contain < > : " / \\ | ? * or a path.')
        stem = name.split(".", 1)[0].rstrip(" ").upper()
        if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(
            r"(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", stem
        ):
            raise ValueError(f"{name!r} is a reserved Windows device name.")
        if len(name.encode("utf-16-le")) // 2 > 255:
            raise ValueError("Names must be at most 255 UTF-16 characters long.")
        return name

    @staticmethod
    def _path(path):
        return os.path.abspath(os.fspath(path))

    @staticmethod
    def _is_link(path):
        return os.path.islink(path) or getattr(os.path, "isjunction", lambda value: False)(path)

    @classmethod
    def _reject_link_components(cls, path):
        current = path
        while True:
            if cls._is_link(current):
                raise ValueError(f"Symbolic links and junctions are not supported for this operation: {current}")
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

    @classmethod
    def _source(cls, path):
        path = cls._path(path)
        cls._reject_link_components(path)
        info = os.stat(path, follow_symlinks=False)
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError(f"Only regular files and folders are supported: {path}")
        if os.path.dirname(path) == path:
            raise ValueError("Operations on a filesystem root are not supported.")
        return path

    @classmethod
    def _check_tree(cls, source):
        """Reject links before transferring, including links inside folders."""
        if not os.path.isdir(source):
            return
        def on_error(error):
            raise error
        for root, directories, files in os.walk(source, followlinks=False, onerror=on_error):
            for name in directories + files:
                child = os.path.join(root, name)
                if cls._is_link(child):
                    raise ValueError(f"Folder contains a symbolic link or junction: {child}")
                mode = os.stat(child, follow_symlinks=False).st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise ValueError(f"Folder contains an unsupported special file: {child}")

    @classmethod
    def _target(cls, source, target):
        target = cls._path(target)
        parent = os.path.dirname(target)
        cls._reject_link_components(parent)
        if not os.path.isdir(parent):
            raise NotADirectoryError(f"Destination folder does not exist: {parent}")
        if os.path.normcase(source) == os.path.normcase(target):
            raise ValueError("Source and destination are the same path.")
        if os.path.isdir(source):
            try:
                nested = os.path.normcase(os.path.commonpath([source, target])) == os.path.normcase(source)
            except ValueError:  # Different Windows drives.
                nested = False
            if nested:
                raise ValueError("A folder cannot be copied or moved inside itself.")
        if os.path.lexists(target):
            raise FileExistsError(f"Destination already exists: {target}")
        return target

    @classmethod
    def _copy_file(cls, source, target):
        cls._reject_link_components(source)
        created = False
        try:
            with open(source, "rb") as reader:
                with open(target, "xb") as writer:
                    created = True
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
            shutil.copystat(source, target, follow_symlinks=False)
        except Exception:
            if created:
                os.unlink(target)
            raise
        return target

    @classmethod
    def _copy(cls, source, target):
        if os.path.isdir(source):
            # copytree reserves the destination with mkdir; files use exclusive
            # creation, so an existing destination is never replaced.
            return shutil.copytree(source, target, copy_function=cls._copy_file)
        return cls._copy_file(source, target)

    @classmethod
    def _move(cls, source, target):
        if os.name == "nt":
            try:
                # Windows rename fails atomically if the destination exists.
                os.rename(source, target)
                return target
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
        elif os.path.isfile(source):
            try:
                # POSIX rename can overwrite, so use an exclusive hard link.
                os.link(source, target, follow_symlinks=False)
            except OSError as error:
                if error.errno not in {errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS}:
                    raise
            else:
                os.unlink(source)
                return target
        # Cross-device moves and portable directory moves copy exclusively,
        # deleting the source only after the entire copy has succeeded.
        cls._copy(source, target)
        if os.path.isdir(source):
            shutil.rmtree(source)
        else:
            os.unlink(source)
        return target

    def copy(self, src, dst):
        """Copy src into destination DIRECTORY dst, rejecting existing targets."""
        with self._operation_lock:
            source = self._source(src)
            destination = self._path(dst)
            self._reject_link_components(destination)
            if not os.path.isdir(destination):
                raise NotADirectoryError(f"Destination must be an existing folder: {destination}")
            target = self._target(source, os.path.join(destination, os.path.basename(source)))
            self._check_tree(source)
            self._log(f"Copying: {source} -> {target}")
            result = self._copy(source, target)
            self._log(f"Copied: {result}")
            return result

    def move(self, src, dst):
        """Move src into destination DIRECTORY dst, rejecting existing targets."""
        with self._operation_lock:
            source = self._source(src)
            destination = self._path(dst)
            self._reject_link_components(destination)
            if not os.path.isdir(destination):
                raise NotADirectoryError(f"Destination must be an existing folder: {destination}")
            target = self._target(source, os.path.join(destination, os.path.basename(source)))
            self._check_tree(source)
            self._log(f"Moving: {source} -> {target}")
            result = self._move(source, target)
            self._log(f"Moved: {result}")
            return result

    def delete(self, path, permanent=False):
        """Send an item to the system trash; permanent removal is explicit."""
        with self._operation_lock:
            path = self._source(path)
            if permanent:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)
                self._log(f"Permanently deleted: {path}")
            else:
                try:
                    from send2trash import send2trash
                except ImportError as error:
                    raise RuntimeError(
                        "Recycle Bin support requires Send2Trash. Install dependencies with "
                        "python -m pip install -r requirements.txt. Nothing was deleted."
                    ) from error
                send2trash(path)
                self._log(f"Sent to trash: {path}")
            return path

    def rename(self, src, dst):
        """Rename to a full destination path without overwriting an existing item."""
        with self._operation_lock:
            source = self._source(src)
            target = self._path(dst)
            self.validate_name(os.path.basename(target))
            target = self._target(source, target)
            self._check_tree(source)
            result = self._move(source, target)
            self._log(f"Renamed: {source} -> {result}")
            return result

    def create_folder(self, path):
        with self._operation_lock:
            path = self._path(path)
            self.validate_name(os.path.basename(path))
            self._reject_link_components(os.path.dirname(path))
            os.mkdir(path)
            self._log(f"Created folder: {path}")
            return path
