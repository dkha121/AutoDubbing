"""Local Video Dubbing Studio — application entry point.

Run with:  python app.py
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.app_config import AppConfig
from core.database import init_db
from core.logger import get_logger, setup_logging


def _apply_theme(app: QApplication, theme: str) -> None:
    """Apply a simple dark palette via stylesheet (light = Qt default)."""
    if theme != "dark":
        return

    # Generate custom SVG icons for black & white high-contrast checkboxes and radio buttons
    import os
    os.makedirs("data/icons", exist_ok=True)
    with open("data/icons/cb_checked_black.svg", "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="black"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>')
    with open("data/icons/rb_checked_white.svg", "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white"><circle cx="12" cy="12" r="5"/></svg>')

    app.setStyleSheet(
        """
        QWidget { background-color: #1a1a1a; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
        QListWidget { background-color: #111111; border: none; padding: 6px; }
        QListWidget::item { padding: 10px 14px; margin-bottom: 4px; border-radius: 5px; color: #aaaaaa; }
        QListWidget::item:hover { background-color: #262626; color: #ffffff; }
        QListWidget::item:selected { background-color: #3a7bd5; color: #ffffff; font-weight: bold; }
        QPushButton { background-color: #333333; border: 1px solid #444444; padding: 6px 12px; border-radius: 5px; color: #ffffff; }
        QPushButton:hover { background-color: #444444; border-color: #555555; }
        QPushButton:pressed { background-color: #222222; }
        QPushButton:disabled { color: #555555; background-color: #1f1f1f; border-color: #2a2a2a; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QTableWidget {
            background-color: #121212; border: 1px solid #333333; padding: 5px; border-radius: 4px; color: #ffffff;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
            border-color: #3a7bd5;
        }
        QGroupBox { border: 1px solid #333333; border-radius: 6px; margin-top: 10px; padding-top: 10px; font-weight: bold; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #3a7bd5; }
        QProgressBar { border: 1px solid #333333; border-radius: 4px; text-align: center; background-color: #121212; color: #ffffff; font-weight: bold; }
        QProgressBar::chunk { background-color: #3a7bd5; border-radius: 3px; }
        QHeaderView::section { background-color: #222222; padding: 4px; border: none; color: #ffffff; }

        /* QCheckBox Custom Styling (Black & White Minimalist) */
        QCheckBox { spacing: 6px; }
        QCheckBox::indicator {
            width: 14px;
            height: 14px;
            border: 1px solid #555555;
            border-radius: 3px;
            background-color: #121212;
        }
        QCheckBox::indicator:hover {
            border-color: #aaaaaa;
        }
        QCheckBox::indicator:checked {
            border: 1px solid #ffffff;
            background-color: #ffffff;
            image: url(data/icons/cb_checked_black.svg);
        }
        QCheckBox::indicator:disabled {
            border-color: #2a2a2a;
            background-color: #1a1a1a;
        }

        /* QRadioButton Custom Styling (Black & White Minimalist) */
        QRadioButton { spacing: 6px; }
        QRadioButton::indicator {
            width: 14px;
            height: 14px;
            border: 1px solid #555555;
            border-radius: 7px;
            background-color: #121212;
        }
        QRadioButton::indicator:hover {
            border-color: #aaaaaa;
        }
        QRadioButton::indicator:checked {
            border: 1px solid #ffffff;
            background-color: #121212;
            image: url(data/icons/rb_checked_white.svg);
        }
        QRadioButton::indicator:disabled {
            border-color: #2a2a2a;
            background-color: #1a1a1a;
        }
        """
    )


def main() -> int:
    setup_logging()
    logger = get_logger("app")
    config = AppConfig.instance()
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Local Video Dubbing Studio")
    _apply_theme(app, config.get("ui.theme", "dark"))

    # Imported here so the app can still start if a UI module has an issue.
    from ui.main_window import MainWindow
    window = MainWindow(config)
    window.show()
    logger.info("Application started")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
