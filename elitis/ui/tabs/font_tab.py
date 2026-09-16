"""
Font / Style Tab — font selection with live preview, text color, outline, shadow, box overlay.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QGroupBox,
    QLabel, QListWidget, QListWidgetItem, QSplitter,
)
from PySide6.QtCore import Qt

from elitis.ui.app_state import AppState
from elitis.ui.widgets.setting_row import make_row, SettingRow, ComboRow, RowContext
from elitis.core.models import SF


class FontTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._rows: list[SettingRow] = []
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # Left: font list
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel("Fonts  (from Fonts/ folder)")
        lbl.setObjectName("dim")
        left_l.addWidget(lbl)
        self._font_list = QListWidget()
        self._font_list.setFixedWidth(200)
        left_l.addWidget(self._font_list)
        self._lbl_no_fonts = QLabel("No fonts found.\nAdd .ttf/.otf files\nto the Fonts/ folder.")
        self._lbl_no_fonts.setObjectName("dim")
        self._lbl_no_fonts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self._lbl_no_fonts)
        splitter.addWidget(left)

        # Right: settings
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        right_l = QVBoxLayout(inner)
        right_l.setContentsMargins(12, 12, 12, 12)
        right_l.setSpacing(10)
        right.setWidget(inner)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

        # Font settings group (font name is selected via the list on the left)
        right_l.addWidget(self._make_group("Font size", [
            ("Max size",     "font_size"),
            ("Auto-size",    "font_auto_size"),
            ("Min size",     "font_min_size"),
            ("Max lines",    "font_max_lines"),
        ]))

        # Text appearance
        right_l.addWidget(self._make_group("Text", [
            ("Color",       "text_color"),
            ("Opacity",     "text_opacity"),
            ("Transform",   "text_transform"),
        ]))

        # Outline
        right_l.addWidget(self._make_group("Outline", [
            ("Enabled",     "outline_enabled"),
            ("Color",       "outline_color"),
            ("Width",       "outline_width"),
        ]))

        # Shadow
        right_l.addWidget(self._make_group("Shadow", [
            ("Enabled",     "shadow_enabled"),
            ("Color",       "shadow_color"),
            ("Offset X",    "shadow_offset_x"),
            ("Offset Y",    "shadow_offset_y"),
            ("Blur",        "shadow_blur"),
        ]))

        # Box overlay
        right_l.addWidget(self._make_group("Box overlay", [
            ("Enabled",     "box_enabled"),
            ("Color",       "box_color"),
            ("Opacity",     "box_opacity"),
            ("Height",      "box_height"),
            ("Padding",     "box_padding"),
            ("Position",    "box_position"),
        ]))

        right_l.addStretch()
        self._populate_font_list()

    def _make_group(self, title: str, fields: list[tuple[str, str]]) -> QGroupBox:
        box = QGroupBox(title)
        vbox = QVBoxLayout(box)
        vbox.setSpacing(4)
        item     = self._state.current_item
        defaults = self._state.defaults
        ctx = RowContext(is_default=item.is_default)
        for label, field_name in fields:
            row = make_row(label, field_name, item.settings, defaults.settings, ctx=ctx)
            row.changed.connect(self._state.notify_settings_changed)
            vbox.addWidget(row)
            self._rows.append(row)
        return box

    def _populate_font_list(self):
        fonts = self._state.font_manager.available
        self._font_list.clear()
        if fonts:
            self._lbl_no_fonts.hide()
            for name in fonts:
                self._font_list.addItem(name)
        else:
            self._lbl_no_fonts.show()
        self._font_list.currentTextChanged.connect(self._on_font_selected)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._state.current_changed.connect(self._on_item_changed)
        self._state.project_replaced.connect(self._on_item_changed)

    def _on_item_changed(self, _index: int = 0):
        item     = self._state.current_item
        defaults = self._state.defaults
        ctx = RowContext(is_default=item.is_default)
        for row in self._rows:
            row.apply_context(ctx)
            row.switch_item(item.settings.get(row.field_name), defaults.settings.get(row.field_name))
        # Sync font list selection
        font_name = item.settings.get("font_name").value
        items = self._font_list.findItems(font_name, Qt.MatchFlag.MatchFixedString)
        if items:
            self._font_list.setCurrentItem(items[0])

    def _on_font_selected(self, name: str):
        if not name:
            return
        item_sf = self._state.current_item.settings.get("font_name")
        item_sf.value = name
        item_sf.use_default = False
        # Update the font_name row control
        for row in self._rows:
            if row.field_name == "font_name":
                row.switch_item(item_sf, self._state.defaults.settings.get("font_name"))
                break
        self._state.notify_settings_changed()
