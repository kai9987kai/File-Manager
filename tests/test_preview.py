from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.core.preview import PreviewExecutor, load_preview, _open_preview_stream

try:
    from PIL import Image
except ImportError:
    Image = None


class PreviewExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executors = []
        self.releases = []

    def tearDown(self):
        for event in self.releases:
            event.set()
        for executor in self.executors:
            executor.shutdown(wait=True)

    def executor(self, workers=1, pending=1):
        executor = PreviewExecutor(max_workers=workers, max_pending=pending)
        self.executors.append(executor)
        return executor

    def block_worker(self, executor):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def blocked():
            started.set()
            release.wait(10)
            return "finished read"

        future = executor.submit(blocked)
        self.assertTrue(started.wait(2), "Read worker did not start")
        return future, release

    def test_pool_has_fixed_daemon_workers_and_bounds_pending_reads(self):
        executor = self.executor(workers=2, pending=1)
        first, release_first = self.block_worker(executor)
        second, release_second = self.block_worker(executor)
        pending = executor.submit(lambda: "queued")
        rejected = executor.submit(lambda: "must not run")
        self.assertTrue(rejected.done())
        with self.assertRaisesRegex(RuntimeError, "Preview workers are busy"):
            rejected.result()
        self.assertEqual(len(executor._threads), 2)
        self.assertTrue(all(thread.daemon for thread in executor._threads))
        release_first.set()
        release_second.set()
        self.assertEqual(first.result(timeout=2), "finished read")
        self.assertEqual(second.result(timeout=2), "finished read")
        self.assertEqual(pending.result(timeout=2), "queued")

    def test_cancelled_stale_read_frees_capacity_and_never_runs(self):
        executor = self.executor()
        running, release = self.block_worker(executor)
        observed = []
        stale = executor.submit(lambda: observed.append("stale"))
        self.assertTrue(stale.cancel())
        replacement = executor.submit(lambda: observed.append("current"))
        self.assertFalse(replacement.done())
        self.assertFalse(running.cancel())
        release.set()
        replacement.result(timeout=2)
        self.assertEqual(observed, ["current"])

    def test_shutdown_returns_without_waiting_and_cancels_pending_reads(self):
        executor = self.executor()
        running, release = self.block_worker(executor)
        pending = executor.submit(lambda: "must not run")
        started = time.monotonic()
        executor.shutdown(wait=False, cancel_futures=True)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertFalse(running.done())
        self.assertTrue(pending.cancelled())
        with self.assertRaisesRegex(RuntimeError, "after preview shutdown"):
            executor.submit(lambda: None)
        release.set()
        self.assertEqual(running.result(timeout=2), "finished read")

    def test_shutdown_can_drain_queued_reads_when_requested(self):
        executor = self.executor()
        running, release = self.block_worker(executor)
        pending = executor.submit(lambda: "queued")
        executor.shutdown(wait=False, cancel_futures=False)
        release.set()
        executor.shutdown(wait=True, cancel_futures=False)
        self.assertEqual(running.result(), "finished read")
        self.assertEqual(pending.result(), "queued")

    def test_exceptions_are_future_results_and_worker_remains_available(self):
        executor = self.executor()
        failed = executor.submit(lambda: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            failed.result(timeout=2)
        self.assertEqual(executor.submit(lambda number: number + 1, 4).result(timeout=2), 5)

    def test_blocked_read_does_not_keep_subprocess_alive(self):
        script = (
            "import threading\n"
            "from app.core.preview import PreviewExecutor\n"
            "started = threading.Event()\n"
            "def blocked():\n"
            "    started.set()\n"
            "    threading.Event().wait()\n"
            "executor = PreviewExecutor()\n"
            "executor.submit(blocked)\n"
            "assert started.wait(2)\n"
            "executor.shutdown(wait=False)\n"
            "print('shutdown returned')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                timeout=5, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shutdown returned", result.stdout)

    def test_invalid_capacity_is_rejected(self):
        for workers, pending in ((0, 1), (1, 0), (-1, 1), (1, True)):
            with self.subTest(workers=workers, pending=pending):
                with self.assertRaises(ValueError):
                    PreviewExecutor(workers, pending)


class PreviewFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_open_preview_does_not_block_rename_or_deletion(self):
        source = self.root / "preview.txt"
        target = self.root / "renamed.txt"
        source.write_bytes(b"preview content")
        with _open_preview_stream(source) as stream:
            source.rename(target)
            target.unlink()
            self.assertEqual(stream.read(), b"preview content")

    def test_missing_preview_stream_does_not_create_a_file(self):
        path = self.root / "missing.txt"
        with self.assertRaises(OSError):
            _open_preview_stream(path)
        self.assertFalse(path.exists())

    def test_text_limit_exact_boundary_and_truncation(self):
        path = self.root / "large.txt"
        path.write_bytes(b"a" * 32768)
        self.assertEqual(load_preview(path), ("text", "a" * 32768))
        path.write_bytes(b"a" * 32769)
        kind, content = load_preview(path)
        self.assertEqual(kind, "text")
        self.assertTrue(content.startswith("a" * 32768))
        self.assertIn("limited to the first 32 KB", content)

    def test_empty_binary_utf8_bom_and_invalid_utf8_text(self):
        path = self.root / "document.txt"
        path.touch()
        self.assertEqual(load_preview(path), ("text", "Empty file."))
        path.write_bytes(b"text\x00binary")
        self.assertIn("Binary file", load_preview(path)[1])
        path.write_bytes(b"\xef\xbb\xbfhello")
        self.assertEqual(load_preview(path), ("text", "hello"))
        path.write_bytes(b"bad byte: \xff")
        self.assertEqual(load_preview(path), ("text", "bad byte: \ufffd"))

    def test_missing_directory_and_unsupported_file(self):
        self.assertIn("Preview unavailable", load_preview(self.root / "missing.txt")[1])
        self.assertIn("regular file", load_preview(self.root)[1])
        path = self.root / "data.bin"
        path.write_bytes(b"hello")
        self.assertIn("No built-in preview", load_preview(path)[1])

    @unittest.skipIf(Image is None, "Pillow is optional")
    def test_image_is_detached_and_thumbnail_is_bounded(self):
        path = self.root / "image.png"
        with Image.new("RGB", (1400, 700), color="red") as original:
            original.save(path)
        kind, content = load_preview(path)
        self.assertEqual(kind, "image")
        self.assertEqual(content.size, (640, 320))
        self.assertEqual(content.mode, "RGBA")
        path.unlink()  # No open source handle should remain, including on Windows.
        self.assertEqual(content.getpixel((0, 0)), (255, 0, 0, 255))
        content.close()

    @unittest.skipIf(Image is None, "Pillow is optional")
    def test_image_byte_limit_accepts_boundary_and_rejects_larger_file(self):
        path = self.root / "image.png"
        with Image.new("RGB", (2, 2), color="blue") as original:
            original.save(path)
        with path.open("r+b") as stream:
            stream.truncate(32 * 1024 * 1024)
        kind, content = load_preview(path)
        self.assertEqual(kind, "image")
        content.close()
        with path.open("ab") as stream:
            stream.write(b"x")
        self.assertIn("32 MB preview limit", load_preview(path)[1])

    @unittest.skipIf(Image is None, "Pillow is optional")
    def test_large_pixel_count_and_decompression_warning_are_rejected(self):
        path = self.root / "pixels.png"
        # A one-bit PNG keeps the real fixture small while testing its dimensions.
        with Image.new("1", (8001, 5000)) as original:
            original.save(path)
        self.assertIn("40 megapixel", load_preview(path)[1])
        with Image.new("RGB", (3, 3)) as original:
            original.save(path)
        with patch.object(Image, "MAX_IMAGE_PIXELS", 5):
            self.assertIn("Preview unavailable", load_preview(path)[1])

    def test_invalid_image_returns_readable_failure(self):
        path = self.root / "broken.png"
        path.write_bytes(b"not an image")
        kind, content = load_preview(path)
        self.assertEqual(kind, "text")
        self.assertTrue("Preview unavailable" in content or "Install Pillow" in content)


if __name__ == "__main__":
    unittest.main()
