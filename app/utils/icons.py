# In a real app, this would load images/icons. 
# For now, we'll use emoji or text placeholders to keep it valid without external assets.

class Icons:
    FOLDER = "📁"
    FILE = "📄"
    IMAGE = "🖼️"
    VIDEO = "🎬"
    TEXT = "📝" 
    CODE = "💻"
    UNKNOWN = "❓"

    @staticmethod
    def get_icon(filename, is_dir=False):
        if is_dir:
            return Icons.FOLDER
        
        lower_name = filename.lower()
        if lower_name.endswith(('.png', '.jpg', '.jpeg', '.gif')):
            return Icons.IMAGE
        if lower_name.endswith(('.mp4', '.avi', '.mov')):
            return Icons.VIDEO
        if lower_name.endswith(('.txt', '.md', '.log')):
            return Icons.TEXT
        if lower_name.endswith(('.py', '.js', '.html', '.css', '.json')):
            return Icons.CODE
            
        return Icons.FILE
