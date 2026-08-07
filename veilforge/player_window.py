from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QPointF, QUrl
from PyQt6.QtGui import QPainter, QImage, QPen, QColor, QIcon, QPainterPath
from PyQt6.QtWidgets import QWidget
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink

from pathlib import Path
from .drawings import Stroke
import math
import time


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

        # Video playback support for player window (for map videos).
        # We render video frames via QVideoSink directly in paintEvent so grid/fog
        # are always visible above video across platforms.
        self.video_player: QMediaPlayer | None = None
        self.audio_output: QAudioOutput | None = None
        self.video_sink: QVideoSink | None = None
        self.video_frame_img: QImage | None = None
        self.video_active = False
        self.external_video_stream = False
        self._video_grid_cache: QImage | None = None
        self._video_grid_cache_key: tuple | None = None
        # Video frame optimization: throttling + downscaling
        self._last_video_frame_time = 0.0
        self._min_video_frame_interval = 0.04  # ~25fps throttle (minimum for smooth playback)
        self._max_video_display_width = 2560  # Downscale 4K to this width max

        # grid
        self.show_grid = False
        self.grid_type = "None"
        self.grid_cell_map_px = 70
        self.grid_alpha = 130

        # drawings
        self.drawings: list[Stroke] = []

        # tokens (map-space sprites)
        self.tokens: list[dict] = []

        # view
        self._zoom = 1.0
        self._center = QPointF(0.0, 0.0)

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # -------- API called by MainWindow --------
    def set_images(self, map_img: QImage | None, mask_img: QImage | None):
        """Set the current map image and fog mask for the Player.

        - `map_img`: QImage to render as the background map (None if playing video).
        - `mask_img`: QImage containing the fog mask. If `None`, no fog is shown.

        When a video is active the fog mask is rendered directly in `paintEvent`
        on top of the latest frame received from `QVideoSink`.
        """
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

    def set_tokens(self, tokens: list[dict]):
        self.tokens = tokens or []
        self.update()

    def set_grid(self, show: bool, grid_type: str, cell_map_px: int, alpha: int):
        """Update grid settings for Player view.

        In image mode, grid is drawn in `paintEvent` using map-space coordinates.
        In video mode, grid is drawn by `VideoOverlay` in widget coordinates.
        """
        self.show_grid = bool(show)
        self.grid_type = str(grid_type)
        self.grid_cell_map_px = max(5, int(cell_map_px))
        self.grid_alpha = max(0, min(255, int(alpha)))
        self._video_grid_cache = None
        self._video_grid_cache_key = None
        self.update()

    def _ensure_video_grid_cache(self):
        key = (self.width(), self.height(), self.show_grid, self.grid_type, self.grid_cell_map_px, self.grid_alpha)
        if self._video_grid_cache is not None and self._video_grid_cache_key == key:
            return

        self._video_grid_cache_key = key
        self._video_grid_cache = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_RGBA8888)
        self._video_grid_cache.fill(QColor(0, 0, 0, 0))

        if not (self.show_grid and self.grid_type in ("Square", "Hex")):
            return

        p = QPainter(self._video_grid_cache)
        try:
            pen = QPen(QColor(255, 255, 255, self.grid_alpha), 1)
            p.setPen(pen)
            cell = max(5.0, float(self.grid_cell_map_px))
            if self.grid_type == "Square":
                x = 0.0
                while x <= self.width():
                    p.drawLine(int(x), 0, int(x), self.height())
                    x += cell
                y = 0.0
                while y <= self.height():
                    p.drawLine(0, int(y), self.width(), int(y))
                    y += cell
            else:
                r = cell / 2.0
                dx = math.sqrt(3.0) * r
                dy = 1.5 * r
                first_row = -2
                last_row = int(math.ceil(self.height() / dy)) + 2
                for row in range(first_row, last_row + 1):
                    cy = row * dy
                    x_off = (dx / 2.0) if (row % 2) else 0.0
                    col0 = -2
                    col1 = int(math.ceil(self.width() / dx)) + 2
                    for col in range(col0, col1 + 1):
                        cx = x_off + col * dx
                        self._draw_hex(p, cx, cy, r)
        finally:
            p.end()

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

    # Video control API for MainWindow
    def play_video(self, path: str):
        """Start video playback on the Player window and enable overlay.

        The overlay widget is positioned over the `QVideoWidget` and will draw
        the current fog mask (if provided by `set_images`). This method creates
        a new `QMediaPlayer` and `QAudioOutput` for playback and attempts to
        loop the video where supported.
        """
        try:
            self.stop_video()
            self.external_video_stream = False
            self.video_active = True
            self.video_player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.video_sink = QVideoSink(self)
            self.audio_output.setVolume(1.0)
            self.video_player.setVideoOutput(self.video_sink)
            self.video_player.setAudioOutput(self.audio_output)
            self.video_sink.videoFrameChanged.connect(
                lambda frame: self._on_video_frame(frame.toImage())
            )
            self.video_player.setSource(QUrl.fromLocalFile(path))
            if hasattr(self.video_player, 'setLoops') and hasattr(self.video_player, 'Loops'):
                try:
                    self.video_player.setLoops(self.video_player.Loops.Infinite)
                except Exception:
                    pass
            self.video_player.play()
            self.update()
        except Exception:
            pass

    def stop_video(self):
        """Stop playback and hide the video overlay/widget.

        Cleans up the `QMediaPlayer` and hides the overlay so subsequent calls to
        `set_images` will render the static map path instead.
        """
        try:
            self.video_active = False
            self.external_video_stream = False
            if self.video_player is not None:
                try:
                    self.video_player.stop()
                except Exception:
                    pass
                self.video_player.deleteLater()
                self.video_player = None
            if self.audio_output is not None:
                self.audio_output = None
            self.video_sink = None
            self.video_frame_img = None
            self._video_grid_cache = None
            self._video_grid_cache_key = None
            self.update()
        except Exception:
            pass

    def use_external_video_stream(self, enabled: bool):
        """Enable/disable external video frame feeding from MainWindow.

        When enabled, PlayerWindow does not decode video itself and expects
        frames via `set_external_video_frame`.
        """
        self.external_video_stream = bool(enabled)
        self.video_active = bool(enabled)
        if enabled:
            # Ensure no local decoder stays active.
            if self.video_player is not None:
                try:
                    self.video_player.stop()
                except Exception:
                    pass
                self.video_player.deleteLater()
                self.video_player = None
            self.video_sink = None
            self.audio_output = None
        self.update()

    def set_external_video_frame(self, img: QImage | None):
        if not self.external_video_stream:
            return
        self.video_frame_img = img if img is not None and not img.isNull() else None
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._video_grid_cache = None
        self._video_grid_cache_key = None

    def _on_video_frame(self, img: QImage):
        # Throttle frame updates to ~25fps (minimum for smooth playback)
        now = time.time()
        if now - self._last_video_frame_time < self._min_video_frame_interval:
            return
        self._last_video_frame_time = now
        
        # FAST downscale if needed (FastTransformation for speed, not quality)
        # This uses simple nearest-neighbor for speed, good enough at 25fps
        if img is not None and not img.isNull() and img.width() > self._max_video_display_width:
            img = img.scaledToWidth(
                self._max_video_display_width,
                Qt.TransformationMode.FastTransformation
            )
        
        self.video_frame_img = img if img is not None and not img.isNull() else None
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0))

        # Video mode: draw latest frame + grid + fog overlay in widget-space.
        if self.video_active:
            if self.video_frame_img is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                p.drawImage(QRectF(self.rect()), self.video_frame_img)

            self._ensure_video_grid_cache()
            if self._video_grid_cache is not None:
                p.drawImage(QRectF(self.rect()), self._video_grid_cache)

            if self.mask_img:
                p.drawImage(QRectF(self.rect()), self.mask_img)
            p.end()
            return

        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if not self.map_img:
            p.end()
            return

        self._clamp_center()
        src = self._src_rect()
        if src.isNull():
            p.end()
            return

        target = QRectF(self.rect())

        # draw map
        p.drawImage(target, self.map_img, src)

        # If src goes outside the image, Qt will draw only the intersecting part and leave black bars.
        # Compute the *actual* on-screen rect covered by the map so we can clip grid/annotations to it.
        img_bounds = QRectF(0.0, 0.0, float(self.map_img.width()), float(self.map_img.height()))
        src_i = src.intersected(img_bounds)
        if src_i.isNull():
            p.end()
            return

        # Map src_i (map coords) to widget coords inside the full target rect.
        sx = (src_i.left() - src.left()) / src.width()
        sy = (src_i.top() - src.top()) / src.height()
        sw = src_i.width() / src.width()
        sh = src_i.height() / src.height()
        map_target = QRectF(
            target.left() + sx * target.width(),
            target.top() + sy * target.height(),
            sw * target.width(),
            sh * target.height(),
        )

        # draw grid (optional) — clip to the visible map area (avoid grid on black bars)
        if self.show_grid and self.grid_type in ("Square", "Hex"):
            pen = QPen(QColor(255, 255, 255, self.grid_alpha), 1)
            p.setPen(pen)
            p.save()
            p.setClipRect(map_target.adjusted(2, 2, -2, -2))  # avoid edge leakage
            self._draw_grid(p, src)
            p.restore()

        # drawings/annotations — clip to visible map area
        if self.drawings:
            p.save()
            p.setClipRect(map_target.adjusted(2, 2, -2, -2))  # avoid edge leakage
            self._draw_strokes(p, src)
            p.restore()

        # tokens (draw before fog so fog can hide undiscovered tokens)
        if self.tokens:
            p.save()
            p.setClipRect(map_target.adjusted(2, 2, -2, -2))
            self._draw_tokens(p, src)
            p.restore()

        # draw fog mask LAST (same src) so it covers grid + annotations in fogged areas
        if self.mask_img:
            p.drawImage(QRectF(self.rect()), self.mask_img, src)
        p.end()

    def _draw_tokens(self, p: QPainter, src: QRectF):
        if not self.tokens or src.width() <= 0 or src.height() <= 0:
            return
        target = QRectF(self.rect())
        for t in self.tokens:
            img = t.get("img")
            if img is None or img.isNull():
                continue

            tx = float(t["cx"])
            ty = float(t["cy"])
            tw = float(t["w"])
            th = float(t["h"])
            ta = float(t.get("angle", 0.0))

            u = (tx - src.left()) / src.width()
            v = (ty - src.top()) / src.height()
            uw = tw / src.width()
            vh = th / src.height()

            cxw = target.left() + u * target.width()
            cyw = target.top() + v * target.height()
            ww = uw * target.width()
            hh = vh * target.height()

            p.save()
            p.translate(cxw, cyw)
            p.rotate(ta)
            p.drawImage(QRectF(-ww / 2.0, -hh / 2.0, ww, hh), img)
            p.restore()

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
