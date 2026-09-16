"""
SettingRow — a labeled control that wraps a single SF (SettingField).

The phantom toggle (☁ icon) lets the user switch between:
  - use_phantom=True  → inherit from phantom (control shows phantom value, grayed out)
  - use_phantom=False → item-specific override (control is active)

When switching TO override for the first time, the phantom's current value is copied
as the item's starting value so edits feel continuous.

Factory function `make_row()` returns the appropriate subclass for each value type.
"""
from __future__ import annotations
from typing import Any, Callable
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QCheckBox, QSpinBox,
    QDoubleSpinBox, QComboBox, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

from elitis.core.models import SF
from elitis.ui.widgets.color_button import ColorButton


class SettingRow(QWidget):
    """Base class. Subclasses implement _build_control() and _read_control()/_write_control()."""
    changed = Signal()   # emitted whenever the SF changes (value or use_phantom)
    field_name: str = ""  # set by make_row()

    def __init__(self, label: str, item_sf: SF, phantom_sf: SF, parent=None):
        super().__init__(parent)
        self._item_sf = item_sf
        self._phantom_sf = phantom_sf

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        # Phantom toggle
        self._toggle = QCheckBox()
        self._toggle.setToolTip("☁  Use phantom default")
        self._toggle.setFixedWidth(18)
        self._toggle.setChecked(item_sf.use_phantom)
        self._toggle.stateChanged.connect(self._on_toggle)
        layout.addWidget(self._toggle)

        # Label
        lbl = QLabel(label)
        lbl.setFixedWidth(140)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl)

        # Control (built by subclass)
        self._control = self._build_control()
        layout.addWidget(self._control)
        layout.addStretch()

        self._refresh_state()

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    def _build_control(self) -> QWidget:
        raise NotImplementedError

    def _write_control(self, value: Any):
        """Push a value into the control widget."""
        raise NotImplementedError

    def _read_control(self) -> Any:
        """Read the current value from the control widget."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_state(self):
        using_phantom = self._item_sf.use_phantom
        self._toggle.blockSignals(True)
        self._toggle.setChecked(using_phantom)
        self._toggle.blockSignals(False)
        self._control.setEnabled(not using_phantom)
        if using_phantom:
            self._write_control(self._phantom_sf.value)
        else:
            self._write_control(self._item_sf.value)

    def _on_toggle(self, state):
        use_phantom = bool(state)
        if not use_phantom and self._item_sf.use_phantom:
            # First time enabling override: seed with phantom's value
            self._item_sf.value = self._phantom_sf.value
        self._item_sf.use_phantom = use_phantom
        self._refresh_state()
        self.changed.emit()

    def _on_control_changed(self):
        if not self._item_sf.use_phantom:
            self._item_sf.value = self._read_control()
            self.changed.emit()

    def refresh_phantom(self):
        """Call when phantom value changes so grayed display updates."""
        if self._item_sf.use_phantom:
            self._write_control(self._phantom_sf.value)

    def switch_item(self, item_sf: SF, phantom_sf: SF | None = None):
        """Switch to a different item's SF (when user navigates to another item)."""
        self._item_sf = item_sf
        if phantom_sf is not None:
            self._phantom_sf = phantom_sf
        self._refresh_state()


# ---------------------------------------------------------------------------
# Concrete row types
# ---------------------------------------------------------------------------

class IntRow(SettingRow):
    def __init__(self, label, item_sf, phantom_sf, min_val=0, max_val=9999, parent=None):
        self._min = min_val
        self._max = max_val
        super().__init__(label, item_sf, phantom_sf, parent)

    def _build_control(self):
        sb = QSpinBox()
        sb.setRange(self._min, self._max)
        sb.valueChanged.connect(self._on_control_changed)
        return sb

    def _write_control(self, v):
        self._control.blockSignals(True)
        self._control.setValue(int(v) if v is not None else 0)
        self._control.blockSignals(False)

    def _read_control(self):
        return self._control.value()


class FloatRow(SettingRow):
    def __init__(self, label, item_sf, phantom_sf, min_val=0.0, max_val=1.0,
                 decimals=2, step=0.01, parent=None):
        self._min = min_val
        self._max = max_val
        self._dec = decimals
        self._step = step
        super().__init__(label, item_sf, phantom_sf, parent)

    def _build_control(self):
        sb = QDoubleSpinBox()
        sb.setRange(self._min, self._max)
        sb.setDecimals(self._dec)
        sb.setSingleStep(self._step)
        sb.valueChanged.connect(self._on_control_changed)
        return sb

    def _write_control(self, v):
        self._control.blockSignals(True)
        self._control.setValue(float(v) if v is not None else 0.0)
        self._control.blockSignals(False)

    def _read_control(self):
        return self._control.value()


