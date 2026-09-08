"""Real Tk integration checks. All filesystem actions use temporary fixtures."""
import os
import gc
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from app.core.scanner import FileEntry
from app.core.state import AppState
from app.ui.main_window import MainWindow
from app.ui.palette import CommandPalette


class FileManagerIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Tk interpreters from preceding test cases must be collected on the
        # main thread before new reader threads can trigger cyclic collection.
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.folder = self.base / "files"
        self.folder.mkdir()
        (self.folder / "documents").mkdir()
        (self.folder / "destination").mkdir()
        (self.folder / "file2.txt").write_text("small", encoding="utf-8")
        (self.folder / "file10.txt").write_text("x" * 2048, encoding="utf-8")
        (self.folder / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (self.folder / "documents" / "nested.txt").write_text("nested", encoding="utf-8")
        self.environment = patch.dict(os.environ, {"FILE_MANAGER_STATE_PATH": str(self.base / "settings.json")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        AppState._instance = None
        try:
            self.root = MainWindow(str(self.folder))
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(self.close_root)
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        self.errors = patch("tkinter.messagebox.showerror").start()
        self.addCleanup(patch.stopall)
        self.tab = self.root.get_active_tab()
        self.wait_idle()

    def close_root(self):
        if not self.root._closing:
            self.root.destroy()
        del self.root.report_callback_exception
        self.root = None
        self.tab = None
        gc.collect()
        AppState._instance = None

    def tearDown(self):
        if hasattr(self, "callback_errors"):
            self.assertEqual(self.callback_errors, [])

    def pump(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail("Timed out waiting for Tk background work")

    def wait_idle(self):
        self.pump(lambda: not self.root._jobs and not self.tab._scanning and self.tab._navigation_future is None)

    def select(self, *names):
        items = [item for item, entry in self.tab._items.items() if entry.name in names]
        self.assertEqual(len(items), len(names))
        self.tab.tree.selection_set(items)
        self.tab.on_select()

    def names(self):
        return [self.tab._items[item].name for item in self.tab.tree.get_children()]

    def test_navigation_history_tab_titles_search_and_hidden(self):
        self.assertEqual(self.names(), ["destination", "documents", "file2.txt", "file10.txt"])
        self.select("documents")
        self.tab.open_selected()
        self.wait_idle()
        self.assertEqual(self.tab.directory, str(self.folder / "documents"))
        self.assertEqual(self.root.notebook.tab(self.tab, "text"), "documents")
        self.tab.go_back()
        self.wait_idle()
        self.assertEqual(self.tab.directory, str(self.folder))
        self.tab.go_forward()
        self.wait_idle()
        self.assertEqual(self.names(), ["nested.txt"])
        self.tab.go_up()
        self.wait_idle()
        self.tab.toggle_hidden()
        self.wait_idle()
        self.assertIn(".hidden.txt", self.names())
        self.tab.filter_var.set("nested")
        self.tab.recursive.set(True)
        self.tab.refresh()
        self.wait_idle()
        self.assertEqual(self.names(), ["nested.txt"])
        self.assertEqual(self.tab.tree.item(self.tab.tree.get_children()[0], "values")[-1], "documents")

    def test_invalid_regex_and_old_scan_events(self):
        self.tab.filter_var.set("[")
        self.tab.use_regex.set(True)
        self.tab.refresh()
        self.wait_idle()
        self.assertIn("Invalid regular expression", self.tab.status.msg_label["text"])
        self.tab.use_regex.set(False)
        self.tab.filter_var.set("")
        self.tab.refresh()
        self.tab.scan_queue.put({"type": "batch", "scan_id": self.tab._scan_id - 1,
            "entries": [FileEntry(str(self.folder / "stale"), "stale", False, 1, 0)]})
        self.wait_idle()
        self.assertNotIn("stale", self.names())

    def test_copy_conflict_move_and_create_rename(self):
        self.select("file2.txt")
        self.tab.copy_selected()
        self.tab.navigate_to(str(self.folder / "destination"))
        self.wait_idle()
        self.tab.paste()
        self.wait_idle()
        copied = self.folder / "destination" / "file2.txt"
        self.assertEqual(copied.read_text(), "small")
        self.tab.paste()
        self.wait_idle()
        self.errors.assert_called_once()
        self.assertEqual(copied.read_text(), "small")
        self.select("file2.txt")
        self.tab.cut_selected()
        self.tab.navigate_to(str(self.folder / "documents"))
        self.wait_idle()
        self.tab.paste()
        self.wait_idle()
        self.assertFalse(copied.exists())
        self.assertEqual((self.folder / "documents" / "file2.txt").read_text(), "small")
        self.assertIsNone(self.root.state.clipboard)
        with patch("tkinter.simpledialog.askstring", return_value="New folder"):
            self.tab.create_folder()
        self.wait_idle()
        self.select("New folder")
        with patch("tkinter.simpledialog.askstring", return_value="Renamed"):
            self.tab.rename_selected()
        self.wait_idle()
        self.assertTrue((self.folder / "documents" / "Renamed").is_dir())

    def test_trash_confirmation_and_completion_refresh(self):
        import types
        import sys
        trashed = []

        def fake_trash(path):
            trashed.append(path)
            Path(path).rename(self.base / "trashed-fixture.txt")

        self.select("file2.txt")
        with patch("tkinter.messagebox.askyesno", return_value=False):
            self.tab.delete_selected()
        self.assertTrue((self.folder / "file2.txt").exists())
        with patch("tkinter.messagebox.askyesno", return_value=True), patch.dict(sys.modules, {"send2trash": types.SimpleNamespace(send2trash=fake_trash)}):
            self.tab.delete_selected()
            self.wait_idle()
        self.assertEqual(trashed, [str(self.folder / "file2.txt")])
        self.assertNotIn("file2.txt", self.names())

    def test_recursive_selection_collapses_parent_and_child(self):
        self.tab.recursive.set(True)
        self.tab.refresh()
        self.wait_idle()
        self.select("documents", "nested.txt")
        self.assertEqual(self.tab._operation_paths(), [str(self.folder / "documents")])

    def test_metadata_sorting_previews_and_stale_preview(self):
        self.tab.sort_column("Size")
        self.assertEqual(self.names()[-2:], ["file2.txt", "file10.txt"])
        self.tab.sort_column("Size")
        self.assertEqual(self.names()[-2:], ["file10.txt", "file2.txt"])
        self.select("file2.txt")
        self.pump(lambda: self.tab._preview_future is None)
        self.assertIn("small", self.tab.preview_text.get("1.0", "end"))
        old, new = Future(), Future()
        old.set_running_or_notify_cancel()
        with patch.object(self.root.preview_executor, "submit", side_effect=[old, new]):
            self.tab.update_preview(str(self.folder / "file2.txt"))
            self.tab.update_preview(str(self.folder / "file10.txt"))
        old.set_result(("text", "stale preview"))
        new.set_result(("text", "new preview"))
        self.pump(lambda: self.tab._preview_future is None)
        self.assertIn("new preview", self.tab.preview_text.get("1.0", "end"))

    def test_favorites_palette_and_tab_cleanup(self):
        self.tab.toggle_favorite()
        self.assertIn(str(self.folder), self.root.state.favorites)
        if os.name == "nt":
            self.tab.navigate_to(str(self.folder).upper())
            self.wait_idle()
            self.assertEqual(self.tab.favorite_button["text"], "★ Favorited")
        self.tab.toggle_favorite()
        self.assertEqual(self.root.state.favorites, [])
        called = []
        palette = CommandPalette(self.root, lambda: [("First", lambda: called.append(1)), ("Second", lambda: called.append(2))])
        palette.move_selection(1)
        palette.execute()
        self.assertEqual(called, [2])
        original = self.tab
        second = self.root.new_tab(str(self.folder / "documents"))
        self.root.close_current_tab()
        self.assertTrue(second._closed)
        self.assertFalse(second.winfo_exists())
        self.assertIs(self.root.get_active_tab(), original)

    def test_busy_tab_can_close_and_operation_still_finishes(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.tab._run_operation("Fixture operation", ["fixture"], lambda path: release.wait(3))
        self.root.close_current_tab()
        self.assertTrue(self.tab._closed)
        with patch("tkinter.messagebox.showinfo") as info:
            self.root.close_app()
            info.assert_called_once()
        release.set()
        self.pump(lambda: not self.root._jobs)
        self.assertFalse(self.root._closing)

    def test_superseded_navigation_cannot_replace_newer_folder(self):
        old, new = Future(), Future()
        old.set_running_or_notify_cancel()
        with patch.object(self.root.navigation_executor, "submit", side_effect=[old, new]):
            self.tab.navigate_to(str(self.folder / "documents"))
            self.tab.navigate_to(str(self.folder / "destination"))
        old.set_result(True)
        new.set_result(True)
        self.wait_idle()
        self.assertEqual(self.tab.directory, str(self.folder / "destination"))


if __name__ == "__main__":
    unittest.main()
