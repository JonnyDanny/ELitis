"""
Framing Tab — interactive crop/zoom selector plus canvas-size controls.

Left panel : FramingCanvas (the interactive overlay widget).
Right panel: mode buttons, info display, anchor grid (fill), anti-upscale
             toggle (zoom), canvas-size rows.

All render-triggering is debounced through drag_finished, so the Pillow
render only fires after the user releases the mouse — not on every pixel move.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox,
    QPushButton, QLabel, QCheckBox, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap

from elitis.ui.app_state import AppState
from elitis.ui.widgets.framing_canvas import FramingCanvas
from elitis.ui.widgets.setting_row import make_row, SettingRow


_MODES = [
    ('fill',    "Fill",    "AR-locked window — selection always fills canvas exactly"),
    ('zoom',    "Zoom",    "Freehand region — zooms in, fits within canvas (letterboxed)"),
    ('fit',     "Fit",     "Whole image, letterboxed to fit canvas"),
    ('stretch', "Stretch", "Whole image, stretched to fill canvas"),
    ('center',  "Center",  "Image at native size, centered, edges clipped"),
]


class FramingTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._rows: list[SettingRow] = []
        self._mode_btns: dict[str, QPushButton] = {}
        self._build_ui()
        self._connect_signals()
        self._refresh_from_item()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Left: interactive canvas ----
        self._canvas = FramingCanvas()
        root.addWidget(self._canvas, stretch=1)

        # ---- Right: controls ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #44445a;")
        root.addWidget(sep)

        right = QWidget()
        right.setFixedWidth(220)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 10, 10, 10)
        rl.setSpacing(10)
        root.addWidget(right)

        # Mode buttons
        mode_box = QGroupBox("Mode")
        ml = QVBoxLayout(mode_box)
        ml.setSpacing(3)
        for key, label, tip in _MODES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda checked, k=key: self._set_mode(k))
            self._mode_btns[key] = btn
            ml.addWidget(btn)
        rl.addWidget(mode_box)

        # Mode description
        self._lbl_mode_desc = QLabel()
        self._lbl_mode_desc.setObjectName("dim")
        self._lbl_mode_desc.setWordWrap(True)
        rl.addWidget(self._lbl_mode_desc)

        # Info display
        info_box = QGroupBox("Info")
        il = QVBoxLayout(info_box)
        self._lbl_src    = QLabel("Source: —")
        self._lbl_out    = QLabel("Canvas: —")
        self._lbl_crop   = QLabel("Crop: —")
        for l in (self._lbl_src, self._lbl_out, self._lbl_crop):
            l.setObjectName("dim")
            il.addWidget(l)
        rl.addWidget(info_box)

        # Anchor grid (fill mode only)
        self._anchor_box = QGroupBox("Anchor (fill mode)")
        al = QVBoxLayout(self._anchor_box)
        al.setSpacing(2)
        _LABELS = [
            ("↖", 0.0, 0.0), ("↑",  0.5, 0.0), ("↗", 1.0, 0.0),
            ("←", 0.0, 0.5), ("·",  0.5, 0.5), ("→", 1.0, 0.5),
            ("↙", 0.0, 1.0), ("↓",  0.5, 1.0), ("↘", 1.0, 1.0),
        ]
        row_idx = 0
        row_w = None
        for i, (sym, ax, ay) in enumerate(_LABELS):
            if i % 3 == 0:
                row_w = QWidget()
                rl2 = QHBoxLayout(row_w)
                rl2.setContentsMargins(0, 0, 0, 0)
                rl2.setSpacing(2)
                al.addWidget(row_w)
            b = QPushButton(sym)
            b.setFixedSize(40, 28)
            b.setToolTip(f"Anchor ({ax:.0%}, {ay:.0%})")
            b.clicked.connect(lambda _, a=ax, b_=ay: self._canvas.snap_anchor(a, b_))
            row_w.layout().addWidget(b)
        rl.addWidget(self._anchor_box)

        # Anti-upscale toggle (zoom mode only)
        self._zoom_box = QGroupBox("Zoom mode")
        zl = QVBoxLayout(self._zoom_box)
        self._chk_upscale = QCheckBox("Snap to 1:1 on release")
        self._chk_upscale.setChecked(False)
        self._chk_upscale.toggled.connect(
            lambda v: self._canvas.set_allow_upscale(not v))
        zl.addWidget(self._chk_upscale)
        self._lbl_zoom_hint = QLabel(
            "When checked: if your selection would require upscaling, it "
            "expands to the minimum 1:1 pixel size on release, re-centered "
            "on what you drew."
        )
        self._lbl_zoom_hint.setObjectName("dim")
        self._lbl_zoom_hint.setWordWrap(True)
        zl.addWidget(self._lbl_zoom_hint)
        rl.addWidget(self._zoom_box)

        # Canvas size rows
        size_box = QGroupBox("Canvas size")
        sl = QVBoxLayout(size_box)
        sl.setSpacing(4)
        item    = self._state.current_item
        phantom = self._state.phantom
        for label, field in (("Width", "canvas_width"), ("Height", "canvas_height")):
            row = make_row(label, field, item.settings, phantom.settings,
                           is_phantom_item=item.is_phantom)
            row.changed.connect(self._on_canvas_size_changed)
            sl.addWidget(row)
            self._rows.append(row)
        rl.addWidget(size_box)

        # Reset
        btn_reset = QPushButton("Reset crop to full")
        btn_reset.clicked.connect(self._canvas.reset)
        rl.addWidget(btn_reset)

        rl.addStretch()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self):
        s = self._state
        s.current_changed.connect(self._refresh_from_item)
        s.project_replaced.connect(self._refresh_from_item)

        self._canvas.crop_changed.connect(self._on_crop_changed)
        self._canvas.drag_finished.connect(self._on_drag_finished)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _refresh_from_item(self, _=None):
        item    = self._state.current_item
        phantom = self._state.phantom
        cfg     = self._state.project.resolve_item(item)

        # Load source image into canvas as QPixmap
        path = item.effective_image(phantom)
        if path and Path(path).exists():
            px = QPixmap(path)
            self._canvas.set_source(px, px.width(), px.height())
        else:
            self._canvas.set_source(None)

        self._canvas.set_output_size(cfg.canvas_width, cfg.canvas_height)
        self._canvas.set_crop(cfg.crop_x, cfg.crop_y, cfg.crop_w, cfg.crop_h)
        self._canvas.set_mode(cfg.image_fit)
        self._set_mode(cfg.image_fit, emit=False)

        # Update info labels
        src_w = self._canvas._src_w
        src_h = self._canvas._src_h
        self._lbl_src.setText(f"Source: {src_w} × {src_h} px")
        self._lbl_out.setText(f"Canvas: {cfg.canvas_width} × {cfg.canvas_height} px")
        self._update_crop_label(cfg.crop_x, cfg.crop_y, cfg.crop_w, cfg.crop_h)

        # Switch setting rows to new item
        for row in self._rows:
            row.switch_item(
                item.settings.get(row.field_name),
                phantom.settings.get(row.field_name),
                is_phantom_item=item.is_phantom,
            )

    def _set_mode(self, mode: str, emit: bool = True):
        for key, btn in self._mode_btns.items():
            btn.setChecked(key == mode)
        # Update description
        desc = next((d for k, _, d in _MODES if k == mode), "")
        self._lbl_mode_desc.setText(desc)
        # Show/hide mode-specific panels
        self._anchor_box.setVisible(mode == 'fill')
        self._zoom_box.setVisible(mode == 'zoom')

        if emit:
            self._canvas.set_mode(mode)
            item = self._state.current_item
            sf = item.settings.get('image_fit')
            sf.value = mode
            sf.use_phantom = False
            self._state.notify_settings_changed()

    def _on_crop_changed(self, x: float, y: float, w: float, h: float):
        # Update the SF values live (no render yet)
        item = self._state.current_item
        for field, val in (('crop_x', x), ('crop_y', y), ('crop_w', w), ('crop_h', h)):
            sf = item.settings.get(field)
            sf.value = round(val, 4)
            sf.use_phantom = False
        self._update_crop_label(x, y, w, h)

    def _on_drag_finished(self, x: float, y: float, w: float, h: float):
        # Trigger actual Pillow re-render only when drag ends
        self._state.notify_settings_changed()

    def _on_canvas_size_changed(self):
        self._state.notify_settings_changed()
        cfg = self._state.project.resolve_item(self._state.current_item)
        self._canvas.set_output_size(cfg.canvas_width, cfg.canvas_height)
        self._lbl_out.setText(f"Canvas: {cfg.canvas_width} × {cfg.canvas_height} px")

    def _update_crop_label(self, x, y, w, h):
        self._lbl_crop.setText(
            f"Crop: ({x:.3f}, {y:.3f})\n"
            f"      {w:.3f} × {h:.3f}"
        )
