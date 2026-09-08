import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.state import AppState
from app.ui.visualizer import DiskVisualizer


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.preferences = self.root / "config" / "state.json"
        self.environment = patch.dict(os.environ, {"FILE_MANAGER_STATE_PATH": str(self.preferences)})
        self.environment.start()
        AppState._instance = None

    def tearDown(self):
        AppState._instance = None
        self.environment.stop()
        self.temporary.cleanup()

    def restart(self):
        AppState._instance = None
        return AppState()

    def write_preferences(self, payload):
        self.preferences.parent.mkdir(exist_ok=True)
        self.preferences.write_text(json.dumps(payload), encoding="utf-8")

    def test_preferences_survive_restart_but_session_data_does_not(self):
        state = AppState()
        self.assertIs(state, AppState())
        self.assertEqual(state.current_theme, "Light")
        self.assertFalse(self.preferences.exists())
        favorite = self.root / "Documents"
        favorite.mkdir()
        self.assertTrue(state.add_favorite(favorite))
        self.assertTrue(state.add_to_history(favorite))
        state.current_theme = "Midnight"
        state.show_hidden = True
        state.clipboard = (str(favorite), "copy")
        state.set_tag(str(favorite), "Blue")
        self.assertTrue(state.save())

        restored = self.restart()
        self.assertEqual(restored.state_path, self.preferences)
        self.assertEqual(restored.favorites, [str(favorite)])
        self.assertEqual(restored.history, [str(favorite)])
        self.assertEqual(restored.current_theme, "Midnight")
        self.assertTrue(restored.show_hidden)
        self.assertIsNone(restored.clipboard)
        self.assertEqual(restored.session_tags, {})
        self.assertNotIn("clipboard", json.loads(self.preferences.read_text(encoding="utf-8")))

    def test_favorites_validate_normalize_deduplicate_and_remove(self):
        state = AppState()
        favorite = self.root / "Documents"
        favorite.mkdir()
        file_path = self.root / "file.txt"
        file_path.touch()
        self.assertFalse(state.add_favorite(file_path))
        self.assertFalse(state.add_favorite(self.root / "missing"))
        for invalid in (None, 4, "", "\x00", b"bytes"):
            self.assertFalse(state.add_favorite(invalid))
        self.assertTrue(state.add_favorite(favorite))
        self.assertFalse(state.add_favorite(str(favorite) + os.sep + "."))
        self.assertEqual(state.favorites, [str(favorite)])
        self.assertTrue(state.remove_favorite(str(favorite) + os.sep + "."))
        self.assertEqual(self.restart().favorites, [])

    def test_history_is_bounded_and_revisits_move_to_end(self):
        state = AppState()
        directories = []
        for index in range(24):
            directory = self.root / str(index)
            directory.mkdir()
            directories.append(str(directory))
            state.add_to_history(directory)
        self.assertEqual(state.history, directories[-20:])
        state.add_to_history(directories[-5])
        self.assertEqual(state.history[-1], directories[-5])
        self.assertEqual(len(state.history), 20)
        self.assertEqual(len(set(state.history)), 20)
        self.assertEqual(self.restart().history, state.history)

    def test_corrupt_json_keeps_defaults_and_warns(self):
        self.preferences.parent.mkdir()
        self.preferences.write_text('{"favorites":', encoding="utf-8")
        with self.assertLogs("app.core.state", level="WARNING"):
            state = AppState()
        self.assertEqual(state.favorites, [])
        self.assertEqual(state.current_theme, "Light")
        # Reading a corrupt file does not overwrite evidence of the problem.
        self.assertEqual(self.preferences.read_text(encoding="utf-8"), '{"favorites":')

    def test_invalid_structures_do_not_partially_replace_live_preferences(self):
        state = AppState()
        state.current_theme = "Dark"
        for payload in (
            [], {"version": True}, {"version": 2}, {"current_theme": []},
            {"current_theme": "unknown"}, {"show_hidden": "false"},
            {"favorites": "not a list"}, {"favorites": [7]},
            {"favorites": ["relative/path"]}, {"favorites": [str(self.root) + "\x00"]},
            {"history": [None]},
        ):
            with self.subTest(payload=payload):
                self.write_preferences(payload)
                with self.assertLogs("app.core.state", level="WARNING"):
                    self.assertFalse(state.load())
                self.assertEqual(state.current_theme, "Dark")
                self.assertEqual(state.favorites, [])

    def test_saved_history_is_deduplicated_and_bounded_and_offline_favorites_remain(self):
        paths = [str(self.root / str(index)) for index in range(30)]
        self.write_preferences({"favorites": [paths[0]], "history": paths + [paths[20]]})
        state = AppState()
        self.assertEqual(state.favorites, [paths[0]])
        self.assertEqual(len(state.history), 20)
        self.assertEqual(state.history[-1], paths[20])
        self.assertEqual(len(set(state.history)), 20)

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(self):
        state = AppState()
        self.assertTrue(state.save())
        original = self.preferences.read_bytes()
        state.current_theme = "Dark"
        with patch("app.core.state.os.replace", side_effect=PermissionError("file locked")):
            with self.assertLogs("app.core.state", level="WARNING"):
                self.assertFalse(state.save())
        self.assertEqual(self.preferences.read_bytes(), original)
        self.assertEqual(list(self.preferences.parent.iterdir()), [self.preferences])
        self.assertEqual(self.restart().current_theme, "Light")

    def test_invalid_live_state_does_not_replace_preferences(self):
        state = AppState()
        self.assertTrue(state.save())
        original = self.preferences.read_bytes()
        state.show_hidden = "yes"
        with self.assertLogs("app.core.state", level="WARNING"):
            self.assertFalse(state.save())
        self.assertEqual(self.preferences.read_bytes(), original)


