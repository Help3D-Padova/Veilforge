from __future__ import annotations

import math
from PyQt6.QtCore import Qt, QRectF, QPoint, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPainter, QImage, QPen, QColor, QBrush, QPainterPath, QRadialGradient, QCursor, QPixmap
)
from PyQt6.QtWidgets import QWidget, QMenu

from .drawings import Stroke


class DMCanvas(QWidget):
    maskChanged = pyqtSignal()
    drawingsChanged = pyqtSignal()
    tokensChanged = pyqtSignal()
    gridCalibrated = pyqtSignal(str, int)
    playerViewCenterChanged = pyqtSignal(QPointF)  # emitted when dragging Player view overlay
    # Emitted whenever DM zoom/pan changes.
    # Payload: map_w, map_h, left, top, vis_w, vis_h, zoom
    viewChanged = pyqtSignal(float, float, float, float, float, float, float)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._map: QImage | None = None
        self.mask_img: QImage | None = None

        self.brush_radius = 40
        self.brush_softness = 0.2  # 0..1
        self.dm_fog_alpha = 140

        self.last_mouse_pos: QPoint | None = None
        self._fit_rect = QRectF()

        # DM-only zoom (player stays 1:1 fit)
        self._zoom = 1.0
        self._zoom_min = 1.0
        self._zoom_max = 8.0
        self._view_center = QPointF(0.0, 0.0)   # map coords
        self._last_view_state: tuple[float, float, float, float, float, float, float] | None = None

        # grid calibration
        self._grid_calib_active = False
        self._grid_calib_type = "Square"
        self._grid_calib_pts: list[QPoint] = []

        # annotate snapping (kept for compatibility; can be ignored in UI)
        self.snap_to_grid = False

        # player view overlay (DM): rectangle showing Player viewport in map-space
        self._player_overlay_enabled = False
        self._player_overlay_center = QPointF(0.0, 0.0)   # map coords
        self._player_overlay_zoom = None                  # float
        self._player_overlay_vw = 0                       # player viewport width in pixels
        self._player_overlay_vh = 0                       # player viewport height in pixels

        self._drag_player_overlay = False
        self._drag_player_anchor_map = QPointF(0.0, 0.0)
        self._drag_player_anchor_center = QPointF(0.0, 0.0)

        # panning state (MMB drag)
        self._panning = False
        self._pan_last_pos: QPoint | None = None

        self._undo: list[QImage] = []
        self._redo: list[QImage] = []
        self._max_undo = 40

        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.timeout.connect(self.maskChanged.emit)

        self.show_grid = False
        self.grid_type = "None"
        self.grid_cell_map_px = 70
        self.grid_alpha = 130

        # annotate
        self.annotate_enabled = False
        self.draw_color = (255, 0, 0, 255)
        self.draw_width = 4
        self.draw_dash = "Solid"
        self._drawing_active = False
        self._current_stroke: Stroke | None = None
        self._stroke_id = 1
        self.drawings: list[Stroke] = []

        # tokens (map-space sprites shown on top of map)
        self.tokens: list[dict] = []
        self.selected_token_index: int = -1
        self.token_tool_enabled = False
        self._drag_token = False
        self._token_drag_mode: str | None = None  # move | resize | rotate
        self._drag_token_offset = QPointF(0.0, 0.0)
        self._token_resize_start_w = 0.0
        self._token_resize_start_h = 0.0
        self._token_handle_radius_px = 9.0
        self._token_handle_hit_px = 16.0
        self._token_rotate_hit_px = 28.0
        self._token_hover_mode: str | None = None
        self._token_clipboard: dict | None = None
        self._token_forced_mode: str | None = None
        self._token_rotate_cursor = self._build_rotate_cursor()
        self._token_resize_cursor = QCursor(Qt.CursorShape.SizeFDiagCursor)

    def set_token_tool_enabled(self, enabled: bool):
        """Toggle token manipulation mode.

        In token tool mode, mouse input is reserved for token selection and
        transform handles (move/resize/rotate), not fog painting.
        """
        self.token_tool_enabled = bool(enabled)
        if not self.token_tool_enabled:
            self._drag_token = False
            self._token_drag_mode = None
            self._set_token_hover_cursor(None)
        self.update()

    def _build_rotate_cursor(self) -> QCursor:
        """Create a small circular-arrow cursor used on rotate handle hover."""
        size = 24
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 245), 2))
        p.drawArc(5, 5, 14, 14, 25 * 16, 285 * 16)
        p.drawLine(16, 7, 19, 7)
        p.drawLine(16, 7, 16, 10)
        p.end()
        return QCursor(pm, 12, 12)

    def _set_token_hover_cursor(self, mode: str | None):
        """Apply hover cursor while using token tool handles."""
        if mode == self._token_hover_mode:
            return
        self._token_hover_mode = mode
        if mode == "rotate":
            self.setCursor(self._token_rotate_cursor)
        elif mode == "resize":
            self.setCursor(self._token_resize_cursor)
        else:
            self.unsetCursor()

    def _show_token_context_menu(self, widget_pos: QPoint):
        """Show token context menu (English labels) on right-click.

        Rotate/Resize arm the same drag modes used by token handles.
        Copy/Paste/Delete/Duplicate and z-order actions reuse the same internal
        token operations as keyboard shortcuts and normal manipulation.
        """
        menu = QMenu(self)
        act_rotate = menu.addAction("Rotate")
        act_resize = menu.addAction("Resize")
        menu.addSeparator()
        act_copy = menu.addAction("Copy")
        act_paste = menu.addAction("Paste")
        menu.addSeparator()
        act_delete = menu.addAction("Delete")

        has_selected = 0 <= self.selected_token_index < len(self.tokens)
        can_paste = (self._map is not None) and (self._token_clipboard is not None)

        act_rotate.setEnabled(has_selected)
        act_resize.setEnabled(has_selected)
        act_copy.setEnabled(has_selected)
        act_delete.setEnabled(has_selected)
        act_paste.setEnabled(can_paste)

        chosen = menu.exec(self.mapToGlobal(widget_pos))
        if chosen == act_rotate:
            self._token_forced_mode = "rotate"
            self._set_token_hover_cursor("rotate")
        elif chosen == act_resize:
            self._token_forced_mode = "resize"
            self._set_token_hover_cursor("resize")
        elif chosen == act_copy:
            self.copy_selected_token()
        elif chosen == act_paste:
            self.paste_token()
        elif chosen == act_delete:
            self.remove_selected_token()

    # ---------------- Public API ----------------

    def start_grid_calibration(self, grid_type: str):
        # hide old grid while calibrating (so points are selectable)
        self._grid_calib_active = True
        # dedicated cursor for calibration (no brush)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._grid_calib_type = grid_type
        self._grid_calib_pts = []
        self.show_grid = False
        self.update()

    def cancel_grid_calibration(self):
        self._grid_calib_active = False
        self.unsetCursor()
        self._grid_calib_pts = []
        self.update()

    def set_grid(self, show: bool, grid_type: str, cell_map_px: int, alpha: int):
        self.show_grid = bool(show)
        self.grid_type = grid_type
        self.grid_cell_map_px = max(5, int(cell_map_px))
        self.grid_alpha = max(0, min(255, int(alpha)))
        self.update()

    def set_annotate(self, enabled: bool):
        self.annotate_enabled = bool(enabled)
        self._drawing_active = False
        self._current_stroke = None
        self.update()

    def set_snap_to_grid(self, enabled: bool):
        self.snap_to_grid = bool(enabled)
    def set_draw_style(self, color_rgba: tuple[int, int, int, int], width: int, dash: str):
        self.draw_color = color_rgba
        self.draw_width = max(1, int(width))
        self.draw_dash = dash

    def set_images(self, map_img: QImage | None, mask_img: QImage | None, drawings: list[Stroke] | None = None):
        self._map = map_img
        self.mask_img = mask_img

        # reset zoom/pan on new map
        self._zoom = 1.0
        if self._map:
            self._view_center = QPointF(self._map.width() / 2.0, self._map.height() / 2.0)
        else:
            self._view_center = QPointF(0.0, 0.0)

        # cancel grid calibration
        self._grid_calib_active = False
        self._grid_calib_pts.clear()
        self._undo.clear()
        self._redo.clear()

        self.drawings = drawings or []
        self._stroke_id = 1 + max([s.id for s in self.drawings], default=0)
        self.tokens = []
        self.selected_token_index = -1

        self.update()
        self._schedule_emit()
        self.drawingsChanged.emit()
        self.tokensChanged.emit()
        self._emit_view_changed(force=True)

    def add_token_image(self, img: QImage):
        """Add a new token centered on the map with a safe default size."""
        if self._map is None or img is None or img.isNull():
            return

        # Keep token size reasonable for tabletop maps.
        max_side = 96
        iw, ih = img.width(), img.height()
        if max(iw, ih) > max_side:
            img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        cx = float(self._map.width() / 2.0)
        cy = float(self._map.height() / 2.0)
        self.tokens.append({
            "img": img,
            "cx": cx,
            "cy": cy,
            "w": float(img.width()),
            "h": float(img.height()),
            "angle": 0.0,
        })
        self.selected_token_index = len(self.tokens) - 1
        self.tokensChanged.emit()
        self.update()

    def remove_selected_token(self):
        """Delete the currently selected token, if any."""
        if self.selected_token_index < 0 or self.selected_token_index >= len(self.tokens):
            return
        self.tokens.pop(self.selected_token_index)
        self.selected_token_index = -1
        self.tokensChanged.emit()
        self.update()

    def copy_selected_token(self) -> bool:
        """Copy selected token into an internal clipboard.

        This is used by Ctrl+C and by the token context menu.
        """
        i = self.selected_token_index
        if i < 0 or i >= len(self.tokens):
            return False
        t = self.tokens[i]
        img = t.get("img")
        if img is None or img.isNull():
            return False
        self._token_clipboard = {
            "img": img.copy(),
            "w": float(t["w"]),
            "h": float(t["h"]),
            "angle": float(t.get("angle", 0.0)),
        }
        return True

    def paste_token(self) -> bool:
        """Paste a copied token as a new token, slightly offset from selection.

        This is used by Ctrl+V and by the token context menu.
        """
        if self._map is None or self._token_clipboard is None:
            return False

        src = self._token_clipboard
        w = max(16.0, float(src["w"]))
        h = max(16.0, float(src["h"]))

        if 0 <= self.selected_token_index < len(self.tokens):
            base = self.tokens[self.selected_token_index]
            cx = float(base["cx"]) + 24.0
            cy = float(base["cy"]) + 24.0
        else:
            cx = float(self._map.width()) / 2.0
            cy = float(self._map.height()) / 2.0

        cx = max(0.0, min(cx, float(self._map.width())))
        cy = max(0.0, min(cy, float(self._map.height())))

        self.tokens.append({
            "img": src["img"].copy(),
            "cx": cx,
            "cy": cy,
            "w": w,
            "h": h,
            "angle": float(src.get("angle", 0.0)),
        })
        self.selected_token_index = len(self.tokens) - 1
        self.tokensChanged.emit()
        self.update()
        return True

    def _hit_token_index(self, mp: QPoint) -> int | None:
        """Return top-most token index under a map-space point."""
        mx = float(mp.x())
        my = float(mp.y())
        for i in range(len(self.tokens) - 1, -1, -1):
            t = self.tokens[i]
            cx = float(t["cx"])
            cy = float(t["cy"])
            w = float(t["w"])
            h = float(t["h"])
            a = math.radians(float(t.get("angle", 0.0)))

            dx = mx - cx
            dy = my - cy
            # inverse rotate point around center
            lx = dx * math.cos(-a) - dy * math.sin(-a)
            ly = dx * math.sin(-a) + dy * math.cos(-a)
            if abs(lx) <= w / 2.0 and abs(ly) <= h / 2.0:
                return i
        return None

    def _hit_token_handle(self, wp: QPoint) -> tuple[int, str] | None:
        """Return (token_index, mode) when clicking resize/rotate handles.

        Hit-testing is done in widget-space pixels to keep handle interaction
        reliable at any zoom level and easier to click.
        """
        wx = float(wp.x())
        wy = float(wp.y())
        hit_tol = max(float(self._token_handle_hit_px), float(self._token_handle_radius_px) + 4.0)
        rotate_hit_tol = max(float(self._token_rotate_hit_px), hit_tol)
        for i in range(len(self.tokens) - 1, -1, -1):
            t = self.tokens[i]
            rz = self._map_to_widget_f(self._token_resize_handle_map(t))
            rr = self._map_to_widget_f(self._token_rotate_handle_map(t))
            d_rotate = math.hypot(wx - float(rr.x()), wy - float(rr.y()))
            if d_rotate <= rotate_hit_tol:
                return (i, "rotate")
            d_resize = math.hypot(wx - float(rz.x()), wy - float(rz.y()))
            if d_resize <= hit_tol:
                return (i, "resize")
        return None

    def _token_resize_handle_map(self, t: dict) -> QPointF:
        # top-right corner in token local coords
        w = float(t["w"])
        h = float(t["h"])
        a = math.radians(float(t.get("angle", 0.0)))
        x = w / 2.0
        y = -h / 2.0
        rx = x * math.cos(a) - y * math.sin(a)
        ry = x * math.sin(a) + y * math.cos(a)
        return QPointF(float(t["cx"]) + rx, float(t["cy"]) + ry)

    def _token_rotate_handle_map(self, t: dict) -> QPointF:
        w = float(t["w"])
        h = float(t["h"])
        a = math.radians(float(t.get("angle", 0.0)))
        # above top center
        x = 0.0
        y = -h / 2.0 - max(18.0, min(40.0, 0.15 * max(w, h)))
        rx = x * math.cos(a) - y * math.sin(a)
        ry = x * math.sin(a) + y * math.cos(a)
        return QPointF(float(t["cx"]) + rx, float(t["cy"]) + ry)

    def ensure_mask(self):
        if self._map and (self.mask_img is None or self.mask_img.size() != self._map.size()):
            self.mask_img = QImage(self._map.size(), QImage.Format.Format_RGBA8888)
            self.mask_img.fill(QColor(0, 0, 0, 255))

    def push_undo(self):
        if self.mask_img is None:
            return
        self._undo.append(self.mask_img.copy())
        if len(self._undo) > self._max_undo:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo or self.mask_img is None:
            return
        self._redo.append(self.mask_img.copy())
        self.mask_img = self._undo.pop()
        self.update()
        self._schedule_emit()

    def redo(self):
        if not self._redo or self.mask_img is None:
            return
        self._undo.append(self.mask_img.copy())
        self.mask_img = self._redo.pop()
        self.update()
        self._schedule_emit()

    def reset_fog(self):
        self.ensure_mask()
        if self.mask_img:
            self.push_undo()
            self.mask_img.fill(QColor(0, 0, 0, 255))
            self.update()
            self._schedule_emit()

    def reset_zoom(self):
        self._zoom = 1.0
        if self._map:
            self._view_center = QPointF(self._map.width() / 2.0, self._map.height() / 2.0)
        self.update()
        self._emit_view_changed(force=True)

    def set_view_origin(self, left: float, top: float):
        """Pan viewport to a given map-space top-left origin."""
        if not self._map:
            return
        src = self._current_view_src()
        mw = float(self._map.width())
        mh = float(self._map.height())
        vis_w = float(src.width())
        vis_h = float(src.height())
        max_left = max(0.0, mw - vis_w)
        max_top = max(0.0, mh - vis_h)
        cl = max(0.0, min(float(left), max_left))
        ct = max(0.0, min(float(top), max_top))
        self._view_center = QPointF(cl + vis_w / 2.0, ct + vis_h / 2.0)
        self.update()
        self._emit_view_changed(force=True)

    # ---------------- Internal helpers ----------------

    def _schedule_emit(self):
        if not self._emit_timer.isActive():
            self._emit_timer.start(33)

    def _current_view_src(self) -> QRectF:
        """Visible rect in MAP coordinates."""
        if not self._map:
            return QRectF()

        mw = float(self._map.width())
        mh = float(self._map.height())
        if mw <= 0 or mh <= 0:
            return QRectF()

        # fit scale for full-map view
        if self._fit_rect.width() <= 0 or self._fit_rect.height() <= 0:
            return QRectF(0.0, 0.0, mw, mh)

        fit = min(self._fit_rect.width() / mw, self._fit_rect.height() / mh)
        denom = max(1e-6, fit * float(self._zoom))
        vis_w = self._fit_rect.width() / denom
        vis_h = self._fit_rect.height() / denom

        cx = float(self._view_center.x())
        cy = float(self._view_center.y())

        left = cx - vis_w / 2.0
        top = cy - vis_h / 2.0

        # clamp
        left = max(0.0, min(left, mw - vis_w))
        top = max(0.0, min(top, mh - vis_h))

        return QRectF(left, top, vis_w, vis_h)

    def _scale_map_to_widget(self) -> float:
        if not self._map or self._fit_rect.width() <= 0:
            return 1.0
        src = self._current_view_src()
        if src.width() <= 0:
            return 1.0
        return float(self._fit_rect.width()) / float(src.width())

    def _widget_to_map(self, pt: QPoint) -> QPoint:
        if not self._map or self._fit_rect.width() <= 0 or self._fit_rect.height() <= 0:
            return QPoint(0, 0)
        src = self._current_view_src()

        x = max(self._fit_rect.left(), min(self._fit_rect.right(), float(pt.x())))
        y = max(self._fit_rect.top(), min(self._fit_rect.bottom(), float(pt.y())))

        u = (x - self._fit_rect.left()) / self._fit_rect.width()
        v = (y - self._fit_rect.top()) / self._fit_rect.height()

        mx = int(src.left() + u * src.width())
        my = int(src.top() + v * src.height())

        mw, mh = self._map.width(), self._map.height()
        mx = max(0, min(mw - 1, mx))
        my = max(0, min(mh - 1, my))
        return QPoint(mx, my)

    def _map_to_widget_f(self, mp: QPointF) -> QPointF:
        if not self._map or self._fit_rect.width() <= 0 or self._fit_rect.height() <= 0:
            return QPointF(0.0, 0.0)
        src = self._current_view_src()
        if src.width() <= 0 or src.height() <= 0:
            return QPointF(self._fit_rect.left(), self._fit_rect.top())

        u = (float(mp.x()) - src.left()) / src.width()
        v = (float(mp.y()) - src.top()) / src.height()
        x = self._fit_rect.left() + u * self._fit_rect.width()
        y = self._fit_rect.top() + v * self._fit_rect.height()
        return QPointF(float(x), float(y))

    def _emit_view_changed(self, force: bool = False):
        if not self._map:
            state = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        else:
            src = self._current_view_src()
            state = (
                float(self._map.width()),
                float(self._map.height()),
                float(src.left()),
                float(src.top()),
                float(src.width()),
                float(src.height()),
                float(self._zoom),
            )
        if (not force) and self._last_view_state == state:
            return
        self._last_view_state = state
        self.viewChanged.emit(*state)

    # ---------------- Mouse events ----------------

    def mouseDoubleClickEvent(self, e):
        # DM-only: reset zoom on MMB double click
        if e.button() == Qt.MouseButton.MiddleButton:
            self.reset_zoom()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        if not self._map:
            return

        pos = e.position()
        if not self._fit_rect.contains(pos):
            return

        before = self._widget_to_map(QPoint(int(pos.x()), int(pos.y())))

        delta = e.angleDelta().y()
        if delta == 0:
            return

        step = 1.15 if delta > 0 else (1.0 / 1.15)
        new_zoom = max(self._zoom_min, min(self._zoom_max, self._zoom * step))
        if abs(new_zoom - self._zoom) < 1e-9:
            return

        self._zoom = new_zoom

        after = self._widget_to_map(QPoint(int(pos.x()), int(pos.y())))
        dx = float(before.x() - after.x())
        dy = float(before.y() - after.y())
        self._view_center = QPointF(self._view_center.x() + dx, self._view_center.y() + dy)

        self.update()
        self._emit_view_changed(force=True)

    def mousePressEvent(self, e):
        self.setFocus()
        self.last_mouse_pos = e.position().toPoint()

        # Player overlay drag (SHIFT + LMB)
        if (e.button() == Qt.MouseButton.LeftButton) and (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self._hit_test_player_overlay(self.last_mouse_pos):
                self._drag_player_overlay = True
                self._drag_player_anchor_map = QPointF(self._widget_to_map(self.last_mouse_pos))
                self._drag_player_anchor_center = QPointF(self._player_overlay_center)
                e.accept()
                return

        if not self._map:
            self.update()
            return

        # PAN: MMB drag (DM-only)
        if e.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last_pos = self.last_mouse_pos
            e.accept()
            return

        mp = self._widget_to_map(self.last_mouse_pos)

        # Token context menu on right click over a token.
        if self.token_tool_enabled and (not self.annotate_enabled) and (not self._grid_calib_active) and e.button() == Qt.MouseButton.RightButton:
            hit = self._hit_token_index(mp)
            if hit is not None:
                self.selected_token_index = hit
                self.update()
                self._show_token_context_menu(self.last_mouse_pos)
                e.accept()
                return

        # Token tool interactions (move / resize / rotate)
        if self.token_tool_enabled and (not self.annotate_enabled) and (not self._grid_calib_active) and e.button() == Qt.MouseButton.LeftButton:
            # Handles take precedence and can be outside token bounds.
            handle_hit = self._hit_token_handle(self.last_mouse_pos)
            if handle_hit is not None:
                hit, mode = handle_hit
                self.selected_token_index = hit
                self._drag_token = True
                self._token_drag_mode = mode
                t = self.tokens[hit]
                self._token_resize_start_w = float(t["w"])
                self._token_resize_start_h = float(t["h"])
                self.update()
                e.accept()
                return

            hit = self._hit_token_index(mp)
            if hit is not None:
                self.selected_token_index = hit
                self._drag_token = True
                t = self.tokens[hit]
                if self._token_forced_mode in ("rotate", "resize"):
                    self._token_drag_mode = self._token_forced_mode
                    self._token_forced_mode = None
                else:
                    self._token_drag_mode = "move"
                self._drag_token_offset = QPointF(float(mp.x()) - float(t["cx"]), float(mp.y()) - float(t["cy"]))
                self._token_resize_start_w = float(t["w"])
                self._token_resize_start_h = float(t["h"])
                self.update()
                e.accept()
                return
            else:
                if self.selected_token_index != -1:
                    self.selected_token_index = -1
                    self.update()

        # grid calibration: pick 2 points on map
        if self._grid_calib_active and e.button() == Qt.MouseButton.LeftButton:
            self._grid_calib_pts.append(mp)
            if len(self._grid_calib_pts) >= 2:
                a, b = self._grid_calib_pts[0], self._grid_calib_pts[1]
                dist = math.hypot(float(b.x() - a.x()), float(b.y() - a.y()))
                if self._grid_calib_type == "Hex":
                    cell = max(5, int(round((2.0 * dist) / math.sqrt(3))))
                else:
                    cell = max(5, int(round(dist)))
                self._grid_calib_active = False
                self._grid_calib_pts.clear()
                self.unsetCursor()
                self.gridCalibrated.emit(self._grid_calib_type, cell)
            self.update()
            return

        if self.annotate_enabled:
            mods = e.modifiers()
            if e.button() == Qt.MouseButton.LeftButton:
                self._start_stroke(mp)
            elif e.button() == Qt.MouseButton.RightButton:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    self._erase_portion_at(mp)
                else:
                    self._delete_stroke_at(mp)
            self.update()
            return

        # Fog brush is disabled while token tool is active.
        if self.token_tool_enabled:
            self.update()
            return

        # Fog: LMB reveal, RMB hide
        if e.button() == Qt.MouseButton.LeftButton:
            self._apply_fog_brush(mp, mode="REVEAL", start_stroke=True)
        elif e.button() == Qt.MouseButton.RightButton:
            self._apply_fog_brush(mp, mode="HIDE", start_stroke=True)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()

        # PAN (MMB drag)
        if getattr(self, "_panning", False):
            if not self._map or self._pan_last_pos is None:
                return
            dp = pos - self._pan_last_pos
            self._pan_last_pos = pos
            scale = self._scale_map_to_widget()
            if scale > 1e-6:
                # drag right => move view center left (natural pan)
                self._view_center = QPointF(
                    self._view_center.x() - dp.x() / scale,
                    self._view_center.y() - dp.y() / scale
                )
                self.update()
                self._emit_view_changed(force=True)
            e.accept()
            return

        self.last_mouse_pos = pos

        # Drag player overlay (CTRL+LMB)
        if self._drag_player_overlay and (e.buttons() & Qt.MouseButton.LeftButton):
            cur_map = QPointF(self._widget_to_map(self.last_mouse_pos))
            dx = float(cur_map.x() - self._drag_player_anchor_map.x())
            dy = float(cur_map.y() - self._drag_player_anchor_map.y())
            new_center = QPointF(self._drag_player_anchor_center.x() + dx, self._drag_player_anchor_center.y() + dy)
            self._player_overlay_center = new_center
            self.playerViewCenterChanged.emit(new_center)
            self.update()
            e.accept()
            return

        if not self._map:
            self.update()
            return

        mp = self._widget_to_map(self.last_mouse_pos)

        # Hover cursor hint for token handles or forced transform mode.
        if self.token_tool_enabled and (not self.annotate_enabled) and (not self._grid_calib_active) and (not self._drag_token):
            if self._token_forced_mode in ("rotate", "resize"):
                self._set_token_hover_cursor(self._token_forced_mode)
            else:
                handle_hover = self._hit_token_handle(self.last_mouse_pos)
                self._set_token_hover_cursor(handle_hover[1] if handle_hover is not None else None)
        elif self._token_hover_mode is not None:
            self._set_token_hover_cursor(None)

        if self._drag_token and self.selected_token_index >= 0 and self.selected_token_index < len(self.tokens):
            t = self.tokens[self.selected_token_index]
            mode = self._token_drag_mode
            if mode == "move":
                nx = float(mp.x()) - float(self._drag_token_offset.x())
                ny = float(mp.y()) - float(self._drag_token_offset.y())
                if self._map is not None:
                    nx = max(0.0, min(nx, float(self._map.width())))
                    ny = max(0.0, min(ny, float(self._map.height())))
                t["cx"] = nx
                t["cy"] = ny
            elif mode == "resize":
                cx = float(t["cx"])
                cy = float(t["cy"])
                a = math.radians(float(t.get("angle", 0.0)))
                dx = float(mp.x()) - cx
                dy = float(mp.y()) - cy
                lx = dx * math.cos(-a) - dy * math.sin(-a)
                ly = dx * math.sin(-a) + dy * math.cos(-a)
                sw = max(1e-6, float(self._token_resize_start_w or t["w"]))
                sh = max(1e-6, float(self._token_resize_start_h or t["h"]))
                # Scale uniformly along the token diagonal so aspect ratio is preserved.
                vx = sw / 2.0
                vy = -sh / 2.0
                denom = (vx * vx + vy * vy)
                k = 1.0 if denom <= 1e-9 else ((lx * vx + ly * vy) / denom)
                scale_k = abs(float(k))
                min_scale = max(16.0 / sw, 16.0 / sh)
                scale_k = max(min_scale, scale_k)
                t["w"] = sw * scale_k
                t["h"] = sh * scale_k
            elif mode == "rotate":
                cx = float(t["cx"])
                cy = float(t["cy"])
                ang = math.degrees(math.atan2(float(mp.y()) - cy, float(mp.x()) - cx)) + 90.0
                t["angle"] = ang
            self.tokensChanged.emit()
            self.update()
            e.accept()
            return

        if self.annotate_enabled:
            mods = e.modifiers()
            if e.buttons() & Qt.MouseButton.LeftButton and self._drawing_active:
                self._extend_stroke(mp)
            elif e.buttons() & Qt.MouseButton.RightButton and (mods & Qt.KeyboardModifier.ControlModifier):
                self._erase_portion_at(mp)
            self.update()
            return

        # Fog brush drag is disabled while token tool is active.
        if self.token_tool_enabled:
            self.update()
            return

        if e.buttons() & Qt.MouseButton.LeftButton:
            self._apply_fog_brush(mp, mode="REVEAL", start_stroke=False)
        elif e.buttons() & Qt.MouseButton.RightButton:
            self._apply_fog_brush(mp, mode="HIDE", start_stroke=False)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and getattr(self, "_panning", False):
            self._panning = False
            e.accept()
            return

        # end Player overlay drag
        if self._drag_player_overlay and e.button() == Qt.MouseButton.LeftButton:
            self._drag_player_overlay = False
            self.update()
            e.accept()
            return

        if self._drag_token and e.button() == Qt.MouseButton.LeftButton:
            self._drag_token = False
            self._token_drag_mode = None
            self._token_resize_start_w = 0.0
            self._token_resize_start_h = 0.0
            if self._token_forced_mode is None and self._token_hover_mode is not None:
                self._set_token_hover_cursor(None)
            self.update()
            e.accept()
            return

        if self.annotate_enabled and self._drawing_active and e.button() == Qt.MouseButton.LeftButton:
            self._finish_stroke()
        self.update()

    def leaveEvent(self, e):
        self.last_mouse_pos = None
        if self._token_hover_mode is not None:
            self._set_token_hover_cursor(None)
        self.update()
        super().leaveEvent(e)


    def keyPressEvent(self, e):
        """Handle token shortcuts and annotation clear shortcut.

        Token shortcuts:
        - Ctrl+C: copy selected token
        - Ctrl+V: paste token copy
        - Delete/Backspace: delete selected token
        """
        mods = e.modifiers()

        if mods & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_C:
                if self.copy_selected_token():
                    e.accept()
                    return
            elif e.key() == Qt.Key.Key_V:
                if self.paste_token():
                    e.accept()
                    return

        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_token_index != -1:
                self.remove_selected_token()
                e.accept()
                return
        # Command: erase all annotations (Ctrl+Shift+Backspace/Delete)
        if (mods & Qt.KeyboardModifier.ControlModifier) and (mods & Qt.KeyboardModifier.ShiftModifier):
            if e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                self.clear_annotations()
                e.accept()
                return
        super().keyPressEvent(e)

    def clear_annotations(self):
        self.drawings.clear()
        self._current_stroke = None
        self._drawing_active = False
        self.drawingsChanged.emit()
        self.update()

    # ---------------- Fog painting ----------------

    def _apply_fog_brush(self, center_map: QPoint, mode: str, start_stroke: bool):
        self.ensure_mask()
        if not self.mask_img:
            return
        if start_stroke:
            self.push_undo()
        scale = self._scale_map_to_widget()
        radius_map = max(1, int(round(float(self.brush_radius) / max(1e-6, float(scale)))))
        self._paint_soft_circle(center_map, radius_map, mode=mode)
        self._schedule_emit()

    def _paint_soft_circle(self, center_map: QPoint, radius: int, mode: str):
        """
        Paint a soft circular stamp into the fog mask in *map* coordinates.

        Softness is controlled by self.brush_softness in [0..1]:
        - 0.0 => hard edge
        - 1.0 => very feathered edge
        """
        if self.mask_img is None:
            return

        softness = max(0.0, min(1.0, float(getattr(self, "brush_softness", 0.0))))

        # Feather grows with radius and softness.
        feather = max(1.0, radius * (0.15 + 0.85 * softness))
        patch_r = int(math.ceil(radius + feather))

        cx, cy = int(center_map.x()), int(center_map.y())
        left = max(0, cx - patch_r)
        top = max(0, cy - patch_r)
        right = min(self.mask_img.width(), cx + patch_r + 1)
        bottom = min(self.mask_img.height(), cy + patch_r + 1)
        pw = right - left
        ph = bottom - top
        if pw <= 0 or ph <= 0:
            return

        patch = QImage(pw, ph, QImage.Format.Format_RGBA8888)
        patch.fill(QColor(0, 0, 0, 0))

        pcx = float(cx - left)
        pcy = float(cy - top)

        inner = float(radius) * (1.0 - 0.95 * softness)  # softness=0 => inner≈radius
        outer = float(radius) + feather

        grad = QRadialGradient(QPointF(pcx, pcy), outer)
        grad.setColorAt(0.0, QColor(0, 0, 0, 255))
        t = 0.0 if outer <= 0 else max(0.0, min(1.0, inner / outer))
        # Cinematic falloff (always on)
        if t < 1.0:
            core = min(outer, max(inner, float(radius) * (1.0 - 0.65 * softness)))
            t2 = 0.0 if outer <= 0 else max(0.0, min(1.0, core / outer))
            grad.setColorAt(0.0, QColor(0, 0, 0, 255))
            grad.setColorAt(t2, QColor(0, 0, 0, 255))

            def _clamp01(x: float) -> float:
                return 0.0 if x <= 0.0 else (1.0 if x >= 1.0 else x)

            gamma = 0.60  # <1 => slower fade near the core (more gradual)
            stops = [0.08, 0.16, 0.24, 0.34, 0.46, 0.60, 0.76, 1.00]
            for s in stops:
                pos = t2 + (1.0 - t2) * s
                x = _clamp01((pos - t2) / (1.0 - t2))
                a = int(round(255.0 * ((1.0 - x) ** gamma)))
                grad.setColorAt(float(pos), QColor(0, 0, 0, max(0, min(255, a))))
        else:
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))

        qp = QPainter(patch)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QBrush(grad))
        qp.drawEllipse(QPointF(pcx, pcy), outer, outer)
        qp.end()

        # Apply to mask using alpha MIN/MAX instead of multiplicative compositing.
        # This preserves the feather even while dragging (no "edge hardening" from repeated stamps).
        dest = self.mask_img.copy(left, top, pw, ph)

        sb = patch.bits(); sb.setsize(patch.sizeInBytes())
        db = dest.bits(); db.setsize(dest.sizeInBytes())
        s = memoryview(sb)
        d = memoryview(db)

        if mode == "REVEAL":
            # stamp alpha = how much to reveal; target mask alpha = 255 - stamp
            for i in range(3, len(d), 4):
                sa = s[i]
                ta = 255 - sa
                da = d[i]
                d[i] = ta if ta < da else da
        else:
            # hide: stamp alpha directly increases fog alpha
            for i in range(3, len(d), 4):
                sa = s[i]
                da = d[i]
                d[i] = sa if sa > da else da

        # Write back the modified region (replace)
        p = QPainter(self.mask_img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(left, top, dest)
        p.end()

    # ---------------- Drawing / annotation ----------------

    def _start_stroke(self, mp: QPoint):
        self._drawing_active = True
        self._current_stroke = Stroke(
            id=self._stroke_id,
            points=[(mp.x(), mp.y())],
            color=self.draw_color,
            width=self.draw_width,
            dash=self.draw_dash,
        )
        self._stroke_id += 1

    def _extend_stroke(self, mp: QPoint):
        if not self._current_stroke:
            return
        last = self._current_stroke.points[-1]
        dx = mp.x() - last[0]
        dy = mp.y() - last[1]
        if (dx * dx + dy * dy) < 3:
            return
        self._current_stroke.points.append((mp.x(), mp.y()))

    def _finish_stroke(self):
        if not self._current_stroke:
            self._drawing_active = False
            return
        if len(self._current_stroke.points) >= 2:
            self.drawings.append(self._current_stroke)
            self.drawingsChanged.emit()
        self._current_stroke = None
        self._drawing_active = False

    def _delete_stroke_at(self, mp: QPoint):
        idx = self._hit_stroke_index(mp)
        if idx is not None:
            self.drawings.pop(idx)
            self.drawingsChanged.emit()
            self.update()

    def _erase_portion_at(self, mp: QPoint):
        # Remove points near cursor; split into multiple strokes as needed.
        idx = self._hit_stroke_index(mp, return_closest=True)
        if idx is None:
            return
        s = self.drawings[idx]
        tol = max(10, int(s.width * 2))
        tol2 = tol * tol
        remaining = []
        current = []
        x, y = mp.x(), mp.y()

        for (px, py) in s.points:
            d2 = (px - x) ** 2 + (py - y) ** 2
            keep = d2 > tol2
            if keep:
                current.append((px, py))
            else:
                if len(current) >= 2:
                    remaining.append(current)
                current = []
        if len(current) >= 2:
            remaining.append(current)

        if not remaining:
            self.drawings.pop(idx)
            self.drawingsChanged.emit()
            self.update()
            return

        new_strokes = []
        for seg in remaining:
            new_strokes.append(Stroke(
                id=self._stroke_id,
                points=seg,
                color=s.color,
                width=s.width,
                dash=s.dash
            ))
            self._stroke_id += 1

        self.drawings.pop(idx)
        for ns in reversed(new_strokes):
            self.drawings.insert(idx, ns)

        self.drawingsChanged.emit()
        self.update()

    def _hit_stroke_index(self, mp: QPoint, return_closest: bool = False) -> int | None:
        if not self.drawings:
            return None
        x, y = mp.x(), mp.y()
        best_i = None
        best_d2 = None
        for i, s in enumerate(self.drawings):
            tol = max(8, s.width * 2)
            tol2 = tol * tol
            pts = s.points
            for j in range(1, len(pts)):
                x0, y0 = pts[j - 1]
                x1, y1 = pts[j]
                d2 = self._point_seg_dist2(x, y, x0, y0, x1, y1)
                if d2 <= tol2:
                    if not return_closest:
                        return i
                    if best_d2 is None or d2 < best_d2:
                        best_d2 = d2
                        best_i = i
        return best_i

    def _point_seg_dist2(self, px, py, x0, y0, x1, y1):
        vx = x1 - x0
        vy = y1 - y0
        wx = px - x0
        wy = py - y0
        c1 = vx * wx + vy * wy
        if c1 <= 0:
            dx = px - x0
            dy = py - y0
            return dx * dx + dy * dy
        c2 = vx * vx + vy * vy
        if c2 <= c1:
            dx = px - x1
            dy = py - y1
            return dx * dx + dy * dy
        b = c1 / c2
        bx = x0 + b * vx
        by = y0 + b * vy
        dx = px - bx
        dy = py - by
        return dx * dx + dy * dy

    # ---------------- Rendering ----------------

    def set_player_overlay(self, enabled: bool, center_map: QPointF | None, zoom: float | None,
                           viewport_w: int, viewport_h: int):
        """Called by MainWindow: provides Player camera parameters so DM can see/drag the Player viewport."""
        self._player_overlay_enabled = bool(enabled)
        if center_map is not None:
            self._player_overlay_center = QPointF(float(center_map.x()), float(center_map.y()))
        self._player_overlay_zoom = float(zoom) if (zoom is not None) else None
        self._player_overlay_vw = int(viewport_w or 0)
        self._player_overlay_vh = int(viewport_h or 0)
        self.update()

    def _player_view_src_rect(self) -> QRectF | None:
        """Compute Player visible map rectangle in map-space."""
        if not self._map:
            return None
        if not self._player_overlay_enabled:
            return None
        if not self._player_overlay_zoom or self._player_overlay_zoom <= 0:
            return None
        if self._player_overlay_vw <= 0 or self._player_overlay_vh <= 0:
            return None

        # IMPORTANT:
        # The PlayerWindow builds its source rect as:
        #   view_w_map = widget_w_px / zoom
        #   view_h_map = widget_h_px / zoom
        # i.e. *no* extra "fit" factor.
        #
        # If we introduce a fit-to-map term here, the yellow DM overlay will drift
        # (most noticeable when switching windowed <-> fullscreen, because the
        # player widget aspect changes).
        mw, mh = float(self._map.width()), float(self._map.height())
        denom = max(1e-6, float(self._player_overlay_zoom))
        vis_w = float(self._player_overlay_vw) / denom
        vis_h = float(self._player_overlay_vh) / denom

        # If the player's viewport is larger than the map in either dimension,
        # the player will effectively see the whole map with black bars.
        # Represent that truthfully on the DM overlay.
        if vis_w >= mw or vis_h >= mh:
            return QRectF(0.0, 0.0, mw, mh)

        cx = float(self._player_overlay_center.x())
        cy = float(self._player_overlay_center.y())
        left = cx - vis_w / 2.0
        top = cy - vis_h / 2.0

        left = max(0.0, min(left, mw - vis_w))
        top = max(0.0, min(top, mh - vis_h))

        return QRectF(left, top, vis_w, vis_h)

    def _draw_player_overlay(self, p: QPainter):
        r = self._player_view_src_rect()
        if r is None:
            return

        tl = self._map_to_widget_f(QPointF(r.left(), r.top()))
        br = self._map_to_widget_f(QPointF(r.right(), r.bottom()))
        rect = QRectF(
            float(tl.x()),
            float(tl.y()),
            float(br.x() - tl.x()),
            float(br.y() - tl.y()),
        ).normalized()

        p.save()
        try:
            pen = QPen(QColor(255, 210, 0, 230))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
        finally:
            p.restore()

    def _hit_test_player_overlay(self, pos: QPoint) -> bool:
        r = self._player_view_src_rect()
        if r is None:
            return False

        tl = self._map_to_widget_f(QPointF(r.left(), r.top()))
        br = self._map_to_widget_f(QPointF(r.right(), r.bottom()))

        rect = QRectF(
            float(tl.x()),
            float(tl.y()),
            float(br.x() - tl.x()),
            float(br.y() - tl.y()),
        ).normalized()

        return rect.contains(float(pos.x()), float(pos.y()))


        # Border-only hit test: lets you paint fog inside the rectangle without accidentally moving it.
        if not rect.contains(float(pos.x()), float(pos.y())):
            return False

        margin = 7.0  # px
        x = float(pos.x())
        y = float(pos.y())
        near_left = abs(x - rect.left()) <= margin
        near_right = abs(x - rect.right()) <= margin
        near_top = abs(y - rect.top()) <= margin
        near_bottom = abs(y - rect.bottom()) <= margin
        return near_left or near_right or near_top or near_bottom

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)

        if not self._map:
            p.end()
            return

        w, h = self.width(), self.height()
        mw, mh = self._map.width(), self._map.height()
        fit_scale = min(w / mw, h / mh) if mw and mh else 1.0
        dw, dh = mw * fit_scale, mh * fit_scale
        x, y = (w - dw) / 2.0, (h - dh) / 2.0
        target = QRectF(x, y, dw, dh)
        self._fit_rect = target

        src = self._current_view_src()
        scale = self._scale_map_to_widget()
        self._emit_view_changed()

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Map
        p.drawImage(target, self._map, src)

        # tokens layer (DM view, above map)
        self._draw_tokens(p, target, src)

        # strokes always visible to DM (clip to map area so they don't spill into black bars)
        p.save()
        p.setClipRect(target)
        self._draw_strokes(p, target, scale, src)
        p.restore()

        # fog overlay translucent for DM (IMPORTANT: use same src for zoom alignment)
        if self.mask_img:
            tmp = self.mask_img.copy()
            tp = QPainter(tmp)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            tp.fillRect(tmp.rect(), QColor(0, 0, 0, self.dm_fog_alpha))
            tp.end()
            p.drawImage(target, tmp, src)

        if self.show_grid and self.grid_type != "None":
            self._draw_grid(p, target, scale, src)

        # Grid calibration helpers (DM)
        if self._grid_calib_active and self._grid_calib_pts:
            pen2 = QPen(QColor(0, 255, 0, 220))
            pen2.setWidth(2)
            p.setPen(pen2)
            p.setBrush(QColor(0, 0, 0, 0))
            pts_w = [self._map_to_widget_f(QPointF(float(pt.x()), float(pt.y()))) for pt in self._grid_calib_pts]
            for pw in pts_w:
                p.drawEllipse(QPointF(pw.x(), pw.y()), 6, 6)
            if len(pts_w) >= 2:
                a, b = pts_w[0], pts_w[1]
                p.drawLine(int(a.x()), int(a.y()), int(b.x()), int(b.y()))

        # Player viewport overlay (DM)
        self._draw_player_overlay(p)

        # Cursor preview (hide while panning/dragging player overlay OR during grid calibration)
        if (not self._grid_calib_active) and (not getattr(self, "_panning", False)) and (not getattr(self, "_drag_player_overlay", False)) and self.last_mouse_pos and target.contains(float(self.last_mouse_pos.x()), float(self.last_mouse_pos.y())):
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.annotate_enabled:
                tip_r = max(2, int((self.draw_width * scale) / 2))
                p.drawEllipse(self.last_mouse_pos, tip_r, tip_r)
            else:
                if self.token_tool_enabled:
                    p.end()
                    return
                # brush preview in widget pixels (screen-consistent across zoom)
                r_px = max(2, int(self.brush_radius))
                softness = max(0.0, min(1.0, float(getattr(self, "brush_softness", 0.0))))
                feather_px = max(1.0, float(r_px) * (0.15 + 0.85 * softness))
                outer_px = int(round(float(r_px) + feather_px))

                # Inner: effective brush radius (solid)
                solid = QPen(QColor(255, 255, 255, 220))
                solid.setWidth(2)
                solid.setStyle(Qt.PenStyle.SolidLine)
                p.setPen(solid)
                p.drawEllipse(self.last_mouse_pos, r_px, r_px)

                # Outer: FOV/feather extent (dashed)
                dashed = QPen(QColor(255, 255, 255, 170))
                dashed.setWidth(2)
                dashed.setStyle(Qt.PenStyle.CustomDashLine)
                dashed.setDashPattern([6.0, 6.0])
                p.setPen(dashed)
                p.drawEllipse(self.last_mouse_pos, outer_px, outer_px)


        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._emit_view_changed(force=True)

    def _draw_tokens(self, p: QPainter, target: QRectF, src: QRectF):
        """Render tokens in DM view and draw transform handles when selected."""
        if not self.tokens or src.width() <= 0 or src.height() <= 0:
            return

        p.save()
        p.setClipRect(target)
        for i, t in enumerate(self.tokens):
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

            rect = QRectF(cxw - ww / 2.0, cyw - hh / 2.0, ww, hh)
            if rect.right() < target.left() or rect.left() > target.right() or rect.bottom() < target.top() or rect.top() > target.bottom():
                continue

            p.save()
            p.translate(cxw, cyw)
            p.rotate(ta)
            p.drawImage(QRectF(-ww / 2.0, -hh / 2.0, ww, hh), img)
            if i == self.selected_token_index:
                pen = QPen(QColor(255, 215, 0, 230), 2)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(-ww / 2.0, -hh / 2.0, ww, hh))

                if self.token_tool_enabled:
                    handle_r = float(self._token_handle_radius_px)

                    # resize handle (top-right) with explicit diagonal-resize icon
                    resize_c = QPointF(ww / 2.0, -hh / 2.0)
                    p.setBrush(QBrush(QColor(0, 200, 255, 235)))
                    p.setPen(QPen(QColor(20, 20, 20, 230), 1))
                    p.drawEllipse(resize_c, handle_r, handle_r)

                    p.save()
                    p.translate(resize_c)
                    p.setPen(QPen(QColor(255, 255, 255, 245), 2))
                    p.drawLine(-3, 3, 3, -3)
                    # Arrow heads for NW-SE resize cue.
                    p.drawLine(3, -3, 1, -3)
                    p.drawLine(3, -3, 3, -1)
                    p.drawLine(-3, 3, -1, 3)
                    p.drawLine(-3, 3, -3, 1)
                    p.restore()

                    # rotate handle (top-center, outside) with explicit rotate icon
                    ry = -hh / 2.0 - max(10.0, min(20.0, 0.15 * max(ww, hh)))
                    rotate_c = QPointF(0.0, ry)
                    p.setBrush(QBrush(QColor(255, 160, 0, 235)))
                    p.setPen(QPen(QColor(20, 20, 20, 230), 1))
                    p.drawEllipse(rotate_c, handle_r, handle_r)

                    p.save()
                    p.translate(rotate_c)
                    p.setPen(QPen(QColor(255, 255, 255, 245), 2))
                    p.drawArc(QRectF(-4.5, -4.5, 9.0, 9.0), 30 * 16, 260 * 16)
                    # Arrow head at arc end.
                    p.drawLine(4, -1, 2, -3)
                    p.drawLine(4, -1, 1, 0)
                    p.restore()
            p.restore()
        p.restore()

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

    def _chaikin(self, pts: list[tuple[float, float]], iters: int = 1) -> list[tuple[float, float]]:
        # Chaikin corner-cutting: makes polyline smoother without heavy math.
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

    def _smooth_path(self, pts: list[tuple[float, float]], target: QRectF, src: QRectF) -> QPainterPath:
        def to_w(xm: float, ym: float) -> QPointF:
            u = (xm - src.left()) / src.width() if src.width() else 0.0
            v = (ym - src.top()) / src.height() if src.height() else 0.0
            return QPointF(target.left() + u * target.width(), target.top() + v * target.height())

        pts = self._chaikin(pts, iters=1)
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

    def _draw_strokes(self, p: QPainter, target: QRectF, scale: float, src: QRectF):
        p.save()
        for s in self.drawings:
            if len(s.points) < 2:
                continue
            col = QColor(*s.color)
            pen = self._dash_pen(col, int(s.width * scale), s.dash)
            p.setPen(pen)
            path = self._smooth_path(s.points, target, src)
            p.drawPath(path)

        if self._current_stroke and len(self._current_stroke.points) >= 2:
            col = QColor(*self._current_stroke.color)
            col.setAlpha(180)
            pen = self._dash_pen(col, int(self._current_stroke.width * scale), self._current_stroke.dash)
            p.setPen(pen)
            path = self._smooth_path(self._current_stroke.points, target, src)
            p.drawPath(path)
        p.restore()

    def _draw_grid(self, p: QPainter, target: QRectF, scale: float, src: QRectF):
        cell_map = float(self.grid_cell_map_px)
        if cell_map <= 2 or not self._map or src.width() <= 0 or src.height() <= 0:
            return

        pen = QPen(QColor(255, 255, 255, self.grid_alpha))
        pen.setWidth(1)
        p.setPen(pen)

        def mx_to_wx(mx: float) -> float:
            u = (mx - src.left()) / src.width()
            return target.left() + u * target.width()

        def my_to_wy(my: float) -> float:
            v = (my - src.top()) / src.height()
            return target.top() + v * target.height()

        if self.grid_type == "Square":
            start_x = math.floor(src.left() / cell_map) * cell_map
            x = start_x
            while x <= src.right() + cell_map:
                wx = mx_to_wx(x)
                p.drawLine(int(wx), int(target.top()), int(wx), int(target.bottom()))
                x += cell_map

            start_y = math.floor(src.top() / cell_map) * cell_map
            y = start_y
            while y <= src.bottom() + cell_map:
                wy = my_to_wy(y)
                p.drawLine(int(target.left()), int(wy), int(target.right()), int(wy))
                y += cell_map
            return

        if self.grid_type == "Hex":
            cell = cell_map
            r = cell / 2.0
            if r <= 2:
                return
            dx = math.sqrt(3) * r
            dy = 1.5 * r

            first_row = int(math.floor(src.top() / dy)) - 2
            last_row = int(math.ceil(src.bottom() / dy)) + 2

            for row in range(first_row, last_row + 1):
                cy = row * dy
                x_off = (dx / 2.0) if (row % 2) else 0.0
                col0 = int(math.floor((src.left() - x_off) / dx)) - 2
                col1 = int(math.ceil((src.right() - x_off) / dx)) + 2
                for col in range(col0, col1 + 1):
                    cx = x_off + col * dx
                    wx = mx_to_wx(cx)
                    wy = my_to_wy(cy)
                    self._draw_hex(p, wx, wy, r * (target.width() / src.width()))

    def _draw_hex(self, p: QPainter, cx: float, cy: float, r: float):
        pts = []
        for i in range(6):
            ang = math.radians(60 * i - 30)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for i in range(6):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % 6]
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