class ComboRow(SettingRow):
    def __init__(self, label, item_sf, phantom_sf, options: list[str], parent=None):
        self._options = options
        super().__init__(label, item_sf, phantom_sf, parent)

    def _build_control(self):
        cb = QComboBox()
        cb.addItems(self._options)
        cb.currentTextChanged.connect(self._on_control_changed)
        return cb

    def _write_control(self, v):
        self._control.blockSignals(True)
        idx = self._control.findText(str(v) if v is not None else "")
        if idx >= 0:
            self._control.setCurrentIndex(idx)
        self._control.blockSignals(False)

    def _read_control(self):
        return self._control.currentText()


class ColorRow(SettingRow):
    def _build_control(self):
        btn = ColorButton()
        btn.color_changed.connect(lambda _: self._on_control_changed())
        return btn

    def _write_control(self, v):
        if isinstance(v, (list, tuple)) and len(v) == 3:
            self._control.set_color(tuple(v))

    def _read_control(self):
        return self._control.color()


class BoolRow(SettingRow):
    def _build_control(self):
        cb = QCheckBox()
        cb.stateChanged.connect(self._on_control_changed)
        return cb

    def _write_control(self, v):
        self._control.blockSignals(True)
        self._control.setChecked(bool(v))
        self._control.blockSignals(False)

    def _read_control(self):
        return self._control.isChecked()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_row(
    label: str,
    field_name: str,
    item_settings,
    phantom_settings,
    **kwargs,
) -> SettingRow:
    """
    Create the right SettingRow subclass for a given field name.
    kwargs are forwarded to the subclass (e.g. min_val, max_val, options).
    """
    item_sf = item_settings.get(field_name)
    phantom_sf = phantom_settings.get(field_name)

    _TYPE_MAP = {
        # int fields
        "canvas_width":    (IntRow,   {"min_val": 100, "max_val": 7680}),
        "canvas_height":   (IntRow,   {"min_val": 100, "max_val": 4320}),
        "font_size":       (IntRow,   {"min_val": 8,   "max_val": 400}),
        "font_min_size":   (IntRow,   {"min_val": 4,   "max_val": 200}),
        "font_max_lines":  (IntRow,   {"min_val": 1,   "max_val": 10}),
        "outline_width":   (IntRow,   {"min_val": 0,   "max_val": 20}),
        "shadow_offset_x": (IntRow,   {"min_val": -50, "max_val": 50}),
        "shadow_offset_y": (IntRow,   {"min_val": -50, "max_val": 50}),
        "shadow_blur":     (IntRow,   {"min_val": 0,   "max_val": 30}),
        "box_padding":     (IntRow,   {"min_val": 0,   "max_val": 200}),
        "text_opacity":    (IntRow,   {"min_val": 0,   "max_val": 255}),
        "box_opacity":     (IntRow,   {"min_val": 0,   "max_val": 255}),
        # float fields
        "crop_x":          (FloatRow, {"min_val": 0.0, "max_val": 1.0}),
        "crop_y":          (FloatRow, {"min_val": 0.0, "max_val": 1.0}),
        "crop_w":          (FloatRow, {"min_val": 0.01,"max_val": 1.0}),
        "crop_h":          (FloatRow, {"min_val": 0.01,"max_val": 1.0}),
        "text_x":          (FloatRow, {"min_val": 0.0, "max_val": 1.0}),
        "text_y":          (FloatRow, {"min_val": 0.0, "max_val": 1.0}),
        "box_height":      (FloatRow, {"min_val": 0.0, "max_val": 1.0}),
        # combo fields
        "image_fit":       (ComboRow, {"options": ["fill", "fit", "stretch", "center"]}),
        "text_transform":  (ComboRow, {"options": ["none", "upper", "lower", "title"]}),
        "text_align":      (ComboRow, {"options": ["left", "center", "right"]}),
        "box_position":    (ComboRow, {"options": ["bottom", "top", "full"]}),
        # color fields
        "text_color":      (ColorRow, {}),
        "outline_color":   (ColorRow, {}),
        "shadow_color":    (ColorRow, {}),
        "box_color":       (ColorRow, {}),
        # bool fields
        "font_auto_size":  (BoolRow,  {}),
        "outline_enabled": (BoolRow,  {}),
        "shadow_enabled":  (BoolRow,  {}),
        "box_enabled":     (BoolRow,  {}),
    }

    cls, defaults = _TYPE_MAP.get(field_name, (None, {}))
    if cls is None:
        raise ValueError(f"No SettingRow type registered for field '{field_name}'")
    merged = {**defaults, **kwargs}
    row = cls(label, item_sf, phantom_sf, **merged)
    row.field_name = field_name
    return row
