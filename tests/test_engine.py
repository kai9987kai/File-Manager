import errno
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock

from app.core.engine import Engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.txt"
        self.source.write_text("keep this content", encoding="utf-8")
        self.destination = self.root / "destination"
        self.destination.mkdir()
        self.engine = Engine()

    def tearDown(self):
        self.engine.shutdown(wait=True)
        self.temporary.cleanup()

    def test_copy_preserves_source_and_returns_actual_target(self):
        target = self.engine.copy(self.source, self.destination)
        self.assertEqual(target, str(self.destination / self.source.name))
        self.assertEqual(Path(target).read_bytes(), self.source.read_bytes())

    def test_copy_and_move_refuse_existing_files_without_changing_either(self):
        target = self.destination / self.source.name
        target.write_text("destination content", encoding="utf-8")
        for operation in [self.engine.copy, self.engine.move]:
            with self.subTest(operation=operation.__name__), self.assertRaises(FileExistsError):
                operation(self.source, self.destination)
            self.assertEqual(target.read_text(), "destination content")
            self.assertEqual(self.source.read_text(), "keep this content")

    def test_copy_destination_must_be_directory(self):
        with self.assertRaises(NotADirectoryError):
            self.engine.copy(self.source, self.root / "missing")

    def test_destination_created_after_preflight_is_not_overwritten(self):
        target = self.destination / self.source.name
        original_copy = Engine._copy_file
        def compete(source, destination):
            Path(destination).write_text("another writer")
            return original_copy(source, destination)
        with mock.patch.object(Engine, "_copy_file", side_effect=compete):
            with self.assertRaises(FileExistsError):
                self.engine.copy(self.source, self.destination)
        self.assertEqual(target.read_text(), "another writer")
        self.assertEqual(self.source.read_text(), "keep this content")

    def test_failed_file_copy_removes_its_partial_target_and_preserves_source(self):
        def fail_after_partial_write(reader, writer, **kwargs):
            writer.write(b"partial")
            raise OSError("simulated full disk")
        with mock.patch("app.core.engine.shutil.copyfileobj", side_effect=fail_after_partial_write):
            with self.assertRaisesRegex(OSError, "simulated full disk"):
                self.engine.copy(self.source, self.destination)
        self.assertFalse((self.destination / self.source.name).exists())
        self.assertEqual(self.source.read_text(), "keep this content")

    def test_move_removes_source_only_after_success(self):
        target = self.engine.move(self.source, self.destination)
        self.assertFalse(self.source.exists())
        self.assertEqual(Path(target).read_text(), "keep this content")

    def test_cross_device_move(self):
        low_level = "os.rename" if os.name == "nt" else "os.link"
        with mock.patch(f"app.core.engine.{low_level}", side_effect=OSError(errno.EXDEV, "cross device")):
            target = self.engine.move(self.source, self.destination)
        self.assertFalse(self.source.exists())
        self.assertEqual(Path(target).read_text(), "keep this content")

    def test_failed_cross_device_copy_preserves_source(self):
        low_level = "os.rename" if os.name == "nt" else "os.link"
        with mock.patch(f"app.core.engine.{low_level}", side_effect=OSError(errno.EXDEV, "cross device")):
            with mock.patch.object(Engine, "_copy", side_effect=PermissionError("copy failed")):
                with self.assertRaises(PermissionError):
                    self.engine.move(self.source, self.destination)
        self.assertEqual(self.source.read_text(), "keep this content")

    def test_copy_and_move_nested_directory(self):
        folder = self.root / "folder"
        (folder / "nested").mkdir(parents=True)
        (folder / "nested" / "file.txt").write_text("nested content")
        copied = Path(self.engine.copy(folder, self.destination))
        self.assertEqual((copied / "nested" / "file.txt").read_text(), "nested content")
        other = self.root / "other"
        other.mkdir()
        moved = Path(self.engine.move(folder, other))
        self.assertFalse(folder.exists())
        self.assertEqual((moved / "nested" / "file.txt").read_text(), "nested content")

    def test_same_path_and_descendants_are_rejected(self):
        folder = self.root / "folder"
        child = folder / "child"
        child.mkdir(parents=True)
        for operation in [self.engine.copy, self.engine.move]:
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ValueError):
                    operation(self.source, self.root)
                with self.assertRaises(ValueError):
                    operation(folder, child)

    def test_copy_does_not_merge_into_existing_directory(self):
        folder = self.root / "folder"
        folder.mkdir()
        target = self.destination / folder.name
        target.mkdir()
        sentinel = target / "existing.txt"
        sentinel.write_text("preserve me")
        with self.assertRaises(FileExistsError):
            self.engine.copy(folder, self.destination)
        self.assertEqual(sentinel.read_text(), "preserve me")

    def test_rename_rejects_conflicts_and_changes_name(self):
        with self.assertRaises(FileExistsError):
            self.engine.rename(self.source, self.destination)
        target = self.root / "renamed.txt"
        self.assertEqual(self.engine.rename(self.source, target), str(target))
        self.assertFalse(self.source.exists())
        self.assertEqual(target.read_text(), "keep this content")

    def test_create_folder_does_not_silently_accept_existing_path(self):
        target = self.root / "new folder"
        self.assertEqual(self.engine.create_folder(target), str(target))
        with self.assertRaises(FileExistsError):
            self.engine.create_folder(target)

    def test_missing_source_is_an_error_for_all_operations(self):
        missing = self.root / "missing.txt"
        operations = [
            lambda: self.engine.copy(missing, self.destination),
            lambda: self.engine.move(missing, self.destination),
            lambda: self.engine.rename(missing, self.root / "new.txt"),
            lambda: self.engine.delete(missing),
        ]
        for operation in operations:
            with self.assertRaises(FileNotFoundError):
                operation()

    def test_leaf_name_validation(self):
        for name in ["", ".", "..", "../escape", "a/b", "a\\b", "C:escape", "name.", "name ",
                     "name\x00", "CON", "con.txt", "NUL.txt", "COM1.log", "LPT9", "COM\u00b9", "a?b"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.engine.validate_name(name)
        for name in ["file.txt", "new folder", "report 2026.md", "COM10", "\u6587\u4ef6.txt"]:
            self.assertEqual(self.engine.validate_name(name), name)

    def test_default_delete_uses_trash_without_permanent_fallback(self):
        send = mock.Mock()
        with mock.patch.dict("sys.modules", {"send2trash": types.SimpleNamespace(send2trash=send)}):
            self.assertEqual(self.engine.delete(self.source), str(self.source))
        send.assert_called_once_with(str(self.source))
        self.assertTrue(self.source.exists())

    def test_missing_trash_dependency_leaves_file_untouched(self):
        with mock.patch.dict("sys.modules", {"send2trash": None}):
            with self.assertRaisesRegex(RuntimeError, "Nothing was deleted"):
                self.engine.delete(self.source)
        self.assertTrue(self.source.exists())

    def test_trash_failure_does_not_fall_back_to_permanent_delete(self):
        send = mock.Mock(side_effect=PermissionError("cannot trash"))
        with mock.patch.dict("sys.modules", {"send2trash": types.SimpleNamespace(send2trash=send)}):
            with self.assertRaises(PermissionError):
                self.engine.delete(self.source)
        self.assertTrue(self.source.exists())

    def test_explicit_permanent_delete(self):
        self.engine.delete(self.source, permanent=True)
        self.assertFalse(self.source.exists())

    def _symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symbolic links is unavailable on this host")

    def test_broken_destination_link_is_a_conflict(self):
        target = self.destination / self.source.name
        self._symlink(target, self.root / "absent")
        with self.assertRaises(FileExistsError):
            self.engine.copy(self.source, self.destination)
        self.assertTrue(target.is_symlink())

    def test_source_and_nested_links_are_rejected_before_copy(self):
        link = self.root / "link.txt"
        self._symlink(link, self.source)
        with self.assertRaises(ValueError):
            self.engine.copy(link, self.destination)
        folder = self.root / "folder"
        folder.mkdir()
        self._symlink(folder / "nested.txt", self.source)
        with self.assertRaises(ValueError):
            self.engine.copy(folder, self.destination)
        self.assertFalse((self.destination / "folder").exists())

    def test_nested_directory_link_is_rejected_before_move(self):
        folder = self.root / "folder"
        folder.mkdir()
        self._symlink(folder / "linked-folder", self.destination, directory=True)
        with self.assertRaises(ValueError):
            self.engine.move(folder, self.destination)
        self.assertTrue(folder.exists())
        self.assertFalse((self.destination / "folder").exists())

    def test_destination_link_is_rejected(self):
        link = self.root / "linked-destination"
        self._symlink(link, self.destination, directory=True)
        with self.assertRaises(ValueError):
            self.engine.copy(self.source, link)

    def test_concurrent_copies_do_not_overwrite(self):
        futures = [self.engine.submit_task(self.engine.copy, self.source, self.destination) for _ in range(2)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=5))
            except FileExistsError:
                outcomes.append("conflict")
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual((self.destination / self.source.name).read_text(), "keep this content")

    def test_logging_failure_cannot_break_completed_copy(self):
        self.engine.log_callback = mock.Mock(side_effect=RuntimeError("UI closed"))
        target = self.engine.copy(self.source, self.destination)
        self.assertTrue(Path(target).exists())

    def test_shutdown_cancels_queued_tasks_and_rejects_new_submissions(self):
        started = threading.Barrier(5)
        release = threading.Event()
        def blocked():
            started.wait(timeout=5)
            release.wait(timeout=5)
        running = [self.engine.submit_task(blocked) for _ in range(4)]
        started.wait(timeout=5)
        pending = self.engine.submit_task(lambda: "should not run")
        try:
            self.engine.shutdown(wait=False)
            self.assertTrue(pending.cancelled())
            with self.assertRaises(RuntimeError):
                self.engine.submit_task(lambda: None)
        finally:
            release.set()
            for future in running:
                future.result(timeout=5)


if __name__ == "__main__":
    unittest.main()
