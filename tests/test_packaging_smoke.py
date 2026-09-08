"""Packaging receipts and isolated, real-runtime smoke coverage."""

import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.packaging_smoke import _write_report, run_smoke_test


class PackagingSmokeTests(unittest.TestCase):
    def test_failure_writes_receipt_and_restores_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "failure.json"
            original_gc_state = gc.isenabled()
            with patch.dict(os.environ, {"FILE_MANAGER_STATE_PATH": "existing-override.json"}):
                with patch("app.packaging_smoke._exercise_fixture", side_effect=RuntimeError("fixture failure")):
                    self.assertEqual(run_smoke_test(target), 1)
                self.assertEqual(os.environ["FILE_MANAGER_STATE_PATH"], "existing-override.json")
            receipt = json.loads(target.read_text(encoding="utf-8"))
            self.assertFalse(receipt["passed"])
            self.assertIn("fixture failure", "\n".join(receipt["errors"]))
            self.assertEqual(receipt["executable"], sys.executable)
            self.assertEqual(gc.isenabled(), original_gc_state)

    def test_failed_atomic_replace_preserves_prior_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "receipt.json"
            target.write_text("previous receipt", encoding="utf-8")
            with patch("app.packaging_smoke.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    _write_report(target, {"passed": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "previous receipt")
            self.assertEqual(list(Path(temporary).iterdir()), [target])

    @unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Native Tk display required")
    def test_real_runtime_passes_without_touching_external_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            external_settings = folder / "existing-settings.json"
            external_settings.write_text('{"current_theme": "Midnight"}', encoding="utf-8")
            target = folder / "receipt.json"
            environment = dict(os.environ, FILE_MANAGER_STATE_PATH=str(external_settings))
            result = subprocess.run(
                [sys.executable, "-c", "import sys; from app.packaging_smoke import run_smoke_test; "
                 "raise SystemExit(run_smoke_test(sys.argv[1]))", str(target)],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, text=True, timeout=45,
            )
            receipt = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 0, f"{receipt}\n{result.stderr}")
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["errors"], [])
            self.assertIn("pillow_tk_image_preview", receipt["checks"])
            self.assertIn("mocked_recycle_bin_dispatch", receipt["checks"])
            self.assertIn("tab_cleanup", receipt["checks"])
            self.assertFalse(receipt["frozen"])
            self.assertEqual(external_settings.read_text(encoding="utf-8"), '{"current_theme": "Midnight"}')


if __name__ == "__main__":
    unittest.main()
