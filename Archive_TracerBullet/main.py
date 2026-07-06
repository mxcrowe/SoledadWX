#!/usr/bin/env python3
"""
CumulusAI - Desktop Weather Station Application

Main entry point for the application.
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main application entry point."""
    try:
        from PyQt6.QtWidgets import QApplication
        from cumulusai.gui.main_window import MainWindow

        app = QApplication(sys.argv)

        # Set application metadata
        app.setApplicationName("CumulusAI")
        app.setApplicationVersion("0.1.0")

        # Create and show main window
        window = MainWindow()
        window.show()

        logger.info("CumulusAI application started")
        sys.exit(app.exec())

    except ImportError as e:
        logger.error(f"Missing required dependencies: {e}")
        print("Error: Missing required dependencies.")
        print("Please install dependencies using: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
