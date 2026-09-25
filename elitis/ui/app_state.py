"""
AppState — Qt frontend session coordinator.

Inherits all shared state and write-boundary logic from BaseAppState;
adds Qt signals, background preview rendering, and clipboard paste.

All tabs hold a reference to the same AppState; they subscribe to its
signals and call its methods instead of touching the Project directly.

Module-level helper _inspect_clipboard(cb) is defined outside the class so
it can be tested with simple mock objects and has no Qt import requirement.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable, Slot
from PySide6.QtGui import QPixmap
from PIL import Image

from elitis.core.app_state import BaseAppState
from elitis.core.models import Project, ThumbnailItem
from elitis.core.font_manager import FontManager
from elitis.core import renderer
from elitis.ui.widgets.canvas_widget import pil_to_pixmap_scaled


# ---------------------------------------------------------------------------
# Clipboard inspection
# ---------------------------------------------------------------------------

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


def _try_decode_base64_image(text: str):
    """
    Decode a base64 data-URL image and return a PIL RGBA Image, or None.

    Accepts the standard data-URL format:  data:image/<fmt>;base64,<b64data>
    Returns a PIL Image on success, None on any failure (bad encoding, not an
    image, truncated data, etc.).  Never raises.
    """
    import base64, io
    text = text.strip()
    if not (text.startswith("data:image/") and ";base64," in text):
        return None
    try:
        _, b64_part = text.split(";base64,", 1)
        data = base64.b64decode(b64_part)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _inspect_clipboard(cb) -> tuple[str, str]:
    """
    Examine a clipboard object and classify its contents.

    Returns ``(category, message)`` where *category* is one of:

    ``"image"``  — clipboard has pixel data that can be pasted directly.
    ``"files"``  — clipboard has local file paths (e.g. copied in Explorer).
                   At least one is an image file → message says to use Open.
                   Otherwise → message says files contain no image data.
    ``"url"``    — clipboard has a plain-text URL (no local file available).
    ``"text"``   — clipboard has other plain text.
    ``"empty"``  — clipboard is empty or holds an unsupported format.

    This function is intentionally dependency-free: it only calls methods on *cb*
    and the objects it returns, so tests can pass simple mock objects.
    """
    qimg = cb.image()
    if not qimg.isNull():
        return "image", ""

    mime = cb.mimeData()

    if mime.hasUrls():
        urls = mime.urls()
        img_files = [
            u.toLocalFile() for u in urls
            if u.isLocalFile()
            and Path(u.toLocalFile()).suffix.lower() in _IMAGE_EXTS
        ]
        if img_files:
            names = ", ".join(Path(f).name for f in img_files[:3])
            return "files", (
                f"Clipboard has image file(s): {names} — "
                "use 'Open image' to load a file from disk"
            )
        non_img = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if non_img:
            return "files", "Clipboard has files but none are images"
        remote = [u.toString() for u in urls if not u.isLocalFile()]
        if remote:
            return "url", (
                "Clipboard has a remote URL — save the image locally first, "
                "then use 'Open image'"
            )
        return "empty", "Clipboard is empty or has no image"

    if mime.hasText():
        text = mime.text().strip()
        if text.startswith(("http://", "https://", "ftp://")):
            return "url", (
                "Clipboard has a URL, not image data — "
                "save the image locally first, then use 'Open image'"
            )
        if text.startswith("data:image/") and ";base64," in text:
            return "base64", ""
        return "text", "Clipboard has text, not image data"

    return "empty", "Clipboard is empty or has no image"


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

class AppState(QObject, BaseAppState):
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
        super().__init__(projects_dir=projects_dir, egest_dir=egest_dir,
                         fonts_dir=fonts_dir, parent=parent)
        self.ingest_dir = ingest_dir
        self._pool = QThreadPool.globalInstance()

    # ------------------------------------------------------------------
    # Hook overrides — wire BaseAppState reactions to Qt signals
    # ------------------------------------------------------------------

    def _on_changed(self, item: ThumbnailItem) -> None:
        self.settings_changed.emit()
        self.request_preview()
        self.items_status_changed.emit()

    def _on_navigation_changed(self, index: int) -> None:
        self.current_changed.emit(index)
        self.request_preview()

    def _on_project_replaced(self) -> None:
        self.project_replaced.emit()

    def _on_items_status_changed(self) -> None:
        self.items_status_changed.emit()

    def _on_status_message(self, msg: str) -> None:
        self.status_message.emit(msg)

    # ------------------------------------------------------------------
    # Qt-specific: called by SettingRow connections after direct SF writes
    # ------------------------------------------------------------------

    def notify_settings_changed(self):
        self._react(self.current_item)

    # ------------------------------------------------------------------
    # Qt-specific: override commit_image to add resolution warning
    # ------------------------------------------------------------------

    def commit_image(self, item_id: str, path: str | None) -> None:
        super().commit_image(item_id, path)
        if path:
            item = self._project.find_item(item_id)
            if item:
                cfg = self._project.resolve_item(item)
                warning = renderer.check_source_resolution(path, cfg)
                if warning:
                    self.status_message.emit(f"⚠  {warning}")

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
    # Qt-specific: ingest helpers
    # ------------------------------------------------------------------

    @property
    def sourced_dir(self) -> Path:
        return self.ingest_dir / "Sourced"

    def ingest_file(self, path: Path) -> Path:
        """
        Return a committed path for *path* via the ingest pipeline.

        If *path* is already inside ``ingest_dir`` it is returned as-is —
        no double-copy.  Otherwise the file's bytes are passed through
        ``save_sourced_image()`` and the committed path is returned.
        """
        from elitis.core.ingest import save_sourced_image
        try:
            path.relative_to(self.ingest_dir)
            return path  # already inside ingest tree
        except ValueError:
            pass
        return save_sourced_image(path.read_bytes(), path.name, self.sourced_dir)

    # ------------------------------------------------------------------
    # Qt-specific: clipboard paste
    # ------------------------------------------------------------------

    def paste_image_from_clipboard(self) -> bool:
        """
        Read the Qt clipboard, ingest whatever image it contains via
        ``save_sourced_image()``, and assign it to the current item.
        Returns True on success.

        Handled categories (in priority order):

        ``image``   — raw QImage pixel data (screenshot, Ctrl+C on an image).
                      Normalised to RGBA8888 before reading bytes so the layout
                      is always R,G,B,A regardless of platform endianness.
        ``base64``  — data: URL text (``data:image/...;base64,...``).
        ``files``   — local file path(s) on the clipboard (Explorer copy);
                      the first image file is ingested.
        ``url``     — HTTP/S URL text pointing at an image; fetched
                      synchronously with a 15-second timeout.
        """
        import io
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        from elitis.core.ingest import save_sourced_image, fetch_url_bytes

        cb = QApplication.clipboard()
        category, message = _inspect_clipboard(cb)

        if category == "image":
            qimg = cb.image().convertToFormat(QImage.Format.Format_RGBA8888)
            pil  = Image.frombytes("RGBA", (qimg.width(), qimg.height()),
                                   bytes(qimg.bits()))
            buf  = io.BytesIO()
            pil.save(buf, format="PNG")
            data, name, source_url = buf.getvalue(), "clipboard.png", None

        elif category == "base64":
            import base64 as _b64
            text = cb.mimeData().text().strip()
            _, b64_part = text.split(";base64,", 1)
            try:
                data = _b64.b64decode(b64_part)
            except Exception:
                self.status_message.emit("Clipboard base64 image could not be decoded")
                return False
            name, source_url = "clipboard.png", None

        elif category == "files":
            urls      = cb.mimeData().urls()
            img_paths = [
                Path(u.toLocalFile()) for u in urls
                if u.isLocalFile()
                and Path(u.toLocalFile()).suffix.lower() in _IMAGE_EXTS
            ]
            if not img_paths:
                self.status_message.emit(message)
                return False
            p = img_paths[0]
            data, name, source_url = p.read_bytes(), p.name, None

        elif category == "url":
            url = cb.mimeData().text().strip()
            self.status_message.emit("Fetching image…")
            data = fetch_url_bytes(url)
            if data is None:
                self.status_message.emit(f"Could not fetch: {url}")
                return False
            from pathlib import PurePosixPath
            name       = PurePosixPath(url.split("?")[0]).name or "image.jpg"
            source_url = url

        else:
            self.status_message.emit(message)
            return False

        try:
            path = save_sourced_image(data, name, self.sourced_dir,
                                      source_url=source_url)
        except Exception as exc:
            self.status_message.emit(f"Ingest failed: {exc}")
            return False

        self.set_image_for_current(str(path))
        self.status_message.emit(f"Pasted → {path.name}")
        return True
