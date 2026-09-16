"""A button that shows the current color and opens QColorDialog on click."""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PySide6.QtGui import QColor
from PySide6.QtCore import Signal


class ColorButton(QWidget):
    color_changed = Signal(tuple)   # emits (r, g, b)

    def __init__(self, label: str = "", color: tuple = (255, 255, 255), parent=None):
        super().__init__(parent)
        self._color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if label:
            self._label = QLabel(label)
            layout.addWidget(self._label)

        self._btn = QPushButton()
        self._btn.setFixedSize(48, 24)
        self._btn.clicked.connect(self._pick)
        layout.addWidget(self._btn)
        layout.addStretch()
        self._refresh_swatch()

    def _refresh_swatch(self):
        r, g, b = self._color
        self._btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #44445a; border-radius: 3px;"
        )

    def _pick(self):
        from PySide6.QtWidgets import QColorDialog
        r, g, b = self._color
        initial = QColor(r, g, b)
        chosen = QColorDialog.getColor(initial, self, "Pick color")
        if chosen.isValid():
            self._color = (chosen.red(), chosen.green(), chosen.blue())
            self._refresh_swatch()
            self.color_changed.emit(self._color)

    def color(self) -> tuple:
        return self._color

    def set_color(self, color: tuple):
        self._color = color
        self._refresh_swatch()
