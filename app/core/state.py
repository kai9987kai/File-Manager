"""Session state and durable, user-local preferences."""

import json
import logging
import os
from pathlib import Path
import sys
import tempfile


logger = logging.getLogger(__name__)


class AppState:
    _instance = None
    HISTORY_LIMIT = 20
    _THEMES = frozenset({"Light", "Dark", "Midnight"})

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.current_theme = "Light"
        self.show_hidden = False
        self.favorites = []
        self.history = []
        self.clipboard = None  # Session-only (path, operation_type).
        self.session_tags = {}  # Session-only path -> tag.
        self.state_path = self._preferences_path()
        self.load()

    @staticmethod
    def _preferences_path():
        override = os.environ.get("FILE_MANAGER_STATE_PATH")
        if override:
            return Path(os.path.abspath(os.path.expanduser(override)))
        if sys.platform == "win32":
            root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
            return root / "FileManager" / "state.json"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "FileManager" / "state.json"
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return root / "file-manager" / "state.json"

    @staticmethod
    def _normalize_path(path):
        try:
            path = os.fspath(path)
        except TypeError:
            return None
        if not isinstance(path, str) or not path.strip() or "\x00" in path:
            return None
        try:
            return os.path.normpath(os.path.abspath(os.path.expanduser(path)))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _same_path(left, right):
        return os.path.normcase(left) == os.path.normcase(right)

    @classmethod
    def _path_list(cls, values):
        if not isinstance(values, list):
            raise ValueError("Saved paths must be lists")
        result = []
        for value in values:
            # Relative paths change meaning with the launch directory.
            if not isinstance(value, str) or not os.path.isabs(value):
                raise ValueError("Saved paths must be absolute path strings")
            path = cls._normalize_path(value)
            if path is None:
                raise ValueError("Invalid saved path")
            result = [old for old in result if not cls._same_path(old, path)]
            result.append(path)
        return result

    def load(self):
        """Load validated preferences; keep current values if reading fails.

        Missing directories are retained because removable drives and network
        shares can be temporarily unavailable. Clipboard and tags never load.
        """
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("Preferences must be a JSON object")
            if type(payload.get("version", 1)) is not int or payload.get("version", 1) != 1:
                raise ValueError("Unsupported preferences version")
            theme = payload.get("current_theme", "Light")
            if not isinstance(theme, str) or theme not in self._THEMES:
                raise ValueError("Unknown theme")
            show_hidden = payload.get("show_hidden", False)
            if type(show_hidden) is not bool:
                raise ValueError("show_hidden must be a boolean")
            favorites = self._path_list(payload.get("favorites", []))
            history = self._path_list(payload.get("history", []))[-self.HISTORY_LIMIT:]
        except FileNotFoundError:
            return False
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            logger.warning("Could not load preferences from %s: %s", self.state_path, exc)
            return False
        self.current_theme = theme
        self.show_hidden = show_hidden
        self.favorites = favorites
        self.history = history
        return True

    def save(self):
        """Replace preferences atomically, leaving the previous file on failure."""
        temporary_path = None
        try:
            if self.current_theme not in self._THEMES or type(self.show_hidden) is not bool:
                raise ValueError("Invalid theme or hidden-file preference")
            payload = {
                "version": 1,
                "current_theme": self.current_theme,
                "show_hidden": self.show_hidden,
                "favorites": self._path_list(self.favorites),
                "history": self._path_list(self.history)[-self.HISTORY_LIMIT:],
            }
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            # A sibling temporary file keeps os.replace on the same volume.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.state_path)
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not save preferences to %s: %s", self.state_path, exc)
            return False
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def add_favorite(self, path):
        path = self._normalize_path(path)
        if path is None or not os.path.isdir(path):
            return False
        if any(self._same_path(path, favorite) for favorite in self.favorites):
            return False
        self.favorites.append(path)
        self.save()
        return True

    def remove_favorite(self, path):
        path = self._normalize_path(path)
        if path is None:
            return False
        remaining = [favorite for favorite in self.favorites if not self._same_path(favorite, path)]
        if remaining == self.favorites:
            return False
        self.favorites = remaining
        self.save()
        return True

    def add_to_history(self, path, *, validated=False):
        path = self._normalize_path(path)
        if path is None or (not validated and not os.path.isdir(path)):
            return False
        self.history = [old for old in self.history if not self._same_path(old, path)]
        self.history.append(path)
        self.history = self.history[-self.HISTORY_LIMIT:]
        self.save()
        return True

    def get_tag(self, path):
        return self.session_tags.get(path)

    def set_tag(self, path, tag):
        self.session_tags[path] = tag
