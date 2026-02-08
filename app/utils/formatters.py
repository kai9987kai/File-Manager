def human_readable_size(size, dec_places=1):
    """
    Convert a file size in bytes to a human-readable string (e.g., 1.5 MB).
    """
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024:
            return f"{size:.{dec_places}f} {unit}"
        size /= 1024
    return f"{size:.{dec_places}f} PB"

def truncate_path(path, max_length=50):
    """
    Truncate a long path for display, preserving the end.
    Example: C:/Users/.../Documents/file.txt
    """
    if len(path) <= max_length:
        return path
    drive, tail = path[:3], path[-max_length+3:]
    return f"{drive}...{tail}"
