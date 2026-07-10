"""Main application window with sidebar navigation and a docked log panel."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QListWidget, QListWidgetItem, QMainWindow,
    QStackedWidget, QStatusBar, QWidget,
)

from core.app_config import AppConfig
from core.constants import APP_NAME, APP_VERSION
from core.logger import get_logger
from ui.app_state import AppState
from ui.auto_dubbing_page import AutoDubbingPage
from ui.blur_editor_page import BlurEditorPage
from ui.batch_queue_page import BatchQueuePage
from ui.import_page import ImportPage
from ui.render_page import RenderPage
from ui.settings_page import SettingsPage
from ui.subtitle_editor_page import SubtitleEditorPage
from ui.transcribe_page import TranscribePage
from ui.translation_page import TranslationPage
from ui.tts_page import TTSPage
from ui.widgets.log_panel import LogPanel

logger = get_logger(__name__)

_NAV = [
    "Auto Dubbing", "Settings",
]


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.state = AppState()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 800)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        for name in _NAV:
            self.nav.addItem(QListWidgetItem(name))
        layout.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.pages = {
            "Auto Dubbing": AutoDubbingPage(self.state),
            "Settings": SettingsPage(self.config),
        }
        for name in _NAV:
            self.stack.addWidget(self.pages[name])
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # Log dock
        self.log_panel = LogPanel()
        dock = QDockWidget("Logs")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        self.setStatusBar(QStatusBar())
        self.state.project_changed.connect(
            lambda p: self.statusBar().showMessage(f"Project: {p.name} ({p.id})")
        )
        logger.info("%s ready", APP_NAME)
