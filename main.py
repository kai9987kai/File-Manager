"""Launch the desktop file manager."""
import argparse
import logging
import os
import sys

from app.version import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description="Browse and manage files in a tabbed desktop app.")
    parser.add_argument("directory", nargs="?", default=None, help="Initial folder (home folder in the Windows app; current directory from Python)")
    parser.add_argument("--version", action="version", version=f"File Manager {__version__}")
    parser.add_argument("--smoke-test", metavar="REPORT", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.smoke_test:
        from app.packaging_smoke import run_smoke_test
        return run_smoke_test(args.smoke_test)
    from app.ui.main_window import MainWindow
    initial = args.directory or (os.path.expanduser("~") if getattr(sys, "frozen", False) else os.getcwd())
    directory = os.path.abspath(os.path.expanduser(initial))
    if not os.path.isdir(directory):
        parser.error(f"Folder not found: {directory}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    app = MainWindow(directory)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
