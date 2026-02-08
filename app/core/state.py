import os

class AppState:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AppState, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.current_theme = "Light"
        self.favorites = []
        self.history = []  # List of visited paths
        self.clipboard = None # For copy/paste operations (path, operation_type)
        self.session_tags = {} # path -> tag

    def add_favorite(self, path):
        if path not in self.favorites:
            self.favorites.append(path)
            # In a real app, save to disk here

    def remove_favorite(self, path):
        if path in self.favorites:
            self.favorites.remove(path)

    def add_to_history(self, path):
        if path and os.path.exists(path):
            # perform simplistic dedup for now: remove if exists, then append to end
            if path in self.history:
                self.history.remove(path)
            self.history.append(path)
            # Keep history manageable
            if len(self.history) > 20:
                self.history.pop(0)

    def get_tag(self, path):
        return self.session_tags.get(path)

    def set_tag(self, path, tag):
        self.session_tags[path] = tag
