"""
FramingCanvas — interactive crop-region selector.

The source image is converted to a QPixmap once and drawn with QPainter.
All framing interactions (move, resize, draw-new-rect) are pure overlay
operations — zero Pillow re-renders during drag.

Two interactive modes
---------------------
fill  – crop rect is AR-locked to the output canvas ratio; whatever fits
        inside always fills the canvas exactly (no letterboxing, no distortion).
        Corners resize proportionally; edge zones act as move handles.
zoom  – freehand rect; the selected region is scaled to *fit within* the
        output canvas while preserving the source image's own AR (letterboxed
        if needed).  No distortion of the source image — just digital zoom.
        Optional anti-upscale guard enforces a minimum rect size (≥ 1:1 px).

Non-interactive modes (fit, stretch, center) show the image with a dashed
border; the crop rect spans the whole image and is not draggable.

Signals
-------
crop_changed(x, y, w, h)  – fires on every mouse-move pixel (for overlay update)
drag_finished(x, y, w, h) – fires on mouse-release (use this to trigger re-render)
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QPainter, QPen, QColor, QPixmap, QImage,
                            QFontMetrics)

_HANDLE = 7      # corner square half-size, px
_EDGE   = 6      # px from rect edge that counts as edge hit


_CURSORS = {
    'move': Qt.CursorShape.SizeAllCursor,
    'n':    Qt.CursorShape.SizeVerCursor,
    's':    Qt.CursorShape.SizeVerCursor,
    'e':    Qt.CursorShape.SizeHorCursor,
    'w':    Qt.CursorShape.SizeHorCursor,
    'nw':   Qt.CursorShape.SizeFDiagCursor,
    'se':   Qt.CursorShape.SizeFDiagCursor,
    'ne':   Qt.CursorShape.SizeBDiagCursor,
    'sw':   Qt.CursorShape.SizeBDiagCursor,
    'draw': Qt.CursorShape.CrossCursor,
}


class FramingCanvas(QWidget):
    crop_changed  = Signal(float, float, float, float)
    drag_finished = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Source image (as QPixmap — loaded once, no Pillow on drag)
        self._px:    QPixmap | None = None
        self._src_w: int = 1
        self._src_h: int = 1
        # Output canvas target size
        self._out_w: int = 1280
        self._out_h: int = 720
        # Crop rect, normalized 0–1 relative to source image
        self._cx = 0.0
        self._cy = 0.0
        self._cw = 1.0
        self._ch = 1.0
        # Mode
        self._mode = 'fill'
        self._allow_upscale = True   # zoom mode anti-upscale guard

        # Cached image rect inside widget (recomputed on resize)
        self._img_rect = QRectF()

        # Drag state
        self._op:  str | None   = None
        self._dp:  QPointF | None = None   # widget pos at drag start
        self._dc:  tuple  | None = None    # (cx, cy, cw, ch) at drag start

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(300, 180)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_source(self, px: QPixmap | None, w: int = 0, h: int = 0):
        self._px    = px
        self._src_w = w or (px.width()  if px else 1)
        self._src_h = h or (px.height() if px else 1)
        self._update_layout()
        self.update()

    def set_output_size(self, w: int, h: int):
        self._out_w, self._out_h = max(1, w), max(1, h)
        if self._mode == 'fill':
            self._enforce_ar()
        self.update()

    def set_crop(self, x: float, y: float, w: float, h: float):
        self._cx, self._cy, self._cw, self._ch = x, y, w, h
        self.update()

    def set_mode(self, mode: str):
        prev = self._mode
        self._mode = mode
        if mode == 'fill':
            self._enforce_ar()
        elif mode in ('fit', 'stretch'):
            self._cx, self._cy, self._cw, self._ch = 0.0, 0.0, 1.0, 1.0
            self.crop_changed.emit(0, 0, 1, 1)
            self.drag_finished.emit(0, 0, 1, 1)
        self.update()

    def set_allow_upscale(self, allow: bool):
        self._allow_upscale = allow
        if not allow and self._mode == 'zoom':
            self._clamp_zoom_min()
            self._clamp()
            self.crop_changed.emit(self._cx, self._cy, self._cw, self._ch)
        self.update()

    def crop(self) -> tuple[float, float, float, float]:
        return self._cx, self._cy, self._cw, self._ch

    def snap_anchor(self, ax: float, ay: float):
        """Position crop rect at a 3×3 anchor (0/0.5/1 for L/C/R and T/C/B)."""
        self._cx = ax * (1.0 - self._cw)
        self._cy = ay * (1.0 - self._ch)
        self._clamp()
        self.crop_changed.emit(self._cx, self._cy, self._cw, self._ch)
        self.drag_finished.emit(self._cx, self._cy, self._cw, self._ch)
        self.update()

    def reset(self):
        self._cx, self._cy, self._cw, self._ch = 0.0, 0.0, 1.0, 1.0
        if self._mode == 'fill':
            self._enforce_ar()
        self.crop_changed.emit(self._cx, self._cy, self._cw, self._ch)
        self.drag_finished.emit(self._cx, self._cy, self._cw, self._ch)
        self.update()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _update_layout(self):
        ww, wh = self.width(), self.height()
        if ww <= 0 or wh <= 0 or not self._px:
            self._img_rect = QRectF(0, 0, ww, wh)
            return
        scale = min(ww / self._src_w, wh / self._src_h)
        dw = self._src_w * scale
        dh = self._src_h * scale
        self._img_rect = QRectF((ww - dw) / 2, (wh - dh) / 2, dw, dh)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_layout()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _to_widget(self, nx, ny, nw=0.0, nh=0.0) -> QRectF:
        r = self._img_rect
        return QRectF(r.x() + nx * r.width(), r.y() + ny * r.height(),
                      nw * r.width(), nh * r.height())

    def _to_norm(self, wx: float, wy: float) -> tuple[float, float]:
        r = self._img_rect
        if r.width() <= 0 or r.height() <= 0:
            return 0.0, 0.0
        return (wx - r.x()) / r.width(), (wy - r.y()) / r.height()

    def _crop_wrect(self) -> QRectF:
        return self._to_widget(self._cx, self._cy, self._cw, self._ch)

    # ------------------------------------------------------------------
    # AR / clamp helpers
    # ------------------------------------------------------------------

    def _ar_ratio(self) -> float:
        """
        The factor so that ch = cw * ar_ratio keeps pixel-AR == output-AR.
        Derivation: (cw * src_w) / (ch * src_h) = out_w / out_h
                    → ch = cw * (src_w * out_h) / (src_h * out_w)
        """
        return (self._src_w * self._out_h) / (self._src_h * self._out_w)

    def _enforce_ar(self):
        r = self._ar_ratio()
        target_ch = self._cw * r
        if target_ch > 1.0:
            self._ch = 1.0
            self._cw = 1.0 / r
        else:
            self._ch = target_ch
        self._clamp()

    def _clamp(self):
        self._cw = max(0.005, min(self._cw, 1.0))
        self._ch = max(0.005, min(self._ch, 1.0))
        self._cx = max(0.0, min(self._cx, 1.0 - self._cw))
        self._cy = max(0.0, min(self._cy, 1.0 - self._ch))

    def _clamp_zoom_min(self):
        """Prevent upscaling: selection must cover ≥ one output pixel per source pixel."""
        min_w = self._out_w / self._src_w
        min_h = self._out_h / self._src_h
        changed = False
        if self._cw < min_w:
            self._cw = min(1.0, min_w)
            changed = True
        if self._ch < min_h:
            self._ch = min(1.0, min_h)
            changed = True
        return changed

    # ------------------------------------------------------------------
    # Hit-test
    # ------------------------------------------------------------------

    def _hit(self, pos: QPointF) -> str | None:
        if self._mode in ('fit', 'stretch'):
            return None

        cr = self._crop_wrect()
        x, y = pos.x(), pos.y()

        # Outside the padded rect → draw-new if inside image area
        outer = QRectF(cr.x() - _EDGE, cr.y() - _EDGE,
                       cr.width() + 2*_EDGE, cr.height() + 2*_EDGE)
        if not outer.contains(pos):
            if self._img_rect.contains(pos):
                return 'draw'
            return None

        # Corners (checked before edges — smaller target)
        if abs(x - cr.left())  <= _HANDLE and abs(y - cr.top())    <= _HANDLE: return 'nw'
        if abs(x - cr.right()) <= _HANDLE and abs(y - cr.top())    <= _HANDLE: return 'ne'
        if abs(x - cr.left())  <= _HANDLE and abs(y - cr.bottom()) <= _HANDLE: return 'sw'
        if abs(x - cr.right()) <= _HANDLE and abs(y - cr.bottom()) <= _HANDLE: return 'se'

        # Edges — in fill mode, edges just move (AR can't be maintained by one edge)
        on_n = abs(y - cr.top())    <= _EDGE
        on_s = abs(y - cr.bottom()) <= _EDGE
        on_w = abs(x - cr.left())   <= _EDGE
        on_e = abs(x - cr.right())  <= _EDGE
        if on_n: return 'move' if self._mode == 'fill' else 'n'
        if on_s: return 'move' if self._mode == 'fill' else 's'
        if on_w: return 'move' if self._mode == 'fill' else 'w'
        if on_e: return 'move' if self._mode == 'fill' else 'e'

        if cr.contains(pos):
            return 'move'
        return 'draw' if self._img_rect.contains(pos) else None

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        op = self._hit(pos)
        if op is None:
            return
        self._op = op
        self._dp = QPointF(pos)
        self._dc = (self._cx, self._cy, self._cw, self._ch)

        if op == 'draw':
            nx, ny = self._to_norm(pos.x(), pos.y())
            nx, ny = max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))
            self._cx, self._cy = nx, ny
            self._cw, self._ch = 0.001, 0.001
            self._dc = (nx, ny, 0.001, 0.001)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._op is None:
            op = self._hit(pos)
            self.setCursor(_CURSORS.get(op, Qt.CursorShape.ArrowCursor))
            return

        r = self._img_rect
        dx = (pos.x() - self._dp.x()) / r.width()  if r.width()  > 0 else 0.0
        dy = (pos.y() - self._dp.y()) / r.height() if r.height() > 0 else 0.0
        ox, oy, ow, oh = self._dc
        op = self._op

        if op == 'move':
            self._cx = ox + dx
            self._cy = oy + dy
        elif op in ('draw', 'se'):
            self._cw = max(0.001, ow + dx)
            self._ch = max(0.001, oh + dy)
        elif op == 'nw':
            self._cw = max(0.001, ow - dx); self._cx = ox + ow - self._cw
            self._ch = max(0.001, oh - dy); self._cy = oy + oh - self._ch
        elif op == 'ne':
            self._cw = max(0.001, ow + dx)
            self._ch = max(0.001, oh - dy); self._cy = oy + oh - self._ch
        elif op == 'sw':
            self._cw = max(0.001, ow - dx); self._cx = ox + ow - self._cw
            self._ch = max(0.001, oh + dy)
        elif op == 'n':
            self._ch = max(0.001, oh - dy); self._cy = oy + oh - self._ch
        elif op == 's':
            self._ch = max(0.001, oh + dy)
        elif op == 'w':
            self._cw = max(0.001, ow - dx); self._cx = ox + ow - self._cw
        elif op == 'e':
            self._cw = max(0.001, ow + dx)

        if self._mode == 'fill':
            self._ar_lock_op(op, ox, oy, ow, oh)
        elif self._mode == 'zoom' and not self._allow_upscale:
            self._clamp_zoom_min()

        self._clamp()
        self.crop_changed.emit(self._cx, self._cy, self._cw, self._ch)
        self.update()

    def _ar_lock_op(self, op: str, ox, oy, ow, oh):
        """
        After a corner drag, enforce output AR by adjusting height from width.
        Width is treated as the "driver"; height follows.
        Corner ops keep the opposite corner fixed.
        """
        r = self._ar_ratio()
        right  = ox + ow
        bottom = oy + oh

        if op in ('draw', 'se', 'e', 's'):
            self._ch = self._cw * r
        elif op == 'nw':
            self._ch = self._cw * r
            self._cx = right  - self._cw
            self._cy = bottom - self._ch
        elif op == 'ne':
            self._ch = self._cw * r
            self._cy = bottom - self._ch
        elif op == 'sw':
            self._ch = self._cw * r
            self._cx = right  - self._cw
        # 'move', 'n', 'w' don't resize — no AR adjustment needed

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self._op = None
        self.drag_finished.emit(self._cx, self._cy, self._cw, self._ch)
        self.setCursor(_CURSORS.get(self._hit(ev.position()),
                                    Qt.CursorShape.ArrowCursor))

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        painter.fillRect(self.rect(), QColor('#111122'))

        ir = self._img_rect
        if self._px:
            painter.drawPixmap(ir.toRect(), self._px)
        else:
            # Placeholder checkerboard
            painter.fillRect(ir.toRect(), QColor('#2a2a3e'))
            painter.setPen(QColor('#44445a'))
            painter.drawText(ir.toRect(), Qt.AlignmentFlag.AlignCenter,
                             "No image\nOpen or paste one")

        if self._mode in ('fit', 'stretch'):
            pen = QPen(QColor('#8b5cf6'), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ir.adjusted(0, 0, -1, -1))
            painter.end()
            return

        cr = self._crop_wrect()

        # Darken the area outside the crop rect (4 rects around it)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        _fill_around(painter, ir, cr)

        # Rule-of-thirds grid
        painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
        for i in (1, 2):
            gx = cr.x() + cr.width()  * i / 3
            gy = cr.y() + cr.height() * i / 3
            painter.drawLine(QPointF(gx, cr.y()), QPointF(gx, cr.bottom()))
            painter.drawLine(QPointF(cr.x(), gy), QPointF(cr.right(), gy))

        # Crop rect border
        painter.setPen(QPen(QColor('#8b5cf6'), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(cr)

        # Corner drag handles
        hs = _HANDLE
        painter.setPen(QPen(QColor('#c4b5fd'), 1))
        painter.setBrush(QColor('#8b5cf6'))
        for hx, hy in (
            (cr.left(),  cr.top()),    (cr.right(), cr.top()),
            (cr.left(),  cr.bottom()), (cr.right(), cr.bottom()),
        ):
            painter.drawRect(QRectF(hx - hs, hy - hs, hs * 2, hs * 2))

        # Zoom-mode info label (zoom factor / upscale warning)
        if self._mode == 'zoom':
            self._paint_zoom_label(painter, cr)

        painter.end()

    def _paint_zoom_label(self, painter: QPainter, cr: QRectF):
        if self._cw < 0.01 or self._ch < 0.01:
            return
        # Pixels of source covered per output pixel (>1 = downscale = quality OK)
        coverage_x = (self._cw * self._src_w) / self._out_w
        coverage_y = (self._ch * self._src_h) / self._out_h
        # The limiting axis determines quality
        coverage = min(coverage_x, coverage_y)
        if coverage < 1.0:
            label = f"⚠ ×{1/coverage:.1f} upscale"
            fg = QColor('#fbbf24')
        else:
            label = f"×{coverage:.2f} zoom"
            fg = QColor('#4ade80')

        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        tx = int(cr.right()) - tw - 6
        ty = int(cr.bottom()) - 4

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(tx - 4, ty - fm.ascent() - 3, tw + 8,
                                fm.height() + 6, 3, 3)
        painter.setPen(fg)
        painter.drawText(tx, ty, label)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill_around(painter: QPainter, outer: QRectF, inner: QRectF):
    """Fill the area of outer that is not covered by inner with the current brush."""
    top    = QRectF(outer.x(), outer.y(),      outer.width(), inner.y() - outer.y())
    bottom = QRectF(outer.x(), inner.bottom(), outer.width(), outer.bottom() - inner.bottom())
    left   = QRectF(outer.x(), inner.y(),      inner.x() - outer.x(),    inner.height())
    right  = QRectF(inner.right(), inner.y(),  outer.right() - inner.right(), inner.height())
    for r in (top, bottom, left, right):
        if r.width() > 0 and r.height() > 0:
            painter.drawRect(r)