class VisualizerMetadataTests(unittest.TestCase):
    def chart(self):
        # These operations need no Tcl window, only the metadata cache.
        chart = object.__new__(DiskVisualizer)
        chart.draw = Mock()
        chart.path = "old-path"
        chart.data_cache = None
        return chart

    def entry(self, name, size, **kwargs):
        return SimpleNamespace(name=name, size=size, path=name, is_dir=kwargs.get("is_dir", False),
                               is_link=kwargs.get("is_link", False))

    def test_chart_uses_only_supplied_regular_file_metadata(self):
        chart = self.chart()
        entries = [self.entry("small", 3), self.entry("big", 10), self.entry("empty", 0),
                   self.entry("folder", 10000, is_dir=True),
                   self.entry("link", 10000, is_link=True)]
        with patch("os.scandir", side_effect=AssertionError("Unexpected filesystem scan")):
            with patch("os.stat", side_effect=AssertionError("Unexpected filesystem stat")):
                chart.set_entries(entries)
                chart.refresh()
        self.assertEqual(chart.data_cache["total"], 13)
        self.assertEqual([item["name"] for item in chart.data_cache["items"]], ["big", "small", "empty"])
        self.assertEqual(chart.data_cache["excluded"], 2)

    def test_zero_byte_files_and_empty_listings_are_distinguishable(self):
        chart = self.chart()
        chart.set_entries([self.entry("empty", 0)])
        self.assertEqual(chart.data_cache["total"], 0)
        self.assertEqual(len(chart.data_cache["items"]), 1)
        chart.set_entries([])
        self.assertEqual(chart.data_cache["items"], [])

    def test_navigation_clears_previous_chart_immediately(self):
        chart = self.chart()
        chart.set_entries([self.entry("old", 100)])
        chart.update_path("new-path")
        self.assertEqual(chart.path, "new-path")
        self.assertIsNone(chart.data_cache)
        chart.draw.assert_called()


if __name__ == "__main__":
    unittest.main()
