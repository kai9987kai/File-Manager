"""Cancellable directory scanning and metadata-based ordering for the file view."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
import queue
import re
import stat
import threading
from typing import Iterable


@dataclass(frozen=True)
class FileEntry:
    path: str
    name: str
    is_dir: bool
    size: int | None
    mtime: float | None
    is_link: bool = False


def _natural_key(value: str) -> tuple:
    """Tagged parts keep comparisons safe even when a name begins with a digit."""
    return tuple(
        (1, int(part)) if part.isdecimal() else (0, part.casefold())
        for part in re.split(r"(\d+)", value)
    )


def sort_entries(
    entries: Iterable[FileEntry], column: str = "Name", reverse: bool = False
) -> list[FileEntry]:
    """Sort real metadata, preserving folders first and unknown values last."""
    column = column.casefold()

    def name_key(entry):
        return _natural_key(entry.name), _natural_key(entry.path), entry.path

    def value(entry):
        if column == "size":
            return entry.size
        if column in {"modified", "mtime", "date", "date modified"}:
            return entry.mtime
        if column == "type":
            return _natural_key("Folder" if entry.is_dir else os.path.splitext(entry.name)[1])
        if column in {"location", "folder", "path"}:
            return _natural_key(os.path.dirname(entry.path))
        return _natural_key(entry.name)

    folders, files = [], []
    for entry in entries:
        (folders if entry.is_dir else files).append(entry)
    result = []
    for group in (folders, files):
        known = [entry for entry in group if value(entry) is not None]
        unknown = [entry for entry in group if value(entry) is None]
        known.sort(key=lambda entry: (value(entry), name_key(entry)), reverse=reverse)
        unknown.sort(key=name_key, reverse=reverse)
        result.extend(known)
        result.extend(unknown)
    return result


class Scanner(threading.Thread):
    """Publish batches and exactly one terminal event, each tagged by scan id.

    Metadata is read on this worker with ``follow_symlinks=False``. Recursive
    scans never enter symlinks or Windows reparse-point directories. Callers
    must ignore events from superseded scan ids and consume events on the UI
    thread. ``log_callback`` is retained for compatibility; diagnostics travel
    through the queue so a callback cannot accidentally touch Tk from a worker.
    Give each scan its own bounded queue. Cancellation may drop queued batches
    to leave room for the terminal event when a consumer has gone away.
    """

    MAX_ERRORS = 20
    QUEUE_TIMEOUT = 0.05

    def __init__(
        self, directory, pattern, use_regex, recursive, result_queue, log_callback,
        *, scan_id=0, show_hidden=False, batch_size=200,
    ):
        super().__init__(daemon=True)
        self.directory = os.fspath(directory)
        self.pattern = pattern or ""
        self.use_regex = use_regex
        self.recursive = recursive
        self.result_queue = result_queue
        self.log_callback = log_callback
        self.scan_id = scan_id
        self.show_hidden = show_hidden
        self.batch_size = max(1, int(batch_size))
        self.stop_event = threading.Event()
        self._errors = []
        self._error_count = 0
        self._published_count = 0
        self._pattern_error = None
        self._matcher = None
        try:
            if self.pattern:
                if use_regex:
                    self._matcher = re.compile(self.pattern, re.IGNORECASE).search
                elif any(char in self.pattern for char in "*?["):
                    self._matcher = re.compile(
                        fnmatch.translate(self.pattern), re.IGNORECASE
                    ).match
                else:
                    needle = self.pattern.casefold()
                    self._matcher = lambda name: needle in name.casefold()
        except re.error as exc:
            self._pattern_error = f"Invalid regular expression: {exc}"

    def stop(self):
        self.stop_event.set()

    def match(self, name):
        if self._pattern_error:
            return False
        return self._matcher is None or bool(self._matcher(name))

    def _emit(self, event_type, **fields):
        event = {"scan_id": self.scan_id, "type": event_type, **fields}
        while True:
            if event_type == "batch" and self.stop_event.is_set():
                return False
            if event_type == "done":
                event.update(
                    count=self._published_count, cancelled=self.stop_event.is_set()
                )
            try:
                self.result_queue.put(event, timeout=self.QUEUE_TIMEOUT)
                if event_type == "batch":
                    self._published_count += len(fields["entries"])
                return True
            except queue.Full:
                if event_type == "batch" or not self.stop_event.is_set():
                    continue
                # A cancelled scan may no longer have a consumer. Free a slot
                # for its terminal event, accounting only for retained results.
                try:
                    dropped = self.result_queue.get_nowait()
                except queue.Empty:
                    continue
                if dropped.get("type") == "batch":
                    self._published_count -= len(dropped["entries"])
                self.result_queue.task_done()

    def _record_error(self, path, error):
        self._error_count += 1
        if self._error_count <= self.MAX_ERRORS - 1:
            self._errors.append(f"{path}: {error}")
        elif self._error_count == self.MAX_ERRORS:
            self._errors.append("1 additional error omitted.")
        else:
            self._errors[-1] = (
                f"{self._error_count - self.MAX_ERRORS + 1} additional errors omitted."
            )

    def _read_entry(self, entry):
        if not self.show_hidden and entry.name.startswith("."):
            return None
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            self._record_error(entry.path, exc)
            metadata = None

        attributes = getattr(metadata, "st_file_attributes", 0)
        if not self.show_hidden and attributes & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2):
            return None
        if metadata is not None:
            is_dir = stat.S_ISDIR(metadata.st_mode) or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 16)
            )
            is_link = stat.S_ISLNK(metadata.st_mode) or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            )
        else:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError as exc:
                self._record_error(entry.path, exc)
                is_dir, is_link = False, True
            # A failed no-follow stat cannot prove a directory is safe to enter.
            if is_dir:
                is_link = True

        return FileEntry(
            path=entry.path,
            name=entry.name,
            is_dir=is_dir,
            size=metadata.st_size if metadata is not None and not is_dir else None,
            mtime=metadata.st_mtime if metadata is not None else None,
            is_link=is_link,
        )

    def run(self):
        if self._pattern_error:
            self._emit("error", message=self._pattern_error)
            return

        batch = []
        pending = [self.directory]
        try:
            while pending and not self.stop_event.is_set():
                directory = pending.pop()
                try:
                    with os.scandir(directory) as iterator:
                        for raw_entry in iterator:
                            if self.stop_event.is_set():
                                break
                            entry = self._read_entry(raw_entry)
                            if entry is None:
                                continue
                            if self.recursive and entry.is_dir and not entry.is_link:
                                pending.append(entry.path)
                            if not self.match(entry.name):
                                continue
                            batch.append(entry)
                            if len(batch) >= self.batch_size:
                                self._emit("batch", entries=batch)
                                batch = []
                except OSError as exc:
                    if directory == self.directory:
                        self._emit("error", message=f"Cannot read {directory}: {exc}")
                        return
                    self._record_error(directory, exc)
            if batch:
                self._emit("batch", entries=batch)
            self._emit(
                "done", errors=list(self._errors),
            )
        except Exception as exc:
            self._emit("error", message=f"Error scanning {self.directory}: {exc}")
