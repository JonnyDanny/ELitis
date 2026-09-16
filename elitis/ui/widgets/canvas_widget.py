"""
Preview canvas — a QLabel that displays a PIL Image as a QPixmap.
Scales to fill the available space while preserving aspect ratio.
"""
from __future__ import annotations
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt, QSize
from PIL import Image
import io


class CanvasWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background: #111122; border: 1px solid #44445a;")
        self._pixmap: QPixmap | None = None

    def set_image(self, img: Image.Image | None):
        if img is None:
            self._pixmap = None
            self.setText("No preview")
            return
        self._pixmap = pil_to_pixmap(img)
        self._redisplay()

    def set_pixmap(self, px: QPixmap):
        self._pixmap = px
        self._redisplay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redisplay()

    def _redisplay(self):
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def pil_to_pixmap_scaled(img: Image.Image, max_size: tuple[int, int]) -> QPixmap:
    img = img.copy()
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return pil_to_pixmap(img)
