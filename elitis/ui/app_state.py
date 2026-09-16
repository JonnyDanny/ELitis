"""
AppState — single QObject that owns the live Project and coordinates the UI.

All tabs hold a reference to the same AppState; they subscribe to its signals
and call its methods instead of touching the Project directly.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable, Slot
from PySide6.QtGui import QPixmap
from PIL import Image

from elitis.core.models import Project, ThumbnailItem
from elitis.core.font_manager import FontManager
from elitis.core import data_io, renderer
from elitis.ui.widgets.canvas_widget import pil_to_pixmap_scaled


# ---------------------------------------------------------------------------
# Background render task
# ---------------------------------------------------------------------------

class _RenderSignals(QObject):
    done  = Signal(QPixmap, int)   # pixmap, item_index
    error = Signal(str)


class _RenderTask(QRunnable):
    def __init__(self, project: Project, item: ThumbnailItem,
                 item_index: int, font_manager: FontManager,
                 preview_size: tuple[int, int]):
        super().__init__()
        self.signals   = _RenderSignals()
        self._project  = project
        self._item     = item
        self._index    = item_index
        self._fonts    = font_manager
        self._psize    = preview_size

    @Slot()
    def run(self):
        try:
            img = renderer.render_thumbnail(
                self._item, self._project, self._fonts, self._psize
            )
            px = pil_to_pixmap_scaled(img, self._psize)
            self.signals.done.emit(px, self._index)
        except Exception as exc:
            self.signals.error.emit(str(exc))


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------

class AppState(QObject):
    # Emitted when the current item changes (index)
    current_changed = Signal(int)
    # Emitted when a setting on any item changes (triggers re-render)
    settings_changed = Signal()
    # Emitted when the project is replaced (new/load)
    project_replaced = Signal()
    # Emitted when a preview render finishes
    preview_ready = Signal(QPixmap)
    # Status bar messages
    status_message = Signal(str)
    # Emitted when any item's rendered/dirty status changes
    items_status_changed = Signal()

    def __init__(
        self,
        projects_dir: Path,
        ingest_dir: Path,
        egest_dir: Path,
        fonts_dir: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.projects_dir = projects_dir
        self.ingest_dir   = ingest_dir
        self.egest_dir    = egest_dir

        self._font_manager = FontManager(fonts_dir)
        self._project: Project = Project.new("untitled", str(egest_dir))
        self._current_index: int = 1   # 0=defaults item, 1..N = content
        self._project_path: Optional[Path] = None
        self._pool = QThreadPool.globalInstance()
        self._pending_render: Optional[_RenderTask] = None
        # IDs of items whose last export is still current (not dirtied since)
        self._clean_ids: set[str] = set()
        # True if the defaults item's settings were changed since last project load/new
        self._defaults_dirty: bool = False

    # ------------------------------------------------------------------
    # Font manager
    # ------------------------------------------------------------------

    @property
    def font_manager(self) -> FontManager:
        return self._font_manager

    # ------------------------------------------------------------------
    # Project access
    # ------------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self._project

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_item(self) -> ThumbnailItem:
        items = self._project.items
        idx = max(0, min(self._current_index, len(items) - 1))
        return items[idx]

    @property
    def defaults(self) -> ThumbnailItem:
        return self._project.defaults

    def item_count(self) -> int:
        return len(self._project.items)

    def content_count(self) -> int:
        return len(self._project.content_items)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_to(self, index: int):
        count = self.item_count()
        index = max(0, min(index, count - 1))
        if index != self._current_index:
            self._current_index = index
            self.current_changed.emit(index)
            self.request_preview()

    def go_next(self):
        self.go_to(self._current_index + 1)

    def go_prev(self):
        self.go_to(self._current_index - 1)

    def go_to_defaults(self):
        self.go_to(0)

    # ------------------------------------------------------------------
    # Settings changes
    # ------------------------------------------------------------------

    def notify_settings_changed(self):
        cur = self.current_item
        if cur.is_default:
            self._defaults_dirty = True
        else:
            self._clean_ids.discard(cur.id)
        self.settings_changed.emit()
        self.request_preview()
        self.items_status_changed.emit()

    def is_clean(self, item_id: str) -> bool:
        """True if the item has been exported and not changed since."""
        return item_id in self._clean_ids

    @property
    def defaults_dirty(self) -> bool:
        """True if the defaults item's settings changed since the last project load/new."""
        return self._defaults_dirty

    def mark_rendered(self, item_id: str):
        self._clean_ids.add(item_id)
        self.items_status_changed.emit()

    def mark_all_rendered(self):
        self._clean_ids = {i.id for i in self._project.content_items}
        self.items_status_changed.emit()

    # ------------------------------------------------------------------
    # Image management
    # ------------------------------------------------------------------

    def set_image_for_current(self, path: str):
        self.current_item.image_path = path
        self.notify_settings_changed()

    def paste_image_from_clipboard(self) -> bool:
        """
        Grab an image from the Qt clipboard, save it to Ingest/Pasted/,
        and assign it to the current item. Returns True on success.
        """
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        import datetime, uuid

        cb = QApplication.clipboard()
        qimg = cb.image()
        if qimg.isNull():
            self.status_message.emit("Clipboard has no image")
            return False

        # Convert QImage → PIL → save
        ba = qimg.bits().tobytes() if hasattr(qimg.bits(), "tobytes") else bytes(qimg.bits())
        pil = Image.frombytes("RGBA", (qimg.width(), qimg.height()), ba, "raw", "BGRA")

        pasted_dir = self.ingest_dir / "Pasted"
        pasted_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:6]
        dest = pasted_dir / f"pasted_{ts}_{uid}.png"
        pil.save(str(dest))

        self.set_image_for_current(str(dest))
        self.status_message.emit(f"Pasted image saved: {dest.name}")
        return True

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------

    def request_preview(self, preview_size: tuple[int, int] = (960, 540)):
        item = self.current_item
        task = _RenderTask(
            self._project, item, self._current_index,
            self._font_manager, preview_size
        )
        task.signals.done.connect(self._on_render_done)
        task.signals.error.connect(self._on_render_error)
        self._pool.start(task)

    @Slot(QPixmap, int)
    def _on_render_done(self, pixmap: QPixmap, index: int):
        if index == self._current_index:
            self.preview_ready.emit(pixmap)

    @Slot(str)
    def _on_render_error(self, msg: str):
        self.status_message.emit(f"Render error: {msg}")

    # ------------------------------------------------------------------
    # Project IO
    # ------------------------------------------------------------------

    def new_project(self, name: str = "untitled"):
        self._project = Project.new(name, str(self.egest_dir))
        self._project_path = None
        self._current_index = 0
        self._clean_ids.clear()
        self._defaults_dirty = False
        self.project_replaced.emit()
        self.current_changed.emit(0)
        self.request_preview()

    def save_project(self) -> Path:
        if self._project_path is None:
            safe = self._project.name.replace(" ", "_")
            self._project_path = self.projects_dir / f"{safe}.json"
        data_io.save_project(self._project, self._project_path)
        self.status_message.emit(f"Saved: {self._project_path.name}")
        return self._project_path

    def save_project_as(self, path: Path):
        self._project_path = path
        data_io.save_project(self._project, path)
        self.status_message.emit(f"Saved: {path.name}")

    def load_project(self, path: Path):
        self._project = data_io.load_project(path)
        self._project_path = path
        self._current_index = min(1, len(self._project.items) - 1)
        self._clean_ids.clear()
        self._defaults_dirty = False
        self._font_manager.scan()
        self.project_replaced.emit()
        self.current_changed.emit(self._current_index)
        self.request_preview()

    def import_labels(self, source_path: Path, column: int = 0) -> int:
        """Import labels from CSV/TXT, append as new items. Returns count added."""
        labels = data_io.import_labels(source_path, column)
        for lbl in labels:
            self._project.add_item(lbl)
        if labels:
            self._current_index = 1
            self.project_replaced.emit()
            self.request_preview()
        return len(labels)

    def export_batch(self, fmt: str = "PNG") -> list[Path]:
        """Render and save all content items. Returns list of saved paths."""
        out_dir = Path(self._project.output_dir)
        if not out_dir.is_absolute():
            out_dir = self.egest_dir / self._project.name

        def _progress(done, total, path):
            self.status_message.emit(f"Saved {done}/{total}: {path.name}")

        result = renderer.render_all(
            self._project, self._font_manager, out_dir,
            fmt=fmt, on_progress=_progress,
        )
        self.mark_all_rendered()
        return result
