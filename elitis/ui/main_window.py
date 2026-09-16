"""
Main application window.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QWidget,
)
from PySide6.QtCore import Qt

from elitis.ui.app_state import AppState
from elitis.ui.tabs.preview_tab import PreviewTab
from elitis.ui.tabs.framing_tab import FramingTab
from elitis.ui.tabs.font_tab    import FontTab
from elitis.ui.tabs.data_tab    import DataTab


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state

        self.setWindowTitle("ELItis — Tier List Thumbnail Generator")
        self.resize(1200, 750)
        self.setMinimumSize(800, 550)

        tabs = QTabWidget()
        tabs.addTab(PreviewTab(state), "Preview")
        tabs.addTab(FramingTab(state), "Framing")
        tabs.addTab(FontTab(state),    "Fonts & Style")
        tabs.addTab(DataTab(state),    "Data")
        self.setCentralWidget(tabs)

        bar = QStatusBar()
        self.setStatusBar(bar)
        state.status_message.connect(lambda msg: bar.showMessage(msg, 4000))

        # Initial render
        state.request_preview()
