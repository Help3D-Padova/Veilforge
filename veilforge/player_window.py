from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QImage, QPen, QColor, QIcon, QPainterPath
from PyQt6.QtWidgets import QWidget

from pathlib import Path
from .drawings import Stroke
import math


class PlayerWindow(QWidget):
    """
    Player projection window.

    It renders a *map-space* viewport defined by:
      - center (map coords)
      - zoom  (map-px to widget-px multiplier)

    This keeps fog/grid/annotations perfectly aligned while panning/zooming.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Veilforge – Fog of War (Player)")

        # Best-effort icon (no crash if missing)
        try:
            root = Path(__file__).resolve().parent.parent
            ico = root / "assets" / "veilforge.ico"
            png = root / "assets" / "veilforge.png"
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
            elif png.exists():
                self.setWindowIcon(QIcon(str(png)))
        except Exception:
            pass

        self.map_img: QImage | None = None
        self.mask_img: QImage | None = None

        # grid
        self.show_grid = False
        self.grid_type = "None"
        self.grid_cell_map_px = 70
        self.grid_alpha = 130

        # drawings
        self.drawings: list[Stroke] = []

        # view
        self._zoom = 1.0
        self._center = QPointF(0.0, 0.0)

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # -------- API called by MainWindow --------
    def set_images(self, map_img: QImage | None, mask_img: QImage | None):
        self.map_img = map_img
        self.mask_img = mask_img
        if self.map_img:
            self._center = QPointF(self.map_img.width() / 2.0, self.map_img.height() / 2.0)
        else:
            self._center = QPointF(0.0, 0.0)
        self.update()

    def set_drawings(self, drawings: list[Stroke]):
        self.drawings = drawings or []
        self.update()

    def set_grid(self, show: bool, grid_type: str, cell_map_px: int, alpha: int):
        self.show_grid = bool(show)
        self.grid_type = str(grid_type)
        self.grid_cell_map_px = max(5, int(cell_map_px))
        self.grid_alpha = max(0, min(255, int(alpha)))
        self.update()

    def set_view(self, a, b=None):
        """
        Backwards/forwards compatible signature:

        - set_view(zoom: float, center_map: QPointF)
        - set_view(center_map: QPointF, zoom: float)  (older call order)
        - set_view(None, None) -> reset (fit-ish default)
        """
        if a is None or b is None:
            # keep current center if we have a map; just reset zoom
            self._zoom = 1.0
            self.update()
            return

        zoom = None
        center = None

        if isinstance(a, QPointF):
            center = a
            zoom = float(b)
        elif isinstance(b, QPointF):
            zoom = float(a)
            center = b
        else:
            # last resort: try interpret (zoom, (x,y))
            zoom = float(a)
            if isinstance(b, (tuple, list)) and len(b) == 2:
                center = QPointF(float(b[0]), float(b[1]))

        if zoom is None or center is None or zoom <= 0:
            self._zoom = 1.0
            self.update()
            return

        self._zoom = float(zoom)
        self._center = QPointF(float(center.x()), float(center.y()))
        self.update()

    # -------- internals --------
    def _src_rect(self) -> QRectF:
        if not self.map_img or self.width() <= 0 or self.height() <= 0 or self._zoom <= 0:
            return QRectF()
        w_map = float(self.width()) / self._zoom
        h_map = float(self.height()) / self._zoom
        cx = float(self._center.x())
        cy = float(self._center.y())
        return QRectF(cx - w_map / 2.0, cy - h_map / 2.0, w_map, h_map)

    def _clamp_center(self):
        if not self.map_img or self._zoom <= 0:
            return
        w_map = float(self.width()) / self._zoom
        h_map = float(self.height()) / self._zoom
        if w_map <= 0 or h_map <= 0:
            return
        half_w = w_map / 2.0
        half_h = h_map / 2.0
        max_x = float(self.map_img.width()) - half_w
        max_y = float(self.map_img.height()) - half_h
        min_x = half_w
        min_y = half_h
        cx = min(max(float(self._center.x()), min_x), max_x) if max_x >= min_x else float(self.map_img.width()) / 2.0
        cy = min(max(float(self._center.y()), min_y), max_y) if max_y >= min_y else float(self.map_img.height()) / 2.0
        self._center = QPointF(cx, cy)

    def clear_annotations(self):
        self.drawings.clear()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0))

        if not self.map_img:
            p.end()
            return

        self._clamp_center()
        src = self._src_rect()
        if src.isNull():
            p.end()
            return

        target = QRectF(self.rect())        # draw map
        p.drawImage(target, self.map_img, src)

        # draw grid (optional) — keep it UNDER the fog so it doesn't appear on blacked-out areas
        if self.show_grid and self.grid_type in ("Square", "Hex"):
            pen = QPen(QColor(255, 255, 255, self.grid_alpha), 1)
            p.setPen(pen)
            self._draw_grid(p, src)

        # drawings/annotations — draw them BEFORE fog so fog hides them where it's still black
        # (clip to map area so strokes don't spill into black bars)
        if self.drawings:
            p.save()
            p.setClipRect(target.adjusted(2, 2, -2, -2))  # avoid edge leakage
            self._draw_strokes(p, src)
            p.restore()

        # draw fog mask LAST (same src) so it covers both grid and annotations in fogged areas
        if self.mask_img:
            p.save()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawImage(QRectF(self.rect()), self.mask_img, src)
            p.restore()

        p.end()
    def _mx_to_wx(self, mx: float, src: QRectF) -> float:
        return (mx - src.left()) * (self.width() / src.width())

    def _my_to_wy(self, my: float, src: QRectF) -> float:
        return (my - src.top()) * (self.height() / src.height())

    def _draw_grid(self, p: QPainter, src: QRectF):
        cell = float(self.grid_cell_map_px)
        if cell <= 1:
            return
        if self.grid_type == "Square":
            x0 = math.floor(src.left() / cell) * cell
            x1 = src.right()
            y0 = math.floor(src.top() / cell) * cell
            y1 = src.bottom()
            x = x0
            while x <= x1:
                wx = self._mx_to_wx(x, src)
                p.drawLine(int(wx), 0, int(wx), self.height())
                x += cell
            y = y0
            while y <= y1:
                wy = self._my_to_wy(y, src)
                p.drawLine(0, int(wy), self.width(), int(wy))
                y += cell
        else:
            # Hex (pointy top), same as DMCanvas maths in map coords
            r = cell / 2.0
            if r <= 2:
                return
            dx = math.sqrt(3) * r
            dy = 1.5 * r
            first_row = int(math.floor(src.top() / dy)) - 2
            last_row = int(math.ceil(src.bottom() / dy)) + 2
            scale = self.width() / src.width()
            for row in range(first_row, last_row + 1):
                cy = row * dy
                x_off = (dx / 2.0) if (row % 2) else 0.0
                col0 = int(math.floor((src.left() - x_off) / dx)) - 2
                col1 = int(math.ceil((src.right() - x_off) / dx)) + 2
                for col in range(col0, col1 + 1):
                    cx = x_off + col * dx
                    wx = self._mx_to_wx(cx, src)
                    wy = self._my_to_wy(cy, src)
                    self._draw_hex(p, wx, wy, r * scale)

    def _draw_hex(self, p: QPainter, cx: float, cy: float, r: float):
        pts = []
        for i in range(6):
            ang = math.radians(60 * i - 30)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for i in range(6):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % 6]
            p.drawLine(int(x0), int(y0), int(x1), int(y1))


    def _chaikin(self, pts: list[tuple[float, float]], iters: int = 2) -> list[tuple[float, float]]:
        if iters <= 0 or len(pts) < 3:
            return pts
        out = pts
        for _ in range(iters):
            new_pts = [out[0]]
            for i in range(len(out) - 1):
                x0, y0 = out[i]
                x1, y1 = out[i + 1]
                qx = 0.75 * x0 + 0.25 * x1
                qy = 0.75 * y0 + 0.25 * y1
                rx = 0.25 * x0 + 0.75 * x1
                ry = 0.25 * y0 + 0.75 * y1
                new_pts.append((qx, qy))
                new_pts.append((rx, ry))
            new_pts.append(out[-1])
            out = new_pts
        return out

    def _dash_pen(self, color: QColor, width_px: int, dash: str) -> QPen:
        pen = QPen(color)
        pen.setWidth(max(1, int(width_px)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dash == "Dashed":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([10.0, 6.0])
        elif dash == "Dotted":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([1.0, 5.0])
        else:
            pen.setStyle(Qt.PenStyle.SolidLine)
        return pen

    def _smooth_path(self, pts: list[tuple[float, float]], src: QRectF) -> QPainterPath:
        # map coords -> widget coords, then quadratic smoothing
        def to_w(xm: float, ym: float) -> QPointF:
            x = (xm - src.left()) * (self.width() / src.width())
            y = (ym - src.top()) * (self.height() / src.height())
            return QPointF(float(x), float(y))

        pts = self._chaikin(pts, iters=2)
        x0, y0 = pts[0]
        p0 = to_w(float(x0), float(y0))
        path = QPainterPath(p0)

        for i in range(1, len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            mx = (float(x1) + float(x2)) / 2.0
            my = (float(y1) + float(y2)) / 2.0
            path.quadTo(to_w(float(x1), float(y1)), to_w(mx, my))

        xl, yl = pts[-1]
        path.lineTo(to_w(float(xl), float(yl)))
        return path

    def _draw_strokes(self, p: QPainter, src: QRectF):
        if src.width() <= 0 or src.height() <= 0:
            return

        # scale stroke width with zoom so it matches DM feel
        scale = self.width() / src.width()

        for s in self.drawings:
            if not s.points or len(s.points) < 2:
                continue
            r, g, b, a = s.color
            col = QColor(r, g, b, a)
            pen = self._dash_pen(col, int(s.width * scale), s.dash)
            p.setPen(pen)
            p.drawPath(self._smooth_path(s.points, src))
