"""Exercise the shipped runtime using disposable files and real Tk widgets.

This intentionally lives in the application so both portable and installed
executables can verify their bundled Tcl/Tk, Pillow and Send2Trash dependencies.
No fixture is sent to the system recycle bin, and preferences are isolated.
"""

from contextlib import contextmanager
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback


@contextmanager
def _replace_attribute(owner, name, value):
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


def _write_report(path, report):
    """Write a complete receipt or preserve the previous receipt on failure."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _exercise_fixture(base, report):
    # Imports remain inside the protected runner: missing bundle dependencies
    # become a JSON failure, even in windowed executables without stderr.
    import tkinter as tk
    from tkinter import messagebox
    from PIL import Image
    import send2trash

    from app.core.state import AppState
    from app.ui.main_window import MainWindow

    files = base / "files"
    files.mkdir()
    documents = files / "documents"
    destination = files / "destination"
    documents.mkdir()
    destination.mkdir()
    sample = files / "sample.txt"
    sample.write_text("File Manager packaging smoke fixture.\n", encoding="utf-8")
    (documents / "nested.txt").write_text("Nested fixture", encoding="utf-8")
    picture = files / "preview.png"
    with Image.new("RGB", (24, 16), color=(30, 140, 210)) as fixture_image:
        fixture_image.save(picture)

    root = tab = second = None
    workers = []
    previous_state = AppState._instance
    AppState._instance = None

    def check(name, condition, message):
        if not condition:
            raise AssertionError(f"{name}: {message}")
        report["checks"].append(name)

    def pump(predicate, label, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            if report["errors"]:
                raise RuntimeError(f"Tk reported an error during {label}")
            if predicate():
                return
            time.sleep(0.01)
        raise TimeoutError(f"Timed out waiting for {label}")

    def idle(current):
        pump(lambda: not root._jobs and not current._scanning
             and current._navigation_future is None, "directory scan")
        if current.scanner is not None:
            workers.append(current.scanner)

    def callback_error(kind, value, trace):
        report["errors"].append("".join(traceback.format_exception(kind, value, trace)))

    def unexpected_dialog(*args, **kwargs):
        report["errors"].append(f"Unexpected modal dialog: {args!r} {kwargs!r}")
        return "cancel"

    try:
        with _replace_attribute(messagebox, "_show", unexpected_dialog):
            # Retain a partially initialized window for cleanup if a bundled
            # runtime resource is missing during MainWindow.__init__.
            root = MainWindow.__new__(MainWindow)
            MainWindow.__init__(root, str(files))
            root.withdraw()
            root.report_callback_exception = callback_error
            tab = root.get_active_tab()
            idle(tab)
            names = {entry.name for entry in tab._items.values()}
            check("tk_directory_scan", names == {"documents", "destination", "sample.txt", "preview.png"},
                  f"Unexpected file entries: {sorted(names)}")

            tab.update_preview(str(sample))
            pump(lambda: tab._preview_future is None, "text preview")
            check("text_preview", "packaging smoke fixture" in tab.preview_text.get("1.0", "end"),
                  "Text contents did not reach the preview widget")
            tab.update_preview(str(picture))
            pump(lambda: tab._preview_future is None, "Pillow preview")
            check("pillow_tk_image_preview", tab._image is not None and tab.tk_img is not None,
                  "Pillow image did not become a native Tk image")

            copied = Path(root.engine.submit_task(root.engine.copy, sample, destination).result(timeout=8))
            check("engine_copy", copied.read_bytes() == sample.read_bytes(), "Copy contents changed")
            moved = Path(root.engine.submit_task(root.engine.move, copied, documents).result(timeout=8))
            check("engine_move", moved.exists() and not copied.exists(), "Move did not complete")
            renamed = Path(root.engine.submit_task(root.engine.rename, moved, documents / "renamed.txt").result(timeout=8))
            check("engine_rename", renamed.read_bytes() == sample.read_bytes() and not moved.exists(),
                  "Rename did not preserve contents")

            check("send2trash_dependency", callable(send2trash.send2trash), "Send2Trash is unavailable")
            trash_calls = []

            def fake_trash(path):
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(files.resolve()):
                    raise AssertionError("Trash probe escaped the temporary fixture")
                trash_calls.append(resolved)

            with _replace_attribute(send2trash, "send2trash", fake_trash):
                # Keep mock dispatch synchronous: a timed-out worker must never
                # resume after this patch is restored and call the real bin.
                root.engine.delete(renamed)
            check("mocked_recycle_bin_dispatch", trash_calls == [renamed.resolve()] and renamed.exists(),
                  "Trash probe did not use the harmless mock")

            tab.navigate_to(str(documents))
            idle(tab)
            check("folder_navigation", tab.directory == str(documents), "Navigation did not finish")
            tab.go_back()
            idle(tab)
            check("back_navigation", tab.directory == str(files), "Back history did not restore the folder")
            tab.go_forward()
            idle(tab)
            check("forward_navigation", tab.directory == str(documents), "Forward history did not restore the folder")

            root.state.current_theme = "Dark"
            root.state.add_favorite(str(documents))
            check("isolated_preferences_path", root.state.state_path == base / "settings.json",
                  "Preferences were not isolated")
            check("preferences_save", root.state.save(), "Preferences could not be saved")
            root.state.current_theme = "Light"
            root.state.favorites = []
            check("preferences_reload", root.state.load() and root.state.current_theme == "Dark"
                  and str(documents) in root.state.favorites, "Saved preferences did not round-trip")

            second = root.new_tab(str(destination))
            idle(second)
            root.close_current_tab()
            check("tab_cleanup", second._closed and not second.winfo_exists()
                  and root.get_active_tab() is tab, "Closing a tab left native widgets or lost the original tab")
            root.update()
            check("tk_callbacks", not report["errors"], "Tk callback errors occurred")
    finally:
        if root is not None:
            # Stop workers before allowing cyclic collection to run again.
            # Otherwise a reader thread can collect Tcl objects off-thread.
            for name in ("preview_executor", "navigation_executor", "engine"):
                executor = getattr(root, name, None)
                if executor is not None:
                    executor.shutdown(wait=False)
                    workers.extend(getattr(executor, "_threads", ()))
                    workers.extend(getattr(getattr(executor, "executor", None), "_threads", ()))
            for current in (tab, second):
                scanner = getattr(current, "scanner", None)
                if scanner is not None:
                    scanner.stop()
                    workers.append(scanner)
            try:
                if hasattr(root, "_closing") and hasattr(root, "notebook"):
                    root.destroy()
                elif hasattr(root, "tk"):
                    tk.Tk.destroy(root)
            except Exception as error:
                report["errors"].append(f"Tk cleanup failed: {error}")
            root.__dict__.pop("report_callback_exception", None)
        for worker in set(workers):
            worker.join(timeout=2)
            if worker.is_alive():
                report["errors"].append(f"Background worker did not stop: {worker.name}")
        AppState._instance = previous_state
        root = tab = second = None


def run_smoke_test(report_path):
    """Return 0/1 and atomically write a JSON receipt to the supplied location."""
    report = {
        "passed": False, "checks": [], "errors": [], "version": "unknown",
        "executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False)),
    }
    previous_override = os.environ.get("FILE_MANAGER_STATE_PATH")
    collection_enabled = gc.isenabled()
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(report_path))))
    gc.collect()
    gc.disable()
    try:
        from app.version import __version__
        report["version"] = __version__
        with tempfile.TemporaryDirectory(prefix="file-manager-smoke-") as temporary:
            base = Path(temporary)
            os.environ["FILE_MANAGER_STATE_PATH"] = str(base / "settings.json")
            _exercise_fixture(base, report)
    except Exception:
        report["errors"].append(traceback.format_exc())
    finally:
        if previous_override is None:
            os.environ.pop("FILE_MANAGER_STATE_PATH", None)
        else:
            os.environ["FILE_MANAGER_STATE_PATH"] = previous_override
        gc.collect()
        if collection_enabled:
            gc.enable()
    report["passed"] = not report["errors"] and bool(report["checks"])
    try:
        _write_report(path, report)
    except Exception:
        if sys.stderr is not None:
            traceback.print_exc()
        return 1
    return 0 if report["passed"] else 1
