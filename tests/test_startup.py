import sys
import unittest
from unittest.mock import patch

import main


class StartupTests(unittest.TestCase):
    def test_windowed_argument_error_is_visible_and_returns_exit_two(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "platform", "win32"), \
                patch.object(sys, "stderr", None), patch.object(sys, "argv", ["FileManager.exe"]), \
                patch.object(main, "_show_startup_error") as dialog:
            with self.assertRaises(SystemExit) as raised:
                main.StartupParser().parse_args(["--unknown-argument"])
        self.assertEqual(raised.exception.code, 2)
        dialog.assert_called_once()

    def test_smoke_argument_error_does_not_open_a_blocking_dialog(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "platform", "win32"), \
                patch.object(sys, "stderr", None), patch.object(sys, "argv", ["FileManager.exe", "--smoke-test"]), \
                patch.object(main, "_show_startup_error") as dialog:
            with self.assertRaises(SystemExit):
                main.StartupParser().error("Missing smoke report path")
        dialog.assert_not_called()

    def test_smoke_entry_point_returns_runner_status(self):
        with patch("app.packaging_smoke.run_smoke_test", return_value=1) as run:
            self.assertEqual(main.main(["--smoke-test", "fixture-report.json"]), 1)
        run.assert_called_once_with("fixture-report.json")
