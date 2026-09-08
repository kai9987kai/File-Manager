# File Manager

A tabbed Python/Tk desktop file manager with background search, file previews, and recoverable deletion.

## Run

Requires **Python 3.10+**, Tk, and a desktop session. Windows is the primary development platform; macOS and Linux use their system file opener and trash service.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open a specific folder:

```powershell
.\.venv\Scripts\python.exe main.py "C:\Users\YourName\Downloads"
```

On macOS or Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`. Linux installations may also need the distribution's Tk package, such as `python3-tk`.

Pillow enables image previews. Send2Trash enables Trash / Recycle Bin actions. Without Send2Trash, deletion reports an error and leaves the item in place.

## Features

- **Navigation:** multiple tabs, Back/Forward history, parent-folder button, clickable breadcrumbs, and an editable address bar supporting relative paths, home expansion, and environment variables.
- **Quick access:** common home folders, saved favorites, and the 20 most recent folders.
- **Search:** case-insensitive name fragments, wildcard patterns such as `*.pdf`, or regular expressions. Enable **Subfolders** for recursive search and **Hidden** for dotfiles and Windows hidden items.
- **Responsive listings:** folders and files arrive in bounded background batches. Stop cancels the current scan; old scan results cannot replace a newer folder listing. Inaccessible items are reported in Activity.
- **Sorting:** natural names (`file2` before `file10`), numeric file sizes, modification dates, types, and recursive result locations. Folders stay first.
- **File actions:** multi-selection copy/cut/paste, new folders, rename, properties, and confirmed Trash / Recycle Bin actions from buttons, shortcuts, or the right-click menu.
- **Previews:** selectable text up to 32 KB and scaled image previews. Image previews are limited to 32 MB and 40 megapixels. Background readers have bounded queues; stalled reads do not prevent process exit.
- **File sizes:** a chart of the largest regular files in the current results, with explicit totals and zero-byte states. Folder contents and link targets are excluded; this is not a whole-disk usage scanner.
- **Preferences:** Light, Dark, and Midnight themes, favorites, recent folders, and hidden-file preference survive restarts.
- **Command palette:** search actions, favorites, and recent folders with `Ctrl+P`.

Navigation to a new folder clears the current search and the Subfolders toggle. Refresh retains the active filter and selection when the selected paths remain present.

## File-operation behavior

Copy and move use the current folder as their destination. Existing names are reported as conflicts; the app does not overwrite or merge them. Failed batch items are reported individually, and successful cut items are removed from the internal clipboard.

Trash uses the operating system's Trash / Recycle Bin, where supported by the selected volume. There is no permanent-delete fallback in the interface. Use the system trash to restore items. File operations continue if their originating tab is closed; the app waits for operations to finish before allowing the window to close.

Transfers reject symlinks, junctions, linked parent paths, and folders containing links. Recursive search lists links without following them into other directories. Operations on filesystem roots are rejected. A failed directory copy can leave a partial destination folder; its source is retained. Cross-volume moves remove the source only after copying succeeds. Files changing in another application during a transfer are not snapshotted.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+T / Ctrl+W | New / close tab |
| Ctrl+L / Ctrl+F | Address / search |
| Alt+Left / Alt+Right | Back / forward |
| Alt+Up | Parent folder |
| F5 | Refresh |
| Ctrl+H | Toggle hidden items |
| Ctrl+P | Command palette |
| Ctrl+Shift+N | New folder |
| Ctrl+A | Select all in the file list |
| Ctrl+C / Ctrl+X / Ctrl+V | Copy / cut / paste in the file list |
| F2 | Rename selected item |
| Delete | Move selection to Trash / Recycle Bin |
| Enter | Open selected item |
| Escape in search | Clear search |

File-list shortcuts leave normal text-editing shortcuts available in the address, search, and preview fields.

## Preferences

Preferences are written through a temporary file and atomic replacement. Malformed preferences fall back to defaults with a logged warning. Clipboard contents and session tags are never persisted.

| Platform | Default file |
| --- | --- |
| Windows | `%APPDATA%\FileManager\state.json` |
| macOS | `~/Library/Application Support/FileManager/state.json` |
| Linux | `$XDG_CONFIG_HOME/file-manager/state.json`, or `~/.config/file-manager/state.json` |

Set `FILE_MANAGER_STATE_PATH` to use a separate preferences file, useful for portable runs or testing.

## Development and validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app main.py
git diff --check
```

Tests use temporary fixtures and cover collisions, failed copies, links, concurrent operations, scanner cancellation and backpressure, preferences corruption, preview limits, worker shutdown, and real Tk workflows. Trash is mocked in tests so the system recycle bin is not changed. Tk integration tests require a display; headless Linux can run them with `xvfb-run -a python -m unittest discover -s tests -v`.

GitHub Actions is configured for Windows and Linux with Python 3.10 and 3.12.

## Layout

- `main.py` — current entry point.
- `app/core/` — filesystem engine, background scanner/readers, and state.
- `app/ui/` — main window, tabs, palette, previews, and chart.
- `tests/` — unit and Tk integration tests.
- `original.py` and `experimental- mini version.py` — historical prototypes; the features and safeguards above apply to the current `main.py` application.

Licensed under GPL-3.0; see [LICENSE](LICENSE).
