import sys
import os

# Ensure app is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.main_window import MainWindow

import logging

# Configure logging
logging.basicConfig(
    filename='app_debug.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filemode='w'
)

if __name__ == "__main__":
    print("Starting app...")
    logging.info("Application starting...")
    try:
        app = MainWindow()
        print("MainWindow created.")
        app.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        logging.critical("Fatal error", exc_info=True)
        input("Press Enter to continue...")
