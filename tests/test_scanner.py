import os
from pathlib import Path
import queue
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.core.scanner import FileEntry, Scanner, sort_entries


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def scan(self, pattern="", **options):
        result_queue = queue.Queue()
        scanner = Scanner(
            self.root, pattern, options.pop("use_regex", False),
            options.pop("recursive", False), result_queue, lambda message: None,
            **options,
        )
        scanner.run()
        events = []
        while not result_queue.empty():
            events.append(result_queue.get_nowait())
        entries = [entry for event in events if event["type"] == "batch" for entry in event["entries"]]
        return entries, events

    def test_browse_includes_directories_and_background_metadata(self):
        (self.root / "Documents").mkdir()
        (self.root / "Report.txt").write_bytes(b"12345")
        entries, events = self.scan(scan_id=42, batch_size=1)
        entries = {entry.name: entry for entry in entries}
        self.assertTrue(entries["Documents"].is_dir)
        self.assertIsNone(entries["Documents"].size)
        self.assertEqual(entries["Report.txt"].size, 5)
        self.assertGreater(entries["Report.txt"].mtime, 0)
        self.assertEqual([event["type"] for event in events], ["batch", "batch", "done"])
        self.assertTrue(all(event["scan_id"] == 42 for event in events))
        self.assertEqual(events[-1], {"scan_id": 42, "type": "done", "count": 2, "cancelled": False, "errors": []})

    def test_case_insensitive_glob_substring_and_regex(self):
        for name in ["Report.TXT", "budget.csv", "report-backup.txt"]:
            (self.root / name).touch()
        (self.root / "report-folder").mkdir()
        entries, _ = self.scan("REPORT")
        self.assertEqual({entry.name for entry in entries}, {"Report.TXT", "report-backup.txt", "report-folder"})
        entries, _ = self.scan("*.txt")
        self.assertEqual({entry.name for entry in entries}, {"Report.TXT", "report-backup.txt"})
        entries, _ = self.scan(r"^report\.txt$", use_regex=True)
        self.assertEqual([entry.name for entry in entries], ["Report.TXT"])

    def test_regex_is_compiled_once_and_invalid_pattern_emits_one_error(self):
        for number in range(4):
            (self.root / f"file{number}.txt").touch()
        with patch("app.core.scanner.re.compile", wraps=__import__("re").compile) as compile_regex:
            entries, _ = self.scan(r"file\d", use_regex=True)
        self.assertEqual(len(entries), 4)
        self.assertEqual(compile_regex.call_count, 1)
        entries, events = self.scan("[", use_regex=True, scan_id=8)
        self.assertEqual(entries, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["scan_id"], 8)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("Invalid regular expression", events[0]["message"])

    def test_hidden_files_and_directories_are_pruned(self):
        hidden = self.root / ".private"
        hidden.mkdir()
        (hidden / "visible-name.txt").touch()
        (self.root / ".secret").touch()
        (self.root / "public.txt").touch()
        entries, _ = self.scan(recursive=True)
        self.assertEqual([entry.name for entry in entries], ["public.txt"])
        entries, _ = self.scan(recursive=True, show_hidden=True)
        self.assertEqual({entry.name for entry in entries}, {".private", "visible-name.txt", ".secret", "public.txt"})

    def test_recursive_search_descends_nonmatching_folders(self):
        folder = self.root / "archive"
        folder.mkdir()
        (folder / "notes.txt").touch()
        (self.root / "notes-folder").mkdir()
        entries, events = self.scan("notes", recursive=True)
        self.assertEqual({entry.name for entry in entries}, {"notes.txt", "notes-folder"})
        self.assertEqual(events[-1]["count"], 2)

    def test_missing_root_emits_actionable_error(self):
        self.root = self.root / "missing"
        entries, events = self.scan()
        self.assertFalse(entries)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("Cannot read", events[0]["message"])

    def test_inaccessible_subdirectory_is_reported_without_losing_other_results(self):
        blocked = self.root / "blocked"
        blocked.mkdir()
        (self.root / "public.txt").touch()
        real_scandir = os.scandir

        def guarded_scandir(path):
            if os.fspath(path) == str(blocked):
                raise PermissionError("access denied")
            return real_scandir(path)

        with patch("app.core.scanner.os.scandir", side_effect=guarded_scandir):
            entries, events = self.scan(recursive=True)
        self.assertEqual({entry.name for entry in entries}, {"blocked", "public.txt"})
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len(events[-1]["errors"]), 1)
        self.assertIn("access denied", events[-1]["errors"][0])

    def test_cancellation_before_start_has_terminal_event(self):
        result_queue = queue.Queue()
        scanner = Scanner(self.root, "", False, True, result_queue, None, scan_id=17)
        scanner.stop()
        scanner.start()
        scanner.join(timeout=5)
        self.assertFalse(scanner.is_alive())
        self.assertEqual(result_queue.get_nowait(), {"scan_id": 17, "type": "done", "count": 0, "cancelled": True, "errors": []})
        self.assertTrue(result_queue.empty())

    def test_cancellation_between_batches_preserves_published_count(self):
        for number in range(10):
            (self.root / f"file{number}").touch()
        result_queue = queue.Queue()
        scanner = Scanner(self.root, "", False, True, result_queue, None, batch_size=2)
        real_put = result_queue.put

        def cancel_after_batch(event, **kwargs):
            real_put(event, **kwargs)
            if event["type"] == "batch":
                scanner.stop()

        with patch.object(result_queue, "put", side_effect=cancel_after_batch):
            scanner.run()
        batch, done = result_queue.get_nowait(), result_queue.get_nowait()
        self.assertEqual(len(batch["entries"]), 2)
        self.assertEqual(done["count"], 2)
        self.assertTrue(done["cancelled"])
        self.assertTrue(result_queue.empty())

    def test_full_queue_cancellation_exits_without_a_consumer(self):
        for number in range(10):
            (self.root / f"file{number}").touch()
        backpressure = threading.Event()

        class ObservedQueue(queue.Queue):
            def put(self, event, block=True, timeout=None):
                if self.full():
                    backpressure.set()
                return super().put(event, block=block, timeout=timeout)

        result_queue = ObservedQueue(maxsize=2)
        scanner = Scanner(self.root, "", False, True, result_queue, None, batch_size=2)
        scanner.start()
        try:
            self.assertTrue(backpressure.wait(timeout=2))
            self.assertEqual(result_queue.qsize(), 2)
        finally:
            scanner.stop()
            scanner.join(timeout=2)
        self.assertFalse(scanner.is_alive())
        retained, terminal = result_queue.get_nowait(), result_queue.get_nowait()
        self.assertEqual(retained["type"], "batch")
        self.assertEqual(terminal["type"], "done")
        self.assertTrue(terminal["cancelled"])
        self.assertEqual(terminal["count"], len(retained["entries"]))
        self.assertTrue(result_queue.empty())

    def test_cancellation_unblocks_a_terminal_event_waiting_on_a_full_queue(self):
        (self.root / "file").touch()
        terminal_waiting = threading.Event()

        class ObservedQueue(queue.Queue):
            def put(self, event, block=True, timeout=None):
                if event["type"] == "done" and self.full():
                    terminal_waiting.set()
                return super().put(event, block=block, timeout=timeout)

        result_queue = ObservedQueue(maxsize=1)
        scanner = Scanner(self.root, "", False, False, result_queue, None, batch_size=1)
        scanner.start()
        try:
            self.assertTrue(terminal_waiting.wait(timeout=2))
        finally:
            scanner.stop()
            scanner.join(timeout=2)
        self.assertFalse(scanner.is_alive())
        terminal = result_queue.get_nowait()
        self.assertEqual(terminal["type"], "done")
        self.assertEqual(terminal["count"], 0)
        self.assertTrue(terminal["cancelled"])
        self.assertTrue(result_queue.empty())

    def test_fast_batches_preserve_every_result_with_a_bounded_queue(self):
        expected = {f"file{number}" for number in range(20)}
        for name in expected:
            (self.root / name).touch()
        result_queue = queue.Queue(maxsize=1)
        scanner = Scanner(self.root, "", False, False, result_queue, None, batch_size=3)
        scanner.start()
        entries = []
        try:
            while True:
                event = result_queue.get(timeout=2)
                result_queue.task_done()
                if event["type"] != "batch":
                    break
                self.assertLessEqual(len(event["entries"]), 3)
                entries.extend(event["entries"])
            scanner.join(timeout=2)
            self.assertFalse(scanner.is_alive())
            self.assertEqual(event["type"], "done")
            self.assertFalse(event["cancelled"])
            self.assertEqual(event["count"], len(expected))
            self.assertEqual({entry.name for entry in entries}, expected)
            self.assertEqual(len(entries), len(expected))
            self.assertTrue(result_queue.empty())
        finally:
            scanner.stop()
            scanner.join(timeout=2)

    def test_symlink_target_is_not_scanned(self):
        target = self.root / "target"
        target.mkdir()
        (target / "inside.txt").touch()
        link = self.root / "shortcut"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable for this account")
        entries, _ = self.scan(recursive=True)
        self.assertEqual(sum(entry.name == "inside.txt" for entry in entries), 1)
        self.assertTrue(next(entry for entry in entries if entry.name == "shortcut").is_link)

    def test_windows_hidden_attributes_and_junction_are_respected(self):
        class FakeEntry:
            name = "junction"
            path = "junction"

            def stat(self, *, follow_symlinks):
                self.follow_symlinks = follow_symlinks
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_size=0, st_mtime=10,
                                       st_file_attributes=16 | 1024)

        result_queue = queue.Queue()
        scanner = Scanner(self.root, "", False, True, result_queue, None)
        raw = FakeEntry()
        entry = scanner._read_entry(raw)
        self.assertTrue(entry.is_dir)
        self.assertTrue(entry.is_link)
        self.assertFalse(raw.follow_symlinks)

        class FakeIterator:
            def __enter__(self):
                return iter([raw])

            def __exit__(self, *args):
                return False

        with patch("app.core.scanner.os.scandir", return_value=FakeIterator()) as scandir:
            scanner.run()
        self.assertEqual(scandir.call_count, 1)
        with patch.object(raw, "stat", return_value=SimpleNamespace(st_mode=stat.S_IFREG,
                           st_size=1, st_mtime=10, st_file_attributes=2)):
            self.assertIsNone(scanner._read_entry(raw))
            scanner.show_hidden = True
            self.assertIsNotNone(scanner._read_entry(raw))

    def test_stat_errors_preserve_entry_with_unknown_metadata_and_are_bounded(self):
        class UnreadableEntry:
            name = "unreadable.txt"
            path = "unreadable.txt"

            def stat(self, *, follow_symlinks):
                raise PermissionError("metadata denied")

            def is_dir(self, *, follow_symlinks):
                return False

            def is_symlink(self):
                return False

        scanner = Scanner(self.root, "", False, False, queue.Queue(), None)
        entry = scanner._read_entry(UnreadableEntry())
        self.assertIsNone(entry.size)
        self.assertIsNone(entry.mtime)
        for _ in range(100):
            scanner._read_entry(UnreadableEntry())
        self.assertEqual(len(scanner._errors), Scanner.MAX_ERRORS)
        self.assertIn("additional errors omitted", scanner._errors[-1])


class SortEntriesTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            FileEntry("/file10.txt", "file10.txt", False, 100, 20),
            FileEntry("/folder10", "folder10", True, None, 50),
            FileEntry("/file2.txt", "file2.txt", False, 20, 100),
            FileEntry("/folder2", "folder2", True, None, 5),
            FileEntry("/file1.txt", "file1.txt", False, 3, 9),
        ]

    def test_natural_names_and_folders_first_in_both_directions(self):
        self.assertEqual([entry.name for entry in sort_entries(self.entries)],
                         ["folder2", "folder10", "file1.txt", "file2.txt", "file10.txt"])
        self.assertEqual([entry.name for entry in sort_entries(self.entries, reverse=True)],
                         ["folder10", "folder2", "file10.txt", "file2.txt", "file1.txt"])

    def test_numeric_sizes_and_modified_dates(self):
        self.assertEqual([entry.size for entry in sort_entries(self.entries, "Size") if not entry.is_dir], [3, 20, 100])
        self.assertEqual([entry.mtime for entry in sort_entries(self.entries, "Modified")], [5, 50, 9, 20, 100])
        self.assertEqual([entry.size for entry in sort_entries(self.entries, "Size", True) if not entry.is_dir], [100, 20, 3])

    def test_unknown_metadata_stays_last_in_its_group(self):
        self.entries.append(FileEntry("/unknown", "unknown", False, None, None))
        for column in ["Size", "Modified"]:
            for reverse in [False, True]:
                self.assertEqual(sort_entries(self.entries, column, reverse)[-1].name, "unknown")

    def test_sort_does_not_modify_input(self):
        original = list(self.entries)
        sort_entries(self.entries)
        self.assertEqual(self.entries, original)

    def test_unicode_names_and_digit_like_characters_do_not_break_sorting(self):
        entries = [FileEntry(name, name, False, 1, 1) for name in ["²", "file10", "file2", "２"]]
        ordered = sort_entries(entries)
        self.assertEqual(len(ordered), 4)
        self.assertLess([entry.name for entry in ordered].index("file2"),
                        [entry.name for entry in ordered].index("file10"))


if __name__ == "__main__":
    unittest.main()
