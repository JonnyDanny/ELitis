"""
Main application window.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from elitis.ui.app_state import AppState, _IMAGE_EXTS
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
        self.setAcceptDrops(True)

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

    # ------------------------------------------------------------------
    # Drag-drop — accept local image files and HTTP image URLs
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() and any(self._url_is_image(u) for u in mime.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        from elitis.core.ingest import save_sourced_image, fetch_url_bytes
        from pathlib import PurePosixPath

        mime  = event.mimeData()
        state = self._state
        ingested: list[Path] = []

        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in _IMAGE_EXTS and p.is_file():
                    try:
                        ingested.append(state.ingest_file(p))
                    except Exception as exc:
                        state.status_message.emit(f"Drop ingest failed: {exc}")

            else:
                href = url.toString()
                if not any(href.lower().endswith(ext) for ext in _IMAGE_EXTS):
                    continue
                state.status_message.emit(f"Fetching {href}…")
                data = fetch_url_bytes(href)
                if data is None:
                    state.status_message.emit(f"Could not fetch: {href}")
                    continue
                name = PurePosixPath(href.split("?")[0]).name or "image.jpg"
                try:
                    ingested.append(
                        save_sourced_image(data, name, state.sourced_dir,
                                           source_url=href)
                    )
                except Exception as exc:
                    state.status_message.emit(f"Drop ingest failed: {exc}")

        if ingested:
            # Assign the first dropped image to the current item; subsequent
            # ones are committed to Sourced/ for later assignment.
            state.commit_image(state.current_item.id, str(ingested[0]))
            if len(ingested) == 1:
                state.status_message.emit(f"Dropped → {ingested[0].name}")
            else:
                names = ", ".join(p.name for p in ingested)
                state.status_message.emit(
                    f"Dropped {len(ingested)} images → first assigned; others saved: {names}"
                )
        event.acceptProposedAction()

    @staticmethod
    def _url_is_image(url) -> bool:
        if url.isLocalFile():
            return Path(url.toLocalFile()).suffix.lower() in _IMAGE_EXTS
        href = url.toString().lower()
        return any(href.endswith(ext) for ext in _IMAGE_EXTS)
