"""
Preview Tab — full-size preview of the current item, navigation, filmstrip,
quick image swap, and export buttons.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QKeySequence, QShortcut

from elitis.ui.app_state import AppState
from elitis.ui.widgets.canvas_widget import CanvasWidget, pil_to_pixmap_scaled
from elitis.core import renderer


_FILM_SIZE = (160, 90)


class FilmThumb(QLabel):
    clicked = Signal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setFixedSize(*_FILM_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 2px solid #44445a; background: #111122;")

    def set_active(self, active: bool):
        color = "#8b5cf6" if active else "#44445a"
        self.setStyleSheet(f"border: 2px solid {color}; background: #111122;")

    def mousePressEvent(self, event):
        self.clicked.emit(self.index)


class FilmStrip(QScrollArea):
    item_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(_FILM_SIZE[1] + 20)
        self.setWidgetResizable(True)

        self._inner = QWidget()
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self.setWidget(self._inner)

        self._thumbs: list[FilmThumb] = []

    def rebuild(self, state: AppState):
        # Clear
        for t in self._thumbs:
            t.deleteLater()
        self._thumbs.clear()
        # Remove stretch
        self._layout.takeAt(self._layout.count() - 1)

        for i, item in enumerate(state.project.content_items, start=1):
            t = FilmThumb(i)
            t.setText(item.label[:20] or "—")
            t.clicked.connect(self.item_clicked.emit)
            self._layout.addWidget(t)
            self._thumbs.append(t)

        self._layout.addStretch()
        self._render_thumbs(state)

    def _render_thumbs(self, state: AppState):
        for t in self._thumbs:
            item = state.project.items[t.index]
            try:
                img = renderer.render_thumbnail(item, state.project, state.font_manager, _FILM_SIZE)
                px = pil_to_pixmap_scaled(img, _FILM_SIZE)
                t.setPixmap(px)
            except Exception:
                t.setText(item.label[:20] or "—")

    def highlight(self, index: int):
        for t in self._thumbs:
            t.set_active(t.index == index)
        # Scroll to active
        for t in self._thumbs:
            if t.index == index:
                self.ensureWidgetVisible(t)
                break


class PreviewTab(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._build_ui()
        self._connect_signals()
        self._update_nav_labels()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- Top toolbar ----
        top = QHBoxLayout()
        self._lbl_name = QLabel("untitled")
        self._lbl_name.setStyleSheet("font-weight: bold; font-size: 15px;")
        top.addWidget(self._lbl_name)
        top.addStretch()

        self._btn_defaults = QPushButton("☁ Defaults")
        self._btn_defaults.setToolTip("Jump to defaults (template) item")
        top.addWidget(self._btn_defaults)
        layout.addLayout(top)

        # ---- Main canvas ----
        self._canvas = CanvasWidget()
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._canvas, stretch=1)

        # ---- Nav bar ----
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀  Prev")
        self._btn_next = QPushButton("Next  ▶")
        self._lbl_pos  = QLabel("0 / 0")
        self._lbl_pos.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nav.addWidget(self._btn_prev)
        nav.addStretch()
        nav.addWidget(self._lbl_pos)
        nav.addStretch()
        nav.addWidget(self._btn_next)
        layout.addLayout(nav)

        # ---- Film strip ----
        self._film = FilmStrip()
        layout.addWidget(self._film)

        # ---- Action bar ----
        actions = QHBoxLayout()

        self._btn_open_img = QPushButton("Open image…")
        self._btn_paste    = QPushButton("Paste image")
        self._btn_save_one = QPushButton("Save this")
        self._btn_save_all = QPushButton("Save all")
        self._btn_save_all.setObjectName("accent")

        for b in (self._btn_open_img, self._btn_paste,
                  self._btn_save_one, self._btn_save_all):
            actions.addWidget(b)
        layout.addLayout(actions)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self):
        s = self._state
        s.preview_ready.connect(self._canvas.set_pixmap)
        s.current_changed.connect(self._on_current_changed)
        s.project_replaced.connect(self._on_project_replaced)

        self._btn_prev.clicked.connect(s.go_prev)
        self._btn_next.clicked.connect(s.go_next)
        self._btn_defaults.clicked.connect(s.go_to_defaults)
        self._btn_open_img.clicked.connect(self._open_image)
        self._btn_paste.clicked.connect(s.paste_image_from_clipboard)
        self._btn_save_one.clicked.connect(self._save_one)
        self._btn_save_all.clicked.connect(self._save_all)
        self._film.item_clicked.connect(s.go_to)

        QShortcut(QKeySequence(Qt.Key.Key_Left),  self, s.go_prev)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, s.go_next)
        QShortcut(QKeySequence("Ctrl+V"),         self, s.paste_image_from_clipboard)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_current_changed(self, index: int):
        self._update_nav_labels()
        self._film.highlight(index)

    def _on_project_replaced(self):
        self._film.rebuild(self._state)
        self._update_nav_labels()
        self._lbl_name.setText(self._state.project.name)

    def _update_nav_labels(self):
        total = self._state.item_count()
        idx   = self._state.current_index
        label = "defaults" if idx == 0 else f"{idx} / {max(1, total - 1)}"
        self._lbl_pos.setText(label)

        item = self._state.current_item
        name = "Defaults (template)" if item.is_default else (item.label or f"Item {idx}")
        self._lbl_name.setText(name)

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", str(self._state.ingest_dir),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )
        if path:
            self._state.set_image_for_current(path)

    def _save_one(self):
        item = self._state.current_item
        if item.is_default:
            self._state.status_message.emit("Cannot export the defaults item")
            return
        cfg = self._state.project.resolve_item(item)
        out = Path(self._state.project.output_dir)
        if not out.is_absolute():
            out = self._state.egest_dir / self._state.project.name
        out.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in item.label or item.id)
        dest = out / f"{safe}.png"
        img = renderer.render_thumbnail(item, self._state.project, self._state.font_manager)
        img.save(str(dest))
        self._state.status_message.emit(f"Saved: {dest}")

    def _save_all(self):
        saved = self._state.export_batch()
        self._state.status_message.emit(f"Batch complete — {len(saved)} files saved")
        self._film.rebuild(self._state)
