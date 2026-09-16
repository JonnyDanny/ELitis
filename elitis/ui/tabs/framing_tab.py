"""
Framing Tab — canvas size, image fit mode, crop region, text anchor position.

Each control wraps a SettingRow so the phantom toggle works on every field.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGroupBox,
)
from PySide6.QtCore import Qt

from elitis.ui.app_state import AppState
from elitis.ui.widgets.setting_row import make_row, SettingRow


class FramingTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._rows: list[SettingRow] = []
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        scroll.setWidget(inner)

        layout.addWidget(self._make_group("Canvas", [
            ("Width",  "canvas_width"),
            ("Height", "canvas_height"),
        ]))
        layout.addWidget(self._make_group("Image fit", [
            ("Fit mode", "image_fit"),
        ]))
        layout.addWidget(self._make_group("Crop region (0–1, relative to image)", [
            ("Left (x)",   "crop_x"),
            ("Top (y)",    "crop_y"),
            ("Width",      "crop_w"),
            ("Height",     "crop_h"),
        ]))
        layout.addWidget(self._make_group("Text anchor (0–1, relative to canvas)", [
            ("Horizontal", "text_x"),
            ("Vertical",   "text_y"),
            ("Alignment",  "text_align"),
        ]))
        layout.addStretch()

    def _make_group(self, title: str, fields: list[tuple[str, str]]) -> QGroupBox:
        box = QGroupBox(title)
        vbox = QVBoxLayout(box)
        vbox.setSpacing(4)
        item    = self._state.current_item
        phantom = self._state.phantom
        for label, field_name in fields:
            row = make_row(label, field_name, item.settings, phantom.settings)
            row.changed.connect(self._state.notify_settings_changed)
            vbox.addWidget(row)
            self._rows.append(row)
        return box

    def _connect_signals(self):
        self._state.current_changed.connect(self._on_item_changed)
        self._state.project_replaced.connect(self._on_item_changed)

    def _on_item_changed(self, _index: int = 0):
        item    = self._state.current_item
        phantom = self._state.phantom
        for row in self._rows:
            row.switch_item(
                item.settings.get(row.field_name),
                phantom.settings.get(row.field_name),
            )
