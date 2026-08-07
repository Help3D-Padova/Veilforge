from __future__ import annotations

from pathlib import Path
import json
import sys
import math
import base64
import time
import hashlib
import shutil
import subprocess
import re

from PyQt6.QtCore import Qt, QSettings, QTimer, QPointF, QEvent, QUrl, QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage, QGuiApplication, QColor, QIcon, QTransform, QDesktopServices, QPixmap, QPainter, QPen, QFont
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedLayout, QPushButton, QFileDialog,
    QLabel, QSlider, QMessageBox, QComboBox, QCheckBox, QSpinBox, QColorDialog,
    QFrame, QDialog, QTextEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QGridLayout,
    QScrollBar
)

from .dm_canvas import DMCanvas
from .player_window import PlayerWindow
from .map_loader import load_map, LoadedMap
from .session import SessionData, save_session, load_session
from .drawings import Stroke
from . import __version__

HELP_TEXT = (
    "Veilforge – Fog of War (local)\n\n"
    "FOG\n"
    "- Left mouse drag: Reveal\n"
    "- Right mouse drag: Hide\n"
    "- Brush Size: size of the reveal/hide circle\n"
    "- FOV Softness: feathering (applies only to new strokes)\n\n"
    "ANNOTATE\n"
    "- Toggle Annotate ON\n"
    "- Left mouse drag: draw\n"
    "- Right click: delete a whole stroke\n"
    "- CTRL + Right drag: delete only a portion (splits the stroke)\n"
    "- Color / Width / Style / Alpha affect new strokes\n\n"
    "PLAYER\n"
    "- Player Screen ON: shows player view on the selected monitor\n"
    "- Mode: Fullscreen or Window\n\n"
    "GRID\n"
    "- Enable Grid, select Square/Hex, set Cell size (px on map), Alpha\n"
    "- Optional: show on player\n"
    "- In video mode, Grid is rendered as an overlay on both DM and Player screens\n"
    "\n"
    "MASTER NAVIGATION\n"
    "- Mouse wheel: zoom in/out on the DM map\n"
    "- Middle mouse drag: pan in the zoomed image\n"
    "- When zoomed in, horizontal/vertical scrollbars appear (bottom/right)\n"
    "  to move quickly in the zoomed map area\n"
    "\n"
    "TOKENS\n"
    "- Import Token: add a PNG/JPG token centered on the current map\n"
    "- Token tool ON: click a token to select it, drag to move\n"
    "- Resize handle: blue icon (top-right), Rotate handle: orange icon (above token)\n"
    "- Right click on a token: Rotate / Resize / Copy / Paste / Delete\n"
    "- Keyboard: Ctrl+C copies selected token, Ctrl+V pastes a duplicate\n"
    "- Delete selected token: Delete/Backspace\n"
    "- While Token tool is ON, Fog brush preview and paint are disabled on DM canvas\n"
    "\n"
    "NEW: Fog toggle button\n"
    "- The Fog toggle is placed next to 'Reset Fog' in the DM controls.\n"
    "- It controls whether the Player view (image or video) shows the black fog mask.\n"
    "- When Fog is OFF the Player receives no mask (the overlay is hidden for videos).\n"
    "\n"
    "SESSIONS\n"
    "- Save/Save As now includes imported tokens and their transforms\n"
    "- On Load Session, missing map/media files are searched in the session folder\n"
    "- If still missing, Veilforge asks you to locate the file and remembers the new path\n"
)


class DMVideoView(QWidget):
    """DM-side video surface that renders video frames and optional grid.

    This avoids relying on overlay widgets above `QVideoWidget`, which can be
    hidden by native video surfaces on some platforms.
    """

    def __init__(self):
        super().__init__()
        self.frame_img: QImage | None = None
        self.show_grid = False
        self.grid_type = "None"
        self.grid_cell_px = 70
        self.grid_alpha = 130
        self._grid_cache: QImage | None = None
        self._grid_cache_key: tuple | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_frame(self, img: QImage | None):
        self.frame_img = img if img is not None and not img.isNull() else None
        self.update()

    def set_grid(self, show: bool, grid_type: str, cell_px: int, alpha: int):
        self.show_grid = bool(show)
        self.grid_type = str(grid_type)
        self.grid_cell_px = max(5, int(cell_px))
        self.grid_alpha = max(0, min(255, int(alpha)))
        self._grid_cache = None
        self._grid_cache_key = None
        self.update()

    def _ensure_grid_cache(self):
        key = (self.width(), self.height(), self.show_grid, self.grid_type, self.grid_cell_px, self.grid_alpha)
        if self._grid_cache is not None and self._grid_cache_key == key:
            return

        self._grid_cache_key = key
        self._grid_cache = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_RGBA8888)
        self._grid_cache.fill(QColor(0, 0, 0, 0))

        if not (self.show_grid and self.grid_type in ("Square", "Hex")):
            return

        p = QPainter(self._grid_cache)
        try:
            pen = QPen(QColor(255, 255, 255, int(self.grid_alpha)), 1)
            p.setPen(pen)
            cell = max(5.0, float(self.grid_cell_px))
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
                row = -2
                max_row = int(self.height() / dy) + 3
                while row <= max_row:
                    cy = row * dy
                    x_off = (dx / 2.0) if (row % 2) else 0.0
                    col = -2
                    max_col = int(self.width() / dx) + 3
                    while col <= max_col:
                        cx = x_off + col * dx
                        pts = []
                        for i in range(6):
                            ang = math.radians(60 * i - 30)
                            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
                        for i in range(6):
                            x0, y0 = pts[i]
                            x1, y1 = pts[(i + 1) % 6]
                            p.drawLine(int(x0), int(y0), int(x1), int(y1))
                        col += 1
                    row += 1
        finally:
            p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._grid_cache = None
        self._grid_cache_key = None

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), QColor(0, 0, 0))
            if self.frame_img is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                p.drawImage(self.rect(), self.frame_img)

            self._ensure_grid_cache()
            if self._grid_cache is not None:
                p.drawImage(self.rect(), self._grid_cache)
        finally:
            p.end()

class MainWindow(QMainWindow):

    def _get_missing_file_remaps(self) -> dict[str, str]:
        """Return persisted remaps for missing map/media files."""
        try:
            raw = self.settings.value(self.MISSING_MEDIA_REMAPS_KEY, "{}")
        except Exception:
            raw = "{}"

        if isinstance(raw, dict):
            out = {}
            for k, v in raw.items():
                if k and v:
                    out[str(k)] = str(v)
            return out

        s = str(raw or "{}")
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    if k and v:
                        out[str(k)] = str(v)
                return out
        except Exception:
            pass
        return {}

    def _save_missing_file_remaps(self, remaps: dict[str, str]) -> None:
        """Persist remaps in settings as JSON text for portability."""
        try:
            self.settings.setValue(
                self.MISSING_MEDIA_REMAPS_KEY,
                json.dumps(remaps, ensure_ascii=False),
            )
        except Exception:
            pass

    def _remember_missing_file_remap(self, original_path: str, resolved_path: Path) -> None:
        """Store a successful manual remap so future loads are seamless."""
        try:
            key = str(original_path or "").strip()
            if not key:
                return
            rp = str(resolved_path.resolve())
            remaps = self._get_missing_file_remaps()
            remaps[key] = rp

            # Also store a basename fallback for moved folders.
            name = Path(key).name
            if name:
                remaps[name] = rp

            # Keep structure bounded to avoid unbounded settings growth.
            if len(remaps) > 400:
                trimmed = {}
                for i, (k, v) in enumerate(remaps.items()):
                    if i >= 400:
                        break
                    trimmed[k] = v
                remaps = trimmed

            self._save_missing_file_remaps(remaps)
        except Exception:
            pass

    def _resolve_session_media_path(self, saved_path: str, session_json_path: Path) -> Path | None:
        """Resolve a session map/media path with fallback and user prompt.

        Resolution order:
        1) Existing path as stored.
        2) Same basename inside session directory (direct then recursive).
        3) Previously remembered remap.
        4) Ask user to locate the missing file.
        """
        s = str(saved_path or "").strip()
        if not s:
            return None

        session_dir = session_json_path.parent
        raw = Path(s)

        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append((session_dir / raw))
            try:
                candidates.append(self._resolve_portable_path(s))
            except Exception:
                pass
            candidates.append(Path.cwd() / raw)

        # 1) Existing path as stored/candidate
        for c in candidates:
            try:
                if c.exists():
                    return c.resolve()
            except Exception:
                continue

        # 2) Try same filename in the session folder
        try:
            by_name = session_dir / raw.name
            if raw.name and by_name.exists():
                return by_name.resolve()
        except Exception:
            pass

        try:
            if raw.name:
                for f in session_dir.rglob(raw.name):
                    if f.is_file():
                        return f.resolve()
        except Exception:
            pass

        # 3) Remembered remaps (exact key and basename key)
        remaps = self._get_missing_file_remaps()
        for key in (s, raw.name):
            if not key:
                continue
            rp = remaps.get(key)
            if not rp:
                continue
            p = Path(rp)
            try:
                if p.exists() and p.is_file():
                    return p.resolve()
            except Exception:
                continue

        # 4) Ask user to locate file manually
        filter_text = (
            "Map/Media files (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.pdf "
            "*.mp4 *.webm *.mkv *.mov *.avi *.flv *.m2ts *.ts *.3gp *.m4a);;"
            "All files (*.*)"
        )
        located, _ = QFileDialog.getOpenFileName(
            self,
            "Locate missing map/media file",
            str(session_dir),
            filter_text,
        )
        if not located:
            return None

        found = Path(located)
        try:
            found = found.resolve()
        except Exception:
            pass

        self._remember_missing_file_remap(s, found)
        return found

    def _serialize_tokens(self) -> list[dict]:
        """Convert in-memory token images to JSON-safe objects."""
        out: list[dict] = []
        for t in getattr(self.canvas, "tokens", []) or []:
            try:
                img = t.get("img")
                if img is None or img.isNull():
                    continue
                arr = QByteArray()
                buf = QBuffer(arr)
                if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
                    continue
                ok = img.save(buf, "PNG")
                buf.close()
                if not ok:
                    continue
                out.append({
                    "img_b64": base64.b64encode(bytes(arr)).decode("ascii"),
                    "cx": float(t.get("cx", 0.0)),
                    "cy": float(t.get("cy", 0.0)),
                    "w": float(t.get("w", 32.0)),
                    "h": float(t.get("h", 32.0)),
                    "angle": float(t.get("angle", 0.0)),
                })
            except Exception:
                continue
        return out

    def _deserialize_tokens(self, payload: list[dict]) -> list[dict]:
        """Rebuild token dicts with QImage objects from saved JSON data."""
        out: list[dict] = []
        for it in payload or []:
            try:
                b64 = str(it.get("img_b64", ""))
                if not b64:
                    continue
                raw = base64.b64decode(b64.encode("ascii"), validate=False)
                img = QImage()
                if not img.loadFromData(raw, "PNG") or img.isNull():
                    continue
                out.append({
                    "img": img,
                    "cx": float(it.get("cx", 0.0)),
                    "cy": float(it.get("cy", 0.0)),
                    "w": max(1.0, float(it.get("w", img.width()))),
                    "h": max(1.0, float(it.get("h", img.height()))),
                    "angle": float(it.get("angle", 0.0)),
                })
            except Exception:
                continue
        return out

    def _app_dir(self) -> Path:
        """Return the base directory for portable builds.

        - PyInstaller one-folder: folder containing the .exe
        - PyInstaller one-file: sys._MEIPASS (temporary extraction dir)
        - Source run: project root (two levels up from this file)
        """
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                return Path(meipass)
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent

    def _default_sessions_dir(self) -> Path:
        """Default sessions folder for portable builds."""
        d = self._app_dir() / "data" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _make_portable_path(self, p: Path) -> str:
        """Store paths relative to the app folder when possible (portable-friendly)."""
        try:
            base = self._app_dir().resolve()
            rp = p.resolve()
            rel = rp.relative_to(base)
            return str(Path(".") / rel)
        except Exception:
            return str(p)

    def _resolve_portable_path(self, p: str) -> Path:
        """Resolve a stored path (relative to app dir if needed)."""
        pp = Path(str(p))
        if pp.is_absolute():
            return pp
        return (self._app_dir() / pp).resolve()
        

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Veilforge {__version__} – Fog of War")
        try:
            self.setWindowIcon(QIcon(str(self._app_dir() / "assets" / "veilforge.png")))
        except Exception:
            pass

        # Portable-friendly settings (stored next to the app, not in Windows registry)
        settings_path = self._app_dir() / "data" / "settings.ini"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
        self.ask_overwrite = self.settings.value("ask_overwrite", True, type=bool)

        # Recent sessions (most recent first)
        self.RECENT_SESSIONS_KEY = "recent_sessions"
        self.RECENT_MAX = 8
        self.MISSING_MEDIA_REMAPS_KEY = "missing_media_remaps"
        self._restore_prompt_shown = False

        # Player physical calibration: pixels per inch on the real table/screen
        self.px_per_inch_real = float(self.settings.value("px_per_inch_real", 120.0))
        self.player_view_center: QPointF | None = None
        self.player_view_cell_step = 1  # cells per pan step

        # Map/session state
        self.loaded: LoadedMap | None = None
        self.map_img: QImage | None = None
        self.map_rotation_deg = 0
        self.current_session_path: Path | None = None
        # Fog state for player view: True = fog shown, False = fog hidden
        self.fog_enabled = True

        # Media playback
        self.media_player: QMediaPlayer | None = None
        self.audio_output: QAudioOutput | None = None
        self.media_video_sink: QVideoSink | None = None
        self.current_video_frame_img: QImage | None = None
        self.video_widget = DMVideoView()
        # Video frame optimization: throttling + downscaling.
        #
        # Limitation note:
        # Very heavy streams (typically 4K/high bitrate) can starve the UI thread
        # on some systems and trigger Windows "Not responding" warnings.
        # We therefore apply two runtime mitigations:
        # - adaptive "lite" profile (lower frame processing + stronger downscale)
        # - optional cached 1080p transcode (when ffmpeg is available)
        self._last_video_frame_time = 0.0
        self._video_default_frame_interval = 0.04  # ~25fps
        self._video_default_max_width = 2560
        self._video_lite_frame_interval = 0.08  # ~12fps for heavy files
        self._video_lite_max_width = 1280
        self._min_video_frame_interval = self._video_default_frame_interval
        self._max_video_display_width = self._video_default_max_width
        self._active_video_lite_mode = False
        self.video_heavy_size_mb_threshold = int(self.settings.value("video_heavy_size_mb", 180, type=int))
        self.video_auto_lite_mode = self.settings.value("video_auto_lite_mode", True, type=bool)
        self.video_auto_cache_1080p = self.settings.value("video_auto_cache_1080p", True, type=bool)
        self._warned_heavy_videos: set[str] = set()
        self._video_probe_cache: dict[str, dict[str, str | int]] = {}

        # Windows
        self.canvas = DMCanvas()
        self.player = PlayerWindow()
        self.player_enabled = False
        self.player_mode = "Fullscreen"
        self.screens = []

        self.statusBar().showMessage("Ready")

        # ---------- UI ----------
        root = QWidget()
        root.setObjectName("vfRoot")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        v.addLayout(row1)
        self.btn_open = QPushButton("Open Map")
        self.btn_import_token = QPushButton("Import Token")
        self.btn_token_tool = QPushButton("Token tool")
        self.btn_token_tool.setCheckable(True)
        self.btn_rot_l = QPushButton("⟲ Rotate")
        self.btn_rot_r = QPushButton("⟳ Rotate")
        self.btn_zoom_reset = QPushButton("Reset zoom")
        self.btn_zoom_reset.installEventFilter(self)
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save As")
        self.btn_load = QPushButton("Load Session")
        self.btn_recent = QPushButton("Recent…")
        self.btn_help = QPushButton("Help")
        self.btn_open.setProperty("vfRole", "primary")
        self.btn_load.setProperty("vfRole", "secondary")
        self.btn_recent.setProperty("vfRole", "secondary")
        self.btn_save.setProperty("vfRole", "secondary")
        self.btn_save_as.setProperty("vfRole", "secondary")
        self.btn_help.setProperty("vfRole", "ghost")
        row1.addWidget(self.btn_open)
        row1.addWidget(self.btn_rot_l)
        row1.addWidget(self.btn_rot_r)
        row1.addWidget(self.btn_zoom_reset)
        row1.addWidget(self.btn_load)
        row1.addWidget(self.btn_recent)
        row1.addWidget(self.btn_save)
        row1.addWidget(self.btn_save_as)
        row1.addWidget(self.btn_help)
        row1.addStretch(1)

        # Token controls line (under Open Map)
        row1b = QHBoxLayout()
        row1b.setSpacing(6)
        v.addLayout(row1b)
        self.btn_import_token.setProperty("vfRole", "secondary")
        self.btn_token_tool.setProperty("vfRole", "toggle")
        row1b.addWidget(self.btn_import_token)
        row1b.addWidget(self.btn_token_tool)
        row1b.addStretch(1)

        row1.addWidget(QLabel("Target screen"))
        self.cmb_screen = QComboBox()
        row1.addWidget(self.cmb_screen)

        row1.addWidget(QLabel("Player mode"))
        self.cmb_player_mode = QComboBox()
        self.cmb_player_mode.addItems(["Fullscreen", "Window"])
        row1.addWidget(self.cmb_player_mode)

        # Player toggle + Fog toggle + Donate (DM side)
        self.btn_player = QPushButton("Player Screen: OFF")
        self.btn_player.setCheckable(True)
        self.btn_player.setProperty("vfRole", "toggle")

        # Button that toggles the fog on the Player view. The label shows the
        # action that will be performed when clicked ("Fog : Off" will remove
        # the fog; "Fog : On" will re-apply it).
        self.btn_fog = QPushButton("Fog : Off")
        self.btn_fog.setCheckable(True)
        self.btn_fog.setToolTip("Toggle Fog on Player view (applies to images and videos)")
        self.btn_fog.setProperty("vfRole", "toggle")

        self.btn_donate = QPushButton("Donate ❤")
        self.btn_donate.setToolTip("Support Veilforge development")
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donate.setProperty("vfRole", "accent")

        # Keep top bar height consistent
        try:
            _h = self.btn_help.sizeHint().height()
        except Exception:
            _h = 26
        self.btn_player.setMinimumHeight(_h)
        self.btn_fog.setMinimumHeight(_h)
        self.btn_donate.setMinimumHeight(_h)

        # Arrange Player + Fog vertically, Donate to the right
        _player_box = QWidget()
        _player_vlay = QVBoxLayout(_player_box)
        _player_vlay.setSpacing(4)
        _player_vlay.setContentsMargins(0, 0, 0, 0)
        _player_vlay.addWidget(self.btn_player)

        _right_box = QWidget()
        _right_lay = QHBoxLayout(_right_box)
        _right_lay.setSpacing(6)
        _right_lay.setContentsMargins(0, 0, 0, 0)
        _right_lay.addWidget(_player_box)
        _right_lay.addWidget(self.btn_donate)
        row1.addWidget(_right_box)

        # Explicit top-right version badge to avoid ambiguity across builds.
        self.lbl_version_badge = QLabel(f"v{__version__}")
        self.lbl_version_badge.setObjectName("vfVersionBadge")
        self.lbl_version_badge.setToolTip("Application version")
        row1.addWidget(self.lbl_version_badge)

        # Connect fog toggle
        self.btn_fog.clicked.connect(lambda: self._toggle_fog())

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        v.addLayout(row2)
        self.btn_undo = QPushButton("Undo Fog")
        self.btn_redo = QPushButton("Redo Fog")
        self.btn_reset = QPushButton("Reset Fog")
        self.btn_undo.setProperty("vfRole", "secondary")
        self.btn_redo.setProperty("vfRole", "secondary")
        self.btn_reset.setProperty("vfRole", "danger")
        row2.addWidget(self.btn_undo)
        row2.addWidget(self.btn_redo)
        row2.addWidget(self.btn_reset)
        # Move Fog toggle next to Reset Fog (to the right)
        row2.addWidget(self.btn_fog)
        row2.addStretch(1)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        v.addLayout(row3)
        row3.addWidget(QLabel("Brush size"))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(5, 250)
        self.size_slider.setValue(40)
        row3.addWidget(self.size_slider)

        row3.addWidget(QLabel("FOV softness"))
        self.soft_slider = QSlider(Qt.Orientation.Horizontal)
        self.soft_slider.setRange(0, 100)
        self.soft_slider.setValue(20)
        row3.addWidget(self.soft_slider)

        row3.addWidget(QLabel("DM fog alpha"))
        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.setValue(140)
        row3.addWidget(self.alpha_slider)

        row4 = QHBoxLayout()
        row4.setSpacing(6)
        v.addLayout(row4)

        # Grid controls
        self.chk_grid = QCheckBox("Grid")
        self.chk_grid.setToolTip("Enable grid overlay on the map. When enabled, Type defaults to 'Square' if unset.")
        self.cmb_grid = QComboBox()
        self.cmb_grid.addItems(["None", "Square", "Hex"])
        self.cmb_grid.setToolTip("Select grid type. If Grid is enabled and Type is 'None', 'Square' will be selected by default.")
        self.spin_grid = QSpinBox()
        self.spin_grid.setRange(5, 500)
        self.spin_grid.setValue(70)
        self.grid_alpha = QSlider(Qt.Orientation.Horizontal)
        self.grid_alpha.setRange(0, 255)
        self.grid_alpha.setValue(130)
        self.chk_grid_player = QCheckBox("Show on Player")
        self.chk_grid_player.setChecked(True)
        self.btn_grid_cal = QPushButton("Calibrate")
        self.btn_grid_cal.setProperty("vfRole", "secondary")

        row4.addWidget(self.chk_grid)
        row4.addWidget(QLabel("Type"))
        row4.addWidget(self.cmb_grid)
        row4.addWidget(QLabel("Cell(px map)"))
        row4.addWidget(self.spin_grid)
        row4.addWidget(QLabel("Grid alpha"))
        row4.addWidget(self.grid_alpha)
        row4.addWidget(self.chk_grid_player)
        row4.addWidget(self.btn_grid_cal)
        row4.addSpacing(16)

        # Annotate controls
        self.chk_annotate = QCheckBox("Annotate")
        self.chk_snap = QCheckBox("Snap")
        self.chk_snap.setChecked(False)
        self.chk_snap.setVisible(False)
        self.btn_color = QPushButton("Color")
        self.spin_draw_w = QSpinBox()
        self.spin_draw_w.setRange(1, 50)
        self.spin_draw_w.setValue(6)
        self.cmb_dash = QComboBox()
        self.cmb_dash.addItems(["Solid", "Dashed", "Dotted"])
        self.slider_draw_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_draw_alpha.setRange(10, 255)
        self.slider_draw_alpha.setValue(220)

        row4.addWidget(self.chk_annotate)
        row4.addWidget(self.chk_snap)
        row4.addWidget(self.btn_color)
        row4.addWidget(QLabel("Width"))
        row4.addWidget(self.spin_draw_w)
        row4.addWidget(QLabel("Style"))
        row4.addWidget(self.cmb_dash)
        row4.addWidget(QLabel("Alpha"))
        row4.addWidget(self.slider_draw_alpha)

        # Delete annotation (last stroke). Hold CTRL to clear all.
        self.btn_del_anno = QPushButton("Delete annotation")
        self.btn_del_anno.setToolTip("Delete last annotation stroke\n(hold CTRL to delete all annotations)")
        self.btn_del_anno.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_anno.setProperty("vfRole", "danger")
        row4.addWidget(self.btn_del_anno)
        row4.addStretch(1)

        # Player physical calibration + pan
        row5 = QHBoxLayout()
        row5.setSpacing(6)
        v.addLayout(row5)
        self.btn_calib_display = QPushButton('Calibrate 10"')
        self.lbl_ppi = QLabel(f"ppi: {self.px_per_inch_real:.2f}")
        self.btn_pl_left = QPushButton("⟵")
        self.btn_pl_right = QPushButton("⟶")
        self.btn_pl_up = QPushButton("⟰")
        self.btn_pl_down = QPushButton("⟱")
        self.btn_pl_center = QPushButton("Center Player")
        self.btn_calib_display.setProperty("vfRole", "secondary")
        self.btn_pl_left.setProperty("vfRole", "secondary")
        self.btn_pl_right.setProperty("vfRole", "secondary")
        self.btn_pl_up.setProperty("vfRole", "secondary")
        self.btn_pl_down.setProperty("vfRole", "secondary")
        self.btn_pl_center.setProperty("vfRole", "secondary")
        row5.addWidget(self.btn_calib_display)
        row5.addWidget(self.lbl_ppi)
        row5.addSpacing(12)
        row5.addWidget(QLabel("Player pan"))
        row5.addWidget(self.btn_pl_left)
        row5.addWidget(self.btn_pl_right)
        row5.addWidget(self.btn_pl_up)
        row5.addWidget(self.btn_pl_down)
        row5.addWidget(self.btn_pl_center)
        row5.addStretch(1)

        # Canvas frame
        self.canvas_frame = QFrame()
        self.canvas_frame.setObjectName("vfCanvasFrame")
        self.canvas_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.canvas_stack = QStackedLayout(self.canvas_frame)
        self.canvas_stack.setContentsMargins(0, 0, 0, 0)
        self.canvas_stack.addWidget(self.canvas)
        self.canvas_stack.addWidget(self.video_widget)
        self.canvas_stack.setCurrentWidget(self.canvas)

        # DM navigation scrollbars (shown only when zoomed in and pannable).
        self.dm_h_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.dm_v_scroll = QScrollBar(Qt.Orientation.Vertical)
        self.dm_h_scroll.setVisible(False)
        self.dm_v_scroll.setVisible(False)
        self._syncing_dm_scrollbars = False
        self._dm_scroll_scale = 10000

        self.canvas_wrap = QWidget()
        self.canvas_wrap.setObjectName("vfCanvasWrap")
        self.canvas_wrap_grid = QGridLayout(self.canvas_wrap)
        self.canvas_wrap_grid.setContentsMargins(0, 0, 0, 0)
        self.canvas_wrap_grid.setHorizontalSpacing(0)
        self.canvas_wrap_grid.setVerticalSpacing(0)
        self.canvas_wrap_grid.addWidget(self.canvas_frame, 0, 0)
        self.canvas_wrap_grid.addWidget(self.dm_v_scroll, 0, 1)
        self.canvas_wrap_grid.addWidget(self.dm_h_scroll, 1, 0)
        self.canvas_wrap_grid.setColumnStretch(0, 1)
        self.canvas_wrap_grid.setRowStretch(0, 1)

        v.addWidget(self.canvas_wrap, 1)

        # CTA overlay (nice UX)
        self.cta_overlay = QWidget(self.canvas_frame)
        self.cta_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cta_overlay.setStyleSheet("background: rgba(0,0,0,180);")
        ol = QVBoxLayout(self.cta_overlay)
        ol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Veilforge")
        title.setStyleSheet("color: white; font-size: 30px; font-weight: 800;")
        subtitle = QLabel("Load a map or resume a saved session.")
        subtitle.setStyleSheet("color: rgba(255,255,255,210); font-size: 14px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btns = QHBoxLayout()
        self.cta_open = QPushButton("Open Map")
        self.cta_load = QPushButton("Load Session")
        self.cta_open.setProperty("vfRole", "primary")
        self.cta_load.setProperty("vfRole", "secondary")
        self.cta_open.setMinimumWidth(150)
        self.cta_load.setMinimumWidth(150)
        btns.addWidget(self.cta_open)
        btns.addWidget(self.cta_load)
        ol.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        ol.addSpacing(8)
        ol.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        ol.addSpacing(18)
        ol.addLayout(btns)

        # ---------- Signals ----------
        self.btn_open.clicked.connect(self.open_map)
        self.btn_import_token.clicked.connect(self.import_token)
        self.btn_token_tool.toggled.connect(self.on_token_tool_toggled)
        self.cta_open.clicked.connect(self.open_map)
        self.btn_load.clicked.connect(self.load_session_dialog)
        self.btn_recent.clicked.connect(self.open_recent_sessions)
        self.cta_load.clicked.connect(self.load_session_dialog)
        self.btn_save.clicked.connect(self.save_session_quick)
        self.btn_save_as.clicked.connect(self.save_session_as_dialog)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_donate.clicked.connect(self.open_donate)

        self.btn_rot_l.clicked.connect(lambda: self.rotate_map(-90))
        self.btn_rot_r.clicked.connect(lambda: self.rotate_map(90))

        self.btn_undo.clicked.connect(self.canvas.undo)
        self.btn_redo.clicked.connect(self.canvas.redo)
        self.btn_reset.clicked.connect(self.canvas.reset_fog)

        self.size_slider.valueChanged.connect(self.on_size)
        self.soft_slider.valueChanged.connect(self.on_softness)
        self.alpha_slider.valueChanged.connect(self.on_alpha)

        self.cmb_player_mode.currentTextChanged.connect(self.on_player_mode_changed)
        self.btn_player.toggled.connect(self.toggle_player_screen)

        self.canvas.maskChanged.connect(self.sync_player_mask)
        self.canvas.drawingsChanged.connect(self.sync_player_drawings)
        self.canvas.tokensChanged.connect(self.sync_player_tokens)
        self.canvas.viewChanged.connect(self._on_canvas_view_changed)

        # Player view overlay drag (CTRL+LMB on DM canvas)
        self.canvas.playerViewCenterChanged.connect(self._on_player_view_dragged)

        self.chk_grid.toggled.connect(self.on_grid_changed)
        self.cmb_grid.currentTextChanged.connect(lambda _t: self.on_grid_changed())
        self.spin_grid.valueChanged.connect(lambda _v: self.on_grid_changed())
        self.grid_alpha.valueChanged.connect(lambda _v: self.on_grid_changed())
        self.chk_grid_player.toggled.connect(lambda _v: self.on_grid_changed())

        self.chk_annotate.toggled.connect(self.on_annotate_toggle)
        self.btn_color.clicked.connect(self.pick_color)
        self.spin_draw_w.valueChanged.connect(lambda _v: self.on_draw_style_changed())
        self.cmb_dash.currentTextChanged.connect(lambda _t: self.on_draw_style_changed())
        self.slider_draw_alpha.valueChanged.connect(lambda _v: self.on_draw_style_changed())


        self.btn_del_anno.clicked.connect(self.delete_annotation)
        self.chk_snap.toggled.connect(self.canvas.set_snap_to_grid)

        self.btn_grid_cal.clicked.connect(self._start_grid_calibration)
        self.canvas.gridCalibrated.connect(self.on_grid_calibrated)
        self.dm_h_scroll.valueChanged.connect(self._on_dm_h_scroll_changed)
        self.dm_v_scroll.valueChanged.connect(self._on_dm_v_scroll_changed)

        self.btn_calib_display.clicked.connect(self.calibrate_display_dialog)
        self.btn_pl_left.clicked.connect(lambda: self.pan_player(-1, 0))
        self.btn_pl_right.clicked.connect(lambda: self.pan_player(1, 0))
        self.btn_pl_up.clicked.connect(lambda: self.pan_player(0, -1))
        self.btn_pl_down.clicked.connect(lambda: self.pan_player(0, 1))
        self.btn_pl_center.clicked.connect(self.center_player_view)

        self.refresh_screens()
        inst = QGuiApplication.instance()
        if inst is not None:
            inst.screenAdded.connect(lambda _s: self.refresh_screens())
            inst.screenRemoved.connect(lambda _s: self.refresh_screens())

        self._apply_tactical_theme()

        self.resize(1340, 920)
        self._update_cta_visibility()
        self.btn_color.setStyleSheet("background: rgba(255,0,0,180);")
        self._update_window_title()
        QTimer.singleShot(0, self._sync_overlay_geometry)

    def _build_tactical_stylesheet(self) -> str:
        """Tactical Studio V2: high-contrast, game-table oriented UI language."""
        return """
QWidget#vfRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f151a, stop:1 #111b22);
    color: #dbe6ef;
}

QLabel {
    color: #b8c8d8;
    font-size: 12px;
}

QFrame#vfCanvasFrame, QWidget#vfCanvasWrap {
    background: #0d1318;
    border: 1px solid #2c4558;
    border-radius: 12px;
}

QPushButton {
    background: #16232e;
    color: #d8e4ee;
    border: 1px solid #2f4b60;
    border-radius: 9px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}

QPushButton:hover {
    background: #1a2c39;
    border-color: #4f7391;
}

QPushButton:pressed {
    background: #11202a;
}

QPushButton[vfRole="primary"] {
    background: #b88a1b;
    color: #0f151a;
    border-color: #d8ad41;
    font-weight: 800;
}

QPushButton[vfRole="primary"]:hover {
    background: #c89a23;
    border-color: #e2bb58;
}

QPushButton[vfRole="secondary"] {
    background: #1a2a36;
    color: #dce7f0;
    border-color: #3f5f76;
}

QPushButton[vfRole="toggle"] {
    background: #21303b;
}

QPushButton[vfRole="toggle"]:checked {
    background: #2f5d7e;
    color: #f2f8fc;
    border-color: #6aa2cc;
}

QPushButton[vfRole="accent"] {
    background: #a4384b;
    color: #fff4f6;
    border-color: #ce5c71;
    font-weight: 800;
}

QPushButton[vfRole="accent"]:hover {
    background: #bb4459;
    border-color: #df7288;
}

QPushButton[vfRole="danger"] {
    background: #3a1f23;
    color: #ffd7db;
    border-color: #a44f58;
}

QPushButton[vfRole="danger"]:hover {
    background: #4a262b;
}

QPushButton[vfRole="ghost"] {
    background: transparent;
    color: #b8c8d8;
    border-color: #3d5468;
}

QComboBox, QSpinBox {
    background: #14222d;
    color: #dbe6ef;
    border: 1px solid #365367;
    border-radius: 9px;
    padding: 4px 8px;
    min-height: 24px;
}

QComboBox:hover, QSpinBox:hover {
    border-color: #5f88a8;
}

QSlider::groove:horizontal {
    border: 1px solid #324d61;
    height: 6px;
    background: #1b2d3a;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #d2a543;
    border: 1px solid #e3bc66;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}

QCheckBox {
    spacing: 6px;
    color: #d8e4ee;
    font-weight: 600;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid #55748c;
    background: #12202a;
}

QCheckBox::indicator:checked {
    background: #2f5d7e;
    border-color: #6aa2cc;
}

QScrollBar:horizontal, QScrollBar:vertical {
    background: #13212b;
    border: 1px solid #30495c;
    border-radius: 8px;
    margin: 2px;
}

QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
    background: #5a809e;
    border-radius: 7px;
    min-width: 24px;
    min-height: 24px;
}

QStatusBar {
    background: #111c24;
    border-top: 1px solid #2f485a;
    color: #b8c8d8;
}

QToolTip {
    background: #091015;
    color: #e7f0f7;
    border: 1px solid #3e617a;
    border-radius: 8px;
    padding: 6px 8px;
}

QLabel#vfVersionBadge {
    color: #f7df9a;
    background: #1a2a36;
    border: 1px solid #4f7391;
    border-radius: 10px;
    padding: 2px 8px;
    font-weight: 800;
}
"""

    def _apply_tactical_theme(self) -> None:
        """Apply Tactical Studio V2 theme to the main window."""
        try:
            self.setFont(QFont("Bahnschrift", 10))
        except Exception:
            pass
        self.setStyleSheet(self._build_tactical_stylesheet())
    
    def _on_player_view_dragged(self, center_map):
        """
        Receives from the DM canvas the new Player view center (map coordinates)
        when dragging the overlay, and updates the player view.
        """
        if center_map is None:
            return

        try:
            # salva centro in map coords
            self.player_view_center = QPointF(float(center_map.x()), float(center_map.y()))
        except Exception:
            return

        # refresh view (se esiste già la funzione)
        if hasattr(self, "update_player_view"):
            try:
                self.update_player_view()
            except Exception:
                pass

    # ---------- Overlay ----------

    def eventFilter(self, obj, event):
        # Require double click on "Reset zoom" button
        if obj is getattr(self, "btn_zoom_reset", None):
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self.canvas.reset_zoom()
                return True
            # swallow single click (do nothing)
            if event.type() == QEvent.Type.MouseButtonPress:
                return True
        return super().eventFilter(obj, event)

    def _sync_overlay_geometry(self):
        self.cta_overlay.setGeometry(self.canvas_frame.rect())

    def _sync_video_grid_overlay(self):
        """Keep DM video grid settings in sync while video mode is active."""
        try:
            self.video_widget.set_grid(
                self.chk_grid.isChecked(),
                self.cmb_grid.currentText(),
                self.spin_grid.value(),
                self.grid_alpha.value(),
            )
        except Exception:
            pass

    def _video_cache_dir(self) -> Path:
        d = self._app_dir() / "data" / "video_cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _find_ffmpeg(self) -> str | None:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        # Portable fallback (if user bundles ffmpeg near the app)
        candidates = [
            self._app_dir() / "ffmpeg.exe",
            self._app_dir() / "_internal" / "ffmpeg.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return None

    def _find_ffprobe(self) -> str | None:
        exe = shutil.which("ffprobe")
        if exe:
            return exe
        ffmpeg = self._find_ffmpeg()
        if ffmpeg:
            p = Path(ffmpeg)
            cand = p.with_name("ffprobe.exe")
            if cand.exists():
                return str(cand)
        return None

    def _probe_video_stream_info(self, path: Path) -> dict[str, str | int]:
        """Best-effort metadata probe (codec/width/height) for heavy-video detection."""
        try:
            st = path.stat()
            cache_key = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            cache_key = str(path.resolve())

        cached = self._video_probe_cache.get(cache_key)
        if cached is not None:
            return cached

        info: dict[str, str | int] = {"codec": "", "width": 0, "height": 0}

        # Preferred path: ffprobe if available.
        ffprobe = self._find_ffprobe()
        if ffprobe:
            try:
                proc = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=codec_name,width,height",
                        "-of",
                        "default=nw=1:nk=1",
                        str(path),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=8,
                )
                if proc.returncode == 0:
                    vals = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
                    for v in vals:
                        if v.isdigit():
                            n = int(v)
                            if info["width"] == 0:
                                info["width"] = n
                            elif info["height"] == 0:
                                info["height"] = n
                        elif not info["codec"]:
                            info["codec"] = v.lower()
            except Exception:
                pass

        # Fallback: parse ffmpeg banner "Video: codec ..., WxH".
        if (int(info.get("width", 0)) == 0 or int(info.get("height", 0)) == 0 or not str(info.get("codec", ""))):
            ffmpeg = self._find_ffmpeg()
            if ffmpeg:
                try:
                    proc = subprocess.run(
                        [ffmpeg, "-hide_banner", "-i", str(path)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=8,
                    )
                    banner = (proc.stderr or "") + "\n" + (proc.stdout or "")
                    m = re.search(r"Video:\s*([a-zA-Z0-9_]+).*?(\d{3,5})x(\d{3,5})", banner, re.IGNORECASE | re.DOTALL)
                    if m:
                        info["codec"] = str(info.get("codec") or m.group(1)).lower()
                        if int(info.get("width", 0)) == 0:
                            info["width"] = int(m.group(2))
                        if int(info.get("height", 0)) == 0:
                            info["height"] = int(m.group(3))
                except Exception:
                    pass

        self._video_probe_cache[cache_key] = info
        return info

    def _is_heavy_video(self, path: Path) -> tuple[bool, str, dict[str, str | int]]:
        """Classify likely-problematic videos using fast heuristics.

        Uses file heuristics + best-effort stream metadata (codec/resolution).
        """
        reasons: list[str] = []
        info = self._probe_video_stream_info(path)
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb >= float(self.video_heavy_size_mb_threshold):
                reasons.append(f"taille {size_mb:.1f} MB")
        except Exception:
            pass

        name_l = path.name.lower()
        if "4k" in name_l or "2160" in name_l:
            reasons.append("nom/fichier indique 4K")

        width = int(info.get("width", 0) or 0)
        height = int(info.get("height", 0) or 0)
        codec = str(info.get("codec", "") or "").lower()

        if width >= 3840 or height >= 2160:
            reasons.append(f"flux 4K ({width}x{height})")
        if codec in {"vp9", "av1"}:
            reasons.append(f"codec coûteux ({codec})")

        # Conservative fallback when metadata probing is unavailable.
        if not reasons:
            ext = path.suffix.lower()
            try:
                size_mb = path.stat().st_size / (1024 * 1024)
            except Exception:
                size_mb = 0.0
            if ext in {".mkv", ".webm"} and size_mb >= 60.0:
                reasons.append(f"conteneur {ext} potentiellement lourd ({size_mb:.1f} MB)")

        if reasons:
            return True, ", ".join(reasons), info
        return False, "", info

    def _warn_heavy_video_once(self, src: Path, reason: str) -> None:
        key = str(src.resolve())
        if key in self._warned_heavy_videos:
            return
        self._warned_heavy_videos.add(key)
        try:
            QMessageBox.information(
                self,
                "Heavy video detected",
                (
                    f"This video is likely heavy for real-time playback ({reason}).\n\n"
                    "Veilforge will enable a lighter render profile and, if ffmpeg is available,\n"
                    "try a cached 1080p version for smoother playback."
                ),
            )
        except Exception:
            pass

    def _cache_video_1080p(self, src: Path) -> Path | None:
        """Create or reuse a cached 1080p transcode for heavy videos.

        Returns None when ffmpeg is unavailable or conversion fails, in which case
        playback falls back to the original source.
        """
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return None

        try:
            st = src.stat()
            sig = f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            sig = str(src.resolve())
        key = hashlib.sha1(sig.encode("utf-8", errors="ignore")).hexdigest()[:16]
        out = self._video_cache_dir() / f"{src.stem}.{key}.1080p.mp4"

        if out.exists() and out.stat().st_size > 0:
            return out

        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale='min(1920,iw)':-2",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(out),
        ]

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Preparing 1080p cache for smoother playback...", 0)
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        finally:
            try:
                QGuiApplication.restoreOverrideCursor()
            except Exception:
                pass

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            self.statusBar().showMessage("1080p cached copy ready.", 2200)
            return out

        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass
        self.statusBar().showMessage("1080p cache creation failed, fallback to original video.", 3200)
        return None

    def _prepare_video_source(self, path: str) -> tuple[str, bool]:
        """Resolve final video source and rendering profile.

        Output tuple:
        - source path to play (original or cached 1080p)
        - whether lite render profile should be enabled
        """
        src = Path(path).resolve()
        heavy, reason, info = self._is_heavy_video(src)
        use_lite = bool(heavy and self.video_auto_lite_mode)

        width = int(info.get("width", 0) or 0)
        height = int(info.get("height", 0) or 0)
        codec = str(info.get("codec", "") or "").lower()
        is_4k = width >= 3840 or height >= 2160

        # Requested policy: VP9 + 4K always forces lite mode.
        if codec == "vp9" and is_4k:
            use_lite = True

        if heavy:
            self._warn_heavy_video_once(src, reason)

        # Requested policy: apply 1080p cache attempt to all heavy videos.
        if heavy:
            cached = self._cache_video_1080p(src)
            if cached is not None:
                self.statusBar().showMessage(f"Playing cached 1080p: {cached.name}", 2600)
                return str(cached), use_lite

        return str(src), use_lite

    def _apply_video_render_profile(self, lite: bool) -> None:
        self._active_video_lite_mode = bool(lite)
        if self._active_video_lite_mode:
            self._min_video_frame_interval = self._video_lite_frame_interval
            self._max_video_display_width = self._video_lite_max_width
            self.statusBar().showMessage("Video lite mode enabled (lower frame processing load).", 2600)
        else:
            self._min_video_frame_interval = self._video_default_frame_interval
            self._max_video_display_width = self._video_default_max_width

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_overlay_geometry()
        self._sync_video_grid_overlay()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._sync_overlay_geometry)
        QTimer.singleShot(0, self._sync_video_grid_overlay)
        if not getattr(self, "_restore_prompt_shown", False):
            self._restore_prompt_shown = True
            QTimer.singleShot(50, self._prompt_autoload_recent)

    def _stop_media(self):
        """Stop and clean up the current media player.

        This ensures the active QMediaPlayer is disconnected from the video and audio
        outputs before it is deleted, avoiding stale references when a new media file
        is opened or when video mode is disabled.
        """
        if self.media_player is not None:
            try:
                self.media_player.stop()
            except Exception:
                pass
            try:
                self.media_player.setVideoOutput(None)
            except Exception:
                pass
            try:
                self.media_player.setAudioOutput(None)
            except Exception:
                pass
            self.media_player.deleteLater()
            self.media_player = None
        self.audio_output = None
        self.media_video_sink = None
        self.current_video_frame_img = None
        try:
            self.video_widget.set_frame(None)
        except Exception:
            pass
        try:
            self.player.set_external_video_frame(None)
        except Exception:
            pass

    def _on_dm_video_frame(self, frame):
        """Handle decoded DM video frames and share them with Player.

        This keeps a single decoder pipeline and prevents CPU spikes when
        Player screen is enabled with video + grid.
        CRITICAL: Minimal processing to avoid main thread blocking.
        """
        # Throttle frame updates to ~25fps (minimum for smooth playback)
        now = time.time()
        if now - self._last_video_frame_time < self._min_video_frame_interval:
            return
        self._last_video_frame_time = now
        
        try:
            # Convert frame to QImage - Qt hardware optimizes this
            img = frame.toImage()
            
            # FAST downscale if needed (FastTransformation, not SmoothTransformation!)
            # This uses simple nearest-neighbor for speed, good enough at 25fps
            if img is not None and not img.isNull() and img.width() > self._max_video_display_width:
                img = img.scaledToWidth(
                    self._max_video_display_width,
                    Qt.TransformationMode.FastTransformation
                )
        except Exception:
            img = None
        
        self.current_video_frame_img = img if img is not None and not img.isNull() else None
        self.video_widget.set_frame(self.current_video_frame_img)
        if self.player_enabled and getattr(self.loaded, 'is_video', False):
            try:
                self.player.set_external_video_frame(self.current_video_frame_img)
            except Exception:
                pass

    def _on_media_error(self, error, error_string):
        self.statusBar().showMessage(f"Media error: {error} – {error_string}", 5000)
        self._stop_media()
        self.canvas_stack.setCurrentWidget(self.canvas)

    def _set_video_mode(self, enabled: bool, path: str | None = None) -> None:
        """Switch between map canvas mode and video playback mode.

        The DM canvas and video widget are kept in a QStackedLayout so only one is
        visible at a time. When video mode is enabled, this method creates a new
        QMediaPlayer, attaches the QVideoWidget and QAudioOutput, and starts playback.
        Grid overlay visibility for DM video is refreshed here as well.
        """
        if enabled and path:
            self.canvas_stack.setCurrentWidget(self.video_widget)
            self._stop_media()
            try:
                playback_path, use_lite = self._prepare_video_source(path)
                self._apply_video_render_profile(use_lite)
                self.media_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.media_video_sink = QVideoSink(self)
                self.audio_output.setVolume(1.0)
                self.media_player.setVideoOutput(self.media_video_sink)
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.errorOccurred.connect(self._on_media_error)
                self.media_video_sink.videoFrameChanged.connect(self._on_dm_video_frame)
                self.media_player.setSource(QUrl.fromLocalFile(playback_path))
                if hasattr(QMediaPlayer, 'setLoops') and hasattr(QMediaPlayer, 'Loops'):
                    self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
                self.media_player.play()
                self._sync_video_grid_overlay()
            except Exception as exc:
                self._stop_media()
                self.canvas_stack.setCurrentWidget(self.canvas)
                QMessageBox.critical(self, "Media playback error", f"Couldn't play media:\n{exc}")
        else:
            self.canvas_stack.setCurrentWidget(self.canvas)
            self._stop_media()
            self._apply_video_render_profile(False)
            self._sync_video_grid_overlay()

        if enabled:
            self.dm_h_scroll.setVisible(False)
            self.dm_v_scroll.setVisible(False)

    def _on_canvas_view_changed(self, map_w: float, map_h: float, left: float, top: float, vis_w: float, vis_h: float, zoom: float) -> None:
        """Sync DM scrollbars with canvas zoom/pan state.

        Scrollbars are shown only when the DM map is zoomed in and panning is
        possible on the corresponding axis.
        """
        if self._syncing_dm_scrollbars:
            return
        if self.canvas_stack.currentWidget() is not self.canvas:
            self.dm_h_scroll.setVisible(False)
            self.dm_v_scroll.setVisible(False)
            return

        can_pan_x = (map_w > 0.0) and (vis_w > 0.0) and ((map_w - vis_w) > 0.5)
        can_pan_y = (map_h > 0.0) and (vis_h > 0.0) and ((map_h - vis_h) > 0.5)
        show_x = (zoom > 1.0001) and can_pan_x
        show_y = (zoom > 1.0001) and can_pan_y

        self.dm_h_scroll.setVisible(show_x)
        self.dm_v_scroll.setVisible(show_y)

        scale = int(self._dm_scroll_scale)
        self._syncing_dm_scrollbars = True
        try:
            if can_pan_x:
                max_left = max(1e-6, float(map_w - vis_w))
                ratio_x = max(0.0, min(1.0, float(left) / max_left))
                self.dm_h_scroll.setRange(0, scale)
                self.dm_h_scroll.setPageStep(max(1, int(round((vis_w / max(map_w, 1e-6)) * scale))))
                self.dm_h_scroll.setValue(int(round(ratio_x * scale)))
            else:
                self.dm_h_scroll.setRange(0, 0)
                self.dm_h_scroll.setValue(0)

            if can_pan_y:
                max_top = max(1e-6, float(map_h - vis_h))
                ratio_y = max(0.0, min(1.0, float(top) / max_top))
                self.dm_v_scroll.setRange(0, scale)
                self.dm_v_scroll.setPageStep(max(1, int(round((vis_h / max(map_h, 1e-6)) * scale))))
                self.dm_v_scroll.setValue(int(round(ratio_y * scale)))
            else:
                self.dm_v_scroll.setRange(0, 0)
                self.dm_v_scroll.setValue(0)
        finally:
            self._syncing_dm_scrollbars = False

    def _on_dm_h_scroll_changed(self, value: int) -> None:
        """Pan DM viewport horizontally from bottom scrollbar value."""
        if self._syncing_dm_scrollbars:
            return
        if self.canvas_stack.currentWidget() is not self.canvas:
            return
        if self.dm_h_scroll.maximum() <= self.dm_h_scroll.minimum():
            return
        src = self.canvas._current_view_src()
        m = getattr(self.canvas, "_map", None)
        if m is None:
            return
        map_w = float(m.width())
        vis_w = float(src.width())
        max_left = max(0.0, map_w - vis_w)
        ratio = float(value) / float(self._dm_scroll_scale)
        new_left = ratio * max_left
        self.canvas.set_view_origin(new_left, float(src.top()))

    def _on_dm_v_scroll_changed(self, value: int) -> None:
        """Pan DM viewport vertically from right scrollbar value."""
        if self._syncing_dm_scrollbars:
            return
        if self.canvas_stack.currentWidget() is not self.canvas:
            return
        if self.dm_v_scroll.maximum() <= self.dm_v_scroll.minimum():
            return
        src = self.canvas._current_view_src()
        m = getattr(self.canvas, "_map", None)
        if m is None:
            return
        map_h = float(m.height())
        vis_h = float(src.height())
        max_top = max(0.0, map_h - vis_h)
        ratio = float(value) / float(self._dm_scroll_scale)
        new_top = ratio * max_top
        self.canvas.set_view_origin(float(src.left()), new_top)

    def _update_cta_visibility(self):
        self.cta_overlay.setVisible(self.map_img is None and (self.loaded is None or not getattr(self.loaded, 'is_video', False)))

    def _update_window_title(self):
        base = f"Veilforge {__version__} – Fog of War"
        try:
            if self.current_session_path is not None:
                self.setWindowTitle(f"{base}  |  {self.current_session_path.name}")
                return
            if self.loaded is not None and getattr(self.loaded, "source_path", None):
                self.setWindowTitle(f"{base}  |  {Path(self.loaded.source_path).name}")
                return
        except Exception:
            pass
        self.setWindowTitle(base)


    # ---------- Recent sessions / Auto-restore ----------
    def _get_recent_sessions(self) -> list[str]:
        try:
            v = self.settings.value(self.RECENT_SESSIONS_KEY, [])
        except Exception:
            v = []

        # PyQt/QSettings can return: list[str], tuple, QStringList-like, or a single string.
        if v is None:
            return []

        if isinstance(v, (list, tuple)):
            out = [str(x) for x in v if x]
            return out

        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            # JSON array stored as string?
            if (s.startswith("[") and s.endswith("]")):
                try:
                    arr = json.loads(s)
                    if isinstance(arr, list):
                        return [str(x) for x in arr if x]
                except Exception:
                    pass
            # Fallback delimiters
            for sep in ("|", ";", "\n"):
                if sep in s:
                    parts = [p.strip() for p in s.split(sep)]
                    return [p for p in parts if p]
            return [s]

        # Unknown type
        try:
            return [str(v)]
        except Exception:
            return []


    def _save_recent_sessions(self, items: list[str]) -> None:
        try:
            self.settings.setValue(self.RECENT_SESSIONS_KEY, items[: self.RECENT_MAX])
        except Exception:
            pass

    def _add_recent_session(self, session_path: Path) -> None:
        try:
            p = self._make_portable_path(Path(session_path))
        except Exception:
            p = str(session_path)
        items = [x for x in self._get_recent_sessions() if x and x != p]
        items.insert(0, p)
        self._save_recent_sessions(items)

    def _prompt_autoload_recent(self) -> None:
        try:
            if self.map_img is not None and hasattr(self.map_img, "isNull") and (not self.map_img.isNull()):
                return
        except Exception:
            pass

        items = self._get_recent_sessions()
        if not items:
            return

        last = None
        for s in items:
            try:
                if self._resolve_portable_path(s).exists():
                    last = s
                    break
            except Exception:
                continue
        if not last:
            return

        box = QMessageBox(self)
        box.setWindowTitle("Restore session?")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("I found a previous Veilforge session. Do you want to restore it?")
        box.setInformativeText(f"Last session:\n{self._resolve_portable_path(last).name}")

        btn_last = box.addButton("Load last", QMessageBox.ButtonRole.AcceptRole)
        btn_pick = box.addButton("Choose…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_last)

        box.exec()
        clicked = box.clickedButton()
        if clicked == btn_last:
            self._load_session_path(last)
        elif clicked == btn_pick:
            self.open_recent_sessions()

    def _load_session_path(self, path: str) -> None:
        # Ensure any active video playback is stopped before loading a new session.
        try:
            try:
                # stop player video and media to reset player display state
                self.player.stop_video()
            except Exception:
                pass
            path_res = str(self._resolve_portable_path(path))
            data = load_session(path_res)
            resolved_map = self._resolve_session_media_path(data.map_path, Path(path_res))
            if resolved_map is None:
                QMessageBox.warning(self, "Load cancelled", "Session loading cancelled: map/media file not found.")
                return

            previous_map_path = str(data.map_path)
            data.map_path = str(resolved_map)

            # Persist repaired path so future loads don't ask again.
            if previous_map_path != data.map_path:
                try:
                    save_session(path_res, data)
                except Exception:
                    pass

            self.loaded = load_map(data.map_path, pdf_page=data.pdf_page, pdf_dpi=data.pdf_dpi)
        except Exception as e:
            QMessageBox.critical(self, "Load error", f"Couldn't load session:\n{e}")
            return

        self.map_rotation_deg = int(getattr(data, "map_rotation_deg", 0) or 0) % 360
        if self.loaded.is_video:
            self.map_img = None
            self.canvas.set_images(None, None, drawings=[])
            self._set_video_mode(True, self.loaded.source_path)
        else:
            self.map_img = self.loaded.qimage
            self._set_video_mode(False, None)
            if self.map_rotation_deg:
                t = QTransform()
                t.rotate(self.map_rotation_deg)
                self.map_img = self.map_img.transformed(t)

            mask = QImage(data.mask_path)
            drawings = [Stroke.from_dict(d) for d in data.drawings]
            if mask.isNull():
                self.canvas.set_images(self.map_img, None, drawings=drawings)
                self.canvas.reset_fog()
            else:
                self.canvas.set_images(self.map_img, mask, drawings=drawings)

            # Restore session tokens after set_images, which clears token state.
            self.canvas.tokens = self._deserialize_tokens(getattr(data, "tokens", []))
            self.canvas.selected_token_index = -1
            self.canvas.tokensChanged.emit()
            self.canvas.update()

            g = data.grid or {}
            if g:
                self.chk_grid.setChecked(bool(g.get("enabled", False)))
                self.cmb_grid.setCurrentText(str(g.get("type", "None")))
                self.spin_grid.setValue(int(g.get("cell", 70)))
                self.grid_alpha.setValue(int(g.get("alpha", 130)))
                self.chk_grid_player.setChecked(bool(g.get("show_on_player", True)))
                self.on_grid_changed()

        self.current_session_path = self._resolve_portable_path(path)
        self._add_recent_session(self.current_session_path)
        self._update_window_title()
        self.statusBar().showMessage(f"Session loaded: {self.current_session_path.name}", 2600)
        self._update_cta_visibility()

        if self.player_enabled:
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.player.set_drawings(self.canvas.drawings)
            self.player.set_tokens(self.canvas.tokens)
            self.update_player_view()

    def open_recent_sessions(self) -> None:
        items = self._get_recent_sessions()
        existing, missing = [], []
        for s in items:
            try:
                (existing if self._resolve_portable_path(s).exists() else missing).append(s)
            except Exception:
                missing.append(s)

        if not existing and not missing:
            QMessageBox.information(self, "Recent sessions", "No recent sessions found.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Recent sessions")
        dlg.setModal(True)

        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Pick a session to load:"))

        lst = QListWidget()
        lst.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        for p in existing:
            it = QListWidgetItem(Path(p).name)
            it.setToolTip(p)
            it.setData(Qt.ItemDataRole.UserRole, p)
            lst.addItem(it)

        if missing:
            sep = QListWidgetItem("— missing files —")
            sep.setFlags(Qt.ItemFlag.NoItemFlags)
            lst.addItem(sep)
            for p in missing:
                it = QListWidgetItem(Path(p).name)
                it.setToolTip(p)
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                lst.addItem(it)

        v.addWidget(lst)

        btn_row = QHBoxLayout()
        btn_load = QPushButton("Load")
        btn_browse = QPushButton("Browse…")
        btn_clean = QPushButton("Clean missing")
        btn_close = QPushButton("Close")
        btn_row.addWidget(btn_load)
        btn_row.addWidget(btn_browse)
        btn_row.addWidget(btn_clean)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        v.addLayout(btn_row)

        def do_load():
            it = lst.currentItem()
            if not it:
                return
            pth = it.data(Qt.ItemDataRole.UserRole)
            if not pth:
                return
            if not self._resolve_portable_path(str(pth)).exists():
                QMessageBox.warning(dlg, "Missing", "That session file no longer exists.")
                return
            dlg.accept()
            self._load_session_path(str(pth))

        def do_browse():
            dlg.accept()
            self.load_session_dialog()

        def do_clean():
            cleaned = [p for p in self._get_recent_sessions() if p and self._resolve_portable_path(p).exists()]
            self._save_recent_sessions(cleaned)
            QMessageBox.information(dlg, "Cleaned", "Missing entries removed. Re-open Recent to refresh.")

        btn_load.clicked.connect(do_load)
        btn_browse.clicked.connect(do_browse)
        btn_clean.clicked.connect(do_clean)
        btn_close.clicked.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda *_: do_load())

        dlg.exec()

    # ---------- Help ----------
    def open_donate(self):
        """Open the PayPal donate page in the default browser."""
        QDesktopServices.openUrl(QUrl("https://www.paypal.com/donate/?hosted_button_id=RBLTMBPZCV5QL"))

    def show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Veilforge – Help")
        dlg.resize(920, 640)
        lay = QVBoxLayout(dlg)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- Tab: README ---
        tab_readme = QWidget()
        tr = QHBoxLayout(tab_readme)

        readme_box = QTextEdit()
        readme_box.setReadOnly(True)

        # Load README.md from repo root (fallback to built-in HELP_TEXT)
        try:
            readme_path = Path(__file__).resolve().parent.parent / "HELP_README.md"
            md = readme_path.read_text(encoding="utf-8")
            readme_box.setMarkdown(md)
        except Exception:
            readme_box.setPlainText(HELP_TEXT)

        tr.addWidget(readme_box, stretch=3)

        side = QWidget()
        sr = QVBoxLayout(side)
        sr.setContentsMargins(6, 6, 6, 6)

        qr_title = QLabel("Donate")
        qr_title.setStyleSheet("font-size: 16px; font-weight: 800;")
        sr.addWidget(qr_title)

        qr = QLabel()
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setMinimumWidth(220)

        qr_path_candidates = [
            Path(__file__).resolve().parent.parent / "assets" / "donate_qr.png",
            Path(__file__).resolve().parent.parent / "assets" / "Codice QR.png",
        ]
        for p in qr_path_candidates:
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    qr.setPixmap(pm.scaledToWidth(210, Qt.TransformationMode.SmoothTransformation))
                    break
        sr.addWidget(qr)

        qr_hint = QLabel("Scan the QR to donate\n(or smash the button)")
        qr_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_hint.setStyleSheet("color: rgba(255,255,255,210); font-size: 11px;")
        sr.addWidget(qr_hint)

        donate_btn = QPushButton("Donate ❤")
        donate_btn.setFixedHeight(34)
        donate_btn.setStyleSheet(
            "QPushButton{background:#ff4d8d;color:white;border:none;border-radius:10px;padding:6px 12px;font-weight:800;font-size:14px;}"
            "QPushButton:hover{background:#ff2f79;}"
            "QPushButton:pressed{background:#e6286b;}"
        )
        donate_btn.clicked.connect(self.open_donate)
        sr.addWidget(donate_btn)

        updates_btn = QPushButton("Look for updates")
        updates_btn.setFixedHeight(34)
        updates_btn.setToolTip("Open the Veilforge GitHub repository")
        updates_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        updates_btn.setStyleSheet(
            "QPushButton{background:#2d7dd2;color:white;border:none;border-radius:10px;padding:6px 12px;font-weight:800;font-size:14px;}"
            "QPushButton:hover{background:#4a90e2;}"
            "QPushButton:pressed{background:#1f66b3;}"
        )
        updates_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Help3D-Padova/Veilforge")))
        sr.addWidget(updates_btn)

        sr.addStretch(1)
        tr.addWidget(side, stretch=1)
        tabs.addTab(tab_readme, "README")

        # --- Tab: Credits ---
        tab_credits = QWidget()
        tc = QVBoxLayout(tab_credits)
        credits_box = QTextEdit()
        credits_box.setReadOnly(True)
        credits_box.setMarkdown(
            "# Credits\n"
            "\n"
            "**Programming:** Andrea Pirazzini\n"
            "\n"
            "**AI co-developer:** Kai Vector\n"
            "\n"
            "Thanks to everyone testing, breaking, and rebuilding this thing. 🛠️"
        )
        tc.addWidget(credits_box)
        tabs.addTab(tab_credits, "Credits")

        # --- Tab: Use license ---
        tab_license = QWidget()
        tl = QVBoxLayout(tab_license)
        lic_box = QTextEdit()
        lic_box.setReadOnly(True)
        # Load LICENSE.md from repo root (fallback to built-in text)
        try:
            lic_path = Path(__file__).resolve().parent.parent / "LICENSE.md"
            lic_md = lic_path.read_text(encoding="utf-8")
            lic_box.setMarkdown(lic_md)
        except Exception:
            lic_box.setMarkdown(
                "# Use License\n\n"
                "You may **use** this software for personal (non-commercial) purposes.\n\n"
                "You may **modify** it and **redistribute** the source code and/or binaries **as long as you clearly credit the original project and author(s)**.\n\n"
                "You may **not** monetize it. That means you cannot sell the software, sell derivatives, sell the source code, bundle it into a paid product, or charge for access to it.\n\n"
                "No warranty: this project is provided *as-is*."
            )

        tl.addWidget(lic_box)
        tabs.addTab(tab_license, "Use License")

        # Bottom bar
        bar = QHBoxLayout()
        bar.addStretch(1)
        b = QPushButton("Close")
        b.clicked.connect(dlg.accept)
        bar.addWidget(b)
        lay.addLayout(bar)

        dlg.exec()

    # ---------- Screens ----------
    def refresh_screens(self):
        self.screens = list(QGuiApplication.screens())
        self.cmb_screen.blockSignals(True)
        self.cmb_screen.clear()
        for i, s in enumerate(self.screens):
            g = s.geometry()
            name = s.name() or f"Screen {i}"
            self.cmb_screen.addItem(f"{i}: {name} ({g.width()}x{g.height()})", i)
        self.cmb_screen.blockSignals(False)
        self.cmb_screen.setCurrentIndex(1 if len(self.screens) >= 2 else 0)

    # ---------- UI handlers ----------
    def on_player_mode_changed(self, mode: str):
        self.player_mode = mode
        if self.player_enabled:
            self.toggle_player_screen(True)

    def on_size(self, val: int):
        self.canvas.brush_radius = int(val)
        self.canvas.update()

    def on_softness(self, val: int):
        self.canvas.brush_softness = float(val) / 100.0
        self.statusBar().showMessage("FOV softness applies to new strokes", 1800)

    def on_alpha(self, val: int):
        self.canvas.dm_fog_alpha = max(0, min(255, int(val)))
        self.canvas.update()

    def on_grid_changed(self, *_args):
        show = self.chk_grid.isChecked()
        gtype = self.cmb_grid.currentText()
        # If Grid is enabled and the type is still 'None', default to 'Square'
        if show and (not gtype or gtype == "None"):
            # update combobox selection and local variable
            idx = self.cmb_grid.findText("Square")
            if idx >= 0:
                self.cmb_grid.setCurrentIndex(idx)
            gtype = "Square"
        cell = self.spin_grid.value()
        alpha = self.grid_alpha.value()
        self.canvas.set_grid(show, gtype, cell, alpha)
        self.player.set_grid(self.chk_grid_player.isChecked() and show, gtype, cell, alpha)
        self._sync_video_grid_overlay()
        self.update_player_view()

    def _start_grid_calibration(self):
        gtype = self.cmb_grid.currentText()
        if gtype not in ("Square", "Hex"):
            QMessageBox.information(self, "Grid", "Select Square or Hex before calibrating.")
            return
        self.canvas.start_grid_calibration(gtype)

    def on_grid_calibrated(self, gtype: str, cell_map_px: int):
        self.chk_grid.setChecked(True)
        idx = self.cmb_grid.findText(gtype)
        if idx >= 0:
            self.cmb_grid.setCurrentIndex(idx)
        self.spin_grid.setValue(int(cell_map_px))
        self.on_grid_changed()
        self.statusBar().showMessage(f"✅ Grid calibrated ({gtype}) = {cell_map_px}px", 2500)

    def on_annotate_toggle(self, enabled: bool):
        self.canvas.set_annotate(enabled)
        self.on_draw_style_changed()
        self.canvas.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def pick_color(self):
        c = QColorDialog.getColor(QColor(*self.canvas.draw_color), self, "Pick draw color")
        if not c.isValid():
            return
        a = int(self.slider_draw_alpha.value())
        self.canvas.draw_color = (c.red(), c.green(), c.blue(), a)
        self.btn_color.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},180);")
        self.on_draw_style_changed()

    def on_draw_style_changed(self):
        r, g, b, _ = self.canvas.draw_color
        a = int(self.slider_draw_alpha.value())
        self.canvas.set_draw_style((r, g, b, a), self.spin_draw_w.value(), self.cmb_dash.currentText())
        self.canvas.update()

    def import_token(self):
        """Import a token image and add it to the DM canvas token layer.

        Tokens are stored in map-space and then synchronized to the Player
        window through `sync_player_tokens`.
        """
        if not self.loaded or not self.map_img:
            QMessageBox.information(self, "Import Token", "Load a map first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Token",
            str(Path(r'D:/_JDR_Ressources/Veilforge 2.7.0').resolve()),
            "Token images (*.png *.jpg *.jpeg);;All files (*.*)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import Token", "Invalid image file.")
            return
        self.canvas.add_token_image(img)
        self.statusBar().showMessage("Token imported", 1800)

    def on_token_tool_toggled(self, enabled: bool):
        """Enable/disable interactive token manipulation on the DM canvas.

        When enabled, mouse interactions target token move/resize/rotate and
        the fog brush is intentionally disabled to avoid accidental painting.
        """
        self.canvas.set_token_tool_enabled(bool(enabled))
        if enabled:
            self.statusBar().showMessage("Token tool enabled: drag to move, handle to resize/rotate", 2200)
        else:
            self.statusBar().showMessage("Token tool disabled", 1200)

    def delete_annotation(self):
        """Delete the last annotation stroke.
        Tip: hold CTRL while clicking to clear ALL annotations.
        """
        # Nothing to do
        if not getattr(self.canvas, "drawings", None):
            self.statusBar().showMessage("No annotations to delete.", 1800)
            return

        # CTRL = nuke all annotations (with confirmation)
        mods = QGuiApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Delete all annotations?")
            box.setText("This will delete ALL annotation strokes. Continue?")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            new_drawings = []
            msg = "🧽 All annotations deleted."
        else:
            # Delete last stroke
            new_drawings = list(self.canvas.drawings[:-1])
            msg = "🗑️ Deleted last annotation."

        # Re-apply drawings without touching fog/mask
        try:
            if self.map_img is None:
                self.canvas.drawings = new_drawings
                self.canvas.update()
            else:
                self.canvas.set_images(self.map_img, self.canvas.mask_img, drawings=new_drawings)
        except Exception:
            # Fallback: best-effort in case set_images signature changes
            try:
                self.canvas.drawings = new_drawings
                self.canvas.update()
            except Exception:
                pass

        # Sync to player view if enabled
        try:
            self.sync_player_drawings()
        except Exception:
            pass

        self.statusBar().showMessage(msg, 2200)

    # ---------- Player sync ----------
    def sync_player_mask(self):
        """Synchronize the Player's fog mask with the DM canvas.

        If `fog_enabled` is False we pass `None` as the mask so the Player will
        hide the overlay (for videos the overlay widget is hidden).
        """
        if self.player_enabled:
            mask = self.canvas.mask_img if getattr(self, 'fog_enabled', True) else None
            self.player.set_images(self.map_img, mask)
            self.update_player_view()

    def sync_player_drawings(self):
        if self.player_enabled:
            self.player.set_drawings(self.canvas.drawings)

    def sync_player_tokens(self):
        """Push the current DM token list to the Player window."""
        if self.player_enabled:
            self.player.set_tokens(self.canvas.tokens)

    def _toggle_fog(self):
        """Toggle fog visibility on the Player view.

        The button label shows the action that will be performed when clicked.
        """
        try:
            self.fog_enabled = not getattr(self, 'fog_enabled', True)
            # Button text describes the action that will happen on next click
            if self.fog_enabled:
                self.btn_fog.setText('Fog : Off')
            else:
                self.btn_fog.setText('Fog : On')
            # Immediately sync the player view
            self.sync_player_mask()
        except Exception:
            pass

    # ---------- Player physical view ----------
    def _compute_player_zoom(self) -> float | None:
        # Needs calibrated display (px_per_inch_real) and a grid cell size in map pixels.
        if not self.px_per_inch_real:
            return None
        # Keep player zoom independent from Grid visibility so toggling Grid ON/OFF
        # does not change the projected map scale on the player screen.
        gtype = self.cmb_grid.currentText()
        if gtype not in ("Square", "Hex"):
            return None
        cell = float(self.spin_grid.value())
        if cell <= 0:
            return None
        return float(self.px_per_inch_real) / cell
    def _clamp_player_center(self, c: QPointF, zoom: float) -> QPointF:
        """Clamp player view center so the viewport stays inside the map."""
        if not self.map_img or zoom <= 0:
            return c

        # Prefer actual player window size; fallback to selected target screen geometry.
        w = int(self.player.width()) if hasattr(self, "player") else 0
        h = int(self.player.height()) if hasattr(self, "player") else 0
        if w <= 10 or h <= 10:
            try:
                screens = getattr(self, "screens", None) or list(QGuiApplication.screens())
                idx = int(self.cmb_screen.currentData() or 0) if hasattr(self, "cmb_screen") else 0
                idx = max(0, min(len(screens) - 1, idx))
                geo = screens[idx].availableGeometry()
                w, h = int(geo.width()), int(geo.height())
            except Exception:
                w, h = 1920, 1080

        view_w = float(w) / float(zoom)
        view_h = float(h) / float(zoom)
        half_w = view_w / 2.0
        half_h = view_h / 2.0

        map_w = float(self.map_img.width())
        map_h = float(self.map_img.height())

        # If the viewport is bigger than the map, just center.
        if view_w >= map_w or view_h >= map_h:
            return QPointF(map_w / 2.0, map_h / 2.0)

        x = max(half_w, min(map_w - half_w, float(c.x())))
        y = max(half_h, min(map_h - half_h, float(c.y())))
        return QPointF(x, y)


    def update_player_view(self):
        if not self.player_enabled or not self.map_img:
            try:
                self.canvas.set_player_overlay(False, None, None, 0, 0)
            except Exception:
                pass
            return
        zoom = self._compute_player_zoom()
        if zoom is None:
            self.player.set_view(None, None)
            try:
                self.canvas.set_player_overlay(False, None, None, 0, 0)
            except Exception:
                pass
            return
        if self.player_view_center is None:
            self.player_view_center = QPointF(self.map_img.width() / 2.0, self.map_img.height() / 2.0)
        self.player_view_center = self._clamp_player_center(self.player_view_center, float(zoom))

        self.player.set_view(float(zoom), self.player_view_center)

        # Update DM overlay showing the exact Player view rectangle
        try:
            self.canvas.set_player_overlay(
                enabled=True,
                center_map=self.player_view_center,
                zoom=float(zoom),
                viewport_w=int(self.player.width()),
                viewport_h=int(self.player.height()),
            )
        except Exception:
            pass

    def center_player_view(self):
        if not self.map_img:
            return
        self.player_view_center = QPointF(self.map_img.width() / 2.0, self.map_img.height() / 2.0)
        self.update_player_view()

    def pan_player(self, dx_cells: int, dy_cells: int):
        if not self.map_img or self.player_view_center is None:
            self.center_player_view()
            return
        cell = float(self.spin_grid.value())
        if cell <= 0:
            return
        step = cell * float(self.player_view_cell_step)
        self.player_view_center = QPointF(
            self.player_view_center.x() + dx_cells * step,
            self.player_view_center.y() + dy_cells * step,
        )
        self.update_player_view()

    
    def calibrate_display_dialog(self):
        """
        Calibrates the real pixels-per-inch of your setup (projector/screen + distance).
        Shows a line you match to exactly 10\" (25.4 cm) using a ruler.
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QSlider, QPushButton, QFrame, QHBoxLayout
        from PyQt6.QtCore import Qt, QRect, QTimer

        target_len_in = 10.0
        target_len_cm = 25.4

        # scegli lo schermo target (quello del Player) se disponibile
        screens = getattr(self, "screens", None) or list(QGuiApplication.screens())
        idx = 0
        try:
            d = self.cmb_screen.currentData()
            if isinstance(d, int):
                idx = d
            else:
                idx = int(self.cmb_screen.currentIndex())
        except Exception:
            idx = 0
        if idx < 0 or idx >= len(screens):
            idx = 0
        target_screen = screens[idx]
        geo: QRect = target_screen.geometry()

        # dialog senza parent, così può stare sullo schermo scelto
        dlg = QDialog(None)
        dlg.setWindowTitle('Calibrate Display (10")')
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        # mettilo sullo schermo target e fullscreen
        dlg.setGeometry(geo)
        dlg.showFullScreen()

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel('Physical scale calibration')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        lbl = QLabel(
            f"Place a ruler on your table/projection.\n"
            f"Adjust the line until it measures exactly {int(target_len_in)}\" (≈ {target_len_cm:.1f} cm), then click Save."
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 14px;")
        layout.addWidget(lbl)

        class _Preview(QFrame):
            def __init__(self):
                super().__init__()
                self.on_resize = None

            def resizeEvent(self, ev):
                super().resizeEvent(ev)
                if self.on_resize:
                    self.on_resize()

        preview = _Preview()
        preview.setStyleSheet("background: black; border: 1px solid #333;")
        preview.setMinimumHeight(int(geo.height() * 0.35))
        layout.addWidget(preview, 1)

        # linea bianca al centro
        line = QFrame(preview)
        line.setStyleSheet("background: white;")
        line.setFixedHeight(6)

        # slider grosso
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimumHeight(38)
        slider.setStyleSheet("QSlider::groove:horizontal { height: 10px; } QSlider::handle:horizontal { width: 24px; }")
        # range basato sulla larghezza schermo: evita slider "micro"
        max_px = max(400, int(geo.width() * 0.9))
        slider.setRange(50, max_px)
        # valore iniziale: 10" * ppi salvati, clampato al range
        init = int((self.px_per_inch_real or 120.0) * target_len_in)
        init = max(slider.minimum(), min(slider.maximum(), init))
        slider.setValue(init)

        info = QLabel("")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("font-size: 13px; color: #ddd;")

        def upd(v: int):
            # centra la linea e aggiorna label
            w = int(v)
            line.setFixedWidth(w)
            x = int((preview.width() - w) / 2)
            y = int((preview.height() - line.height()) / 2)
            line.move(x, y)

            ppi = float(w) / target_len_in
            px_per_cm = ppi / 2.54
            info.setText(f"Line: {int(target_len_in)}\" (≈ {target_len_cm:.1f} cm)  |  ppi: {ppi:.2f}  |  px/cm: {px_per_cm:.2f}")

        slider.valueChanged.connect(upd)
        preview.on_resize = lambda: upd(slider.value())
        upd(slider.value())
        QTimer.singleShot(0, lambda: upd(slider.value()))

        # barra comandi
        bar = QHBoxLayout()
        bar.setSpacing(12)
        bar.addWidget(slider, 1)

        btn_save = QPushButton("Save")
        btn_save.setMinimumHeight(40)
        btn_save.setStyleSheet("font-size: 14px; font-weight: 600;")
        btn_cancel = QPushButton("Cancel (ESC)")
        btn_cancel.setMinimumHeight(40)

        bar.addWidget(btn_cancel)
        bar.addWidget(btn_save)
        layout.addLayout(bar)
        layout.addWidget(info)

        def save():
            w = float(slider.value())
            self.px_per_inch_real = w / target_len_in
            self.settings.setValue("px_per_inch_real", float(self.px_per_inch_real))
            if hasattr(self, "lbl_ppi"):
                self.lbl_ppi.setText(f"ppi: {self.px_per_inch_real:.2f}")
            dlg.accept()
            self.update_player_view()

        btn_save.clicked.connect(save)
        btn_cancel.clicked.connect(dlg.reject)

        # ESC chiude
        dlg.setModal(True)
        dlg.exec()
    def _maybe_prompt_save_before_discard(self) -> bool:
        """If a map/session is already loaded, ask to save before discarding it (e.g. Open Map).
        Returns True to continue, False to abort.
        """
        if self.map_img is None or self.loaded is None:
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Save current session?")
        box.setText("A map/session is already loaded.")
        box.setInformativeText("Do you want to save the current session before continuing?")

        btn_save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)

        box.exec()
        clicked = box.clickedButton()

        if clicked == btn_cancel:
            return False
        if clicked == btn_save:
            # Safest: if save fails or user cancels Save As, abort the action.
            if not self.save_session_quick():
                return False
        return True

    def _maybe_prompt_save_before_exit(self) -> bool:
        """Ask to save before exiting if a map/session is loaded.
        Safest behavior: if saving fails or is cancelled, abort exit.
        Returns True to proceed with closing, False to abort.
        """
        if self.map_img is None or self.loaded is None:
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Exit Veilforge")
        box.setText("A map/session is currently loaded.")
        box.setInformativeText("Do you want to save the current session before exiting?")

        btn_save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)

        box.exec()
        clicked = box.clickedButton()

        if clicked == btn_cancel:
            return False
        if clicked == btn_save:
            if not self.save_session_quick():
                return False
        return True



# ---------- Map ----------

    def open_map(self):
        # If something is already loaded, offer to save before discarding it
        if not self._maybe_prompt_save_before_discard():
            return
        start_dir = str(Path(r'D:/_JDR_Ressources/Veilforge 2.7.0').resolve())
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Map", start_dir, "Maps (*.png *.jpg *.jpeg *.tif *.tiff *.pdf *.mp4 *.webm *.m4a *.mkv);;All files (*.*)"
        )
        if not path:
            return
        if not Path(path).is_absolute():
            path = str(self._resolve_portable_path(path))
        path = str(Path(path).resolve())
        if not Path(path).exists():
            QMessageBox.critical(self, "Load error", f"Couldn't load map:\nFile not found:\n{path}")
            return
        # Convenience: if user picks a session file from Open Map, load it as session.
        if Path(path).suffix.lower() == ".json":
            self._load_session_path(path)
            return
        # Stop any active video playback before loading this new map so the
        # Player window display parameters are fully reset.
        try:
            try:
                self.player.stop_video()
            except Exception:
                pass
        except Exception:
            pass
        try:
            self.loaded = load_map(path, pdf_page=0, pdf_dpi=150)
        except Exception as e:
            QMessageBox.critical(self, "Load error", f"Couldn't load map:\n{e}")
            return

        self.map_rotation_deg = 0
        self.map_img = self.loaded.qimage
        self.canvas.set_images(self.map_img, None, drawings=[])
        self.canvas.reset_fog()

        self.current_session_path = None
        self._update_window_title()
        self.statusBar().showMessage("Map loaded", 2000)

        if self.loaded.is_video:
            self.map_img = None
            self.canvas.set_images(None, None, drawings=[])
            self._set_video_mode(True, self.loaded.source_path)
        else:
            self.map_img = self.loaded.qimage
            self._set_video_mode(False, None)
            self.canvas.set_images(self.map_img, None, drawings=[])
            self.canvas.reset_fog()
            self.on_grid_changed()

        self._update_cta_visibility()

        if self.player_enabled and not self.loaded.is_video:
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.player.set_drawings(self.canvas.drawings)
            self.update_player_view()

    def rotate_map(self, deg: int):
        if not self.map_img or not self.loaded:
            return
        deg = int(deg)
        if deg % 360 == 0:
            return
        self.map_rotation_deg = (self.map_rotation_deg + deg) % 360

        t = QTransform()
        t.rotate(deg)

        # rotate map
        self.map_img = self.map_img.transformed(t)

        # rotate mask (if any) to match
        mask = self.canvas.mask_img.transformed(t) if self.canvas.mask_img else None

        # rotate drawings (points) for 90/180/270
        def rot_pt(x: int, y: int, w: int, h: int) -> tuple[int, int]:
            d = deg % 360
            if d == 90:
                return (h - 1 - y, x)
            if d == 270:
                return (y, w - 1 - x)
            if d == 180:
                return (w - 1 - x, h - 1 - y)
            return (x, y)

        old_w = self.canvas._map.width() if getattr(self.canvas, "_map", None) else self.map_img.width()
        old_h = self.canvas._map.height() if getattr(self.canvas, "_map", None) else self.map_img.height()

        new_drawings = []
        for s in self.canvas.drawings:
            pts = []
            for x, y in s.points:
                nx, ny = rot_pt(int(x), int(y), old_w, old_h)
                pts.append((float(nx), float(ny)))
            ns = Stroke(id=s.id, points=pts, color=s.color, width=s.width, dash=s.dash)
            new_drawings.append(ns)

        self.canvas.set_images(self.map_img, mask, drawings=new_drawings)

        if self.player_enabled:
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.player.set_drawings(self.canvas.drawings)
            self.update_player_view()

        self.statusBar().showMessage(f"🔄 Rotated {deg:+d}°", 1800)

    # ---------- Save/load ----------
    def _confirm_overwrite_if_needed(self) -> bool:
        if not self.ask_overwrite:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Overwrite")
        box.setText("This will overwrite the existing save. Continue?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        chk = QCheckBox("Don't warn me again")
        box.setCheckBox(chk)
        res = box.exec()
        if chk.isChecked():
            self.ask_overwrite = False
            self.settings.setValue("ask_overwrite", False)
        return res == QMessageBox.StandardButton.Yes

    def _do_save_to(self, session_path: Path) -> bool:
        if not self.loaded or not self.map_img or self.canvas.mask_img is None:
            QMessageBox.information(self, "Nothing to save", "Load a map first.")
            return False

        session_path = session_path.with_suffix(".json")
        mask_path = session_path.with_suffix(".mask.png")
        self.canvas.mask_img.save(str(mask_path))

        grid = {
            "enabled": self.chk_grid.isChecked(),
            "type": self.cmb_grid.currentText(),
            "cell": self.spin_grid.value(),
            "alpha": self.grid_alpha.value(),
            "show_on_player": self.chk_grid_player.isChecked(),
        }
        data = SessionData(
            map_path=self.loaded.source_path,
            is_pdf=self.loaded.is_pdf,
            pdf_page=self.loaded.pdf_page,
            pdf_dpi=self.loaded.dpi,
            map_rotation_deg=int(self.map_rotation_deg),
            mask_path=str(mask_path),
            drawings=[s.to_dict() for s in self.canvas.drawings],
            tokens=self._serialize_tokens(),
            grid=grid,
        )
        try:
            save_session(str(session_path), data)
        except Exception as e:
            QMessageBox.critical(self, "Save error", f"Couldn't save session:\n{e}")
            return False
        self.current_session_path = session_path
        self._add_recent_session(self.current_session_path)
        self._update_window_title()
        self.statusBar().showMessage(f"✅ Session saved: {session_path.name}", 3200)

    
        return True

    def save_session_quick(self) -> bool:
        if self.current_session_path is None:
            return self.save_session_as_dialog()
        if not self._confirm_overwrite_if_needed():
            return False
        return self._do_save_to(self.current_session_path)

    def save_session_as_dialog(self) -> bool:
        if not self.loaded or not self.map_img:
            QMessageBox.information(self, "Nothing to save", "Load a map first.")
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save Session As", str(self._default_sessions_dir()), "Veilforge session (*.json)")
        if not path:
            return False
        sp = Path(path)
        if sp.exists() and self.ask_overwrite:
            if not self._confirm_overwrite_if_needed():
                return False
        return self._do_save_to(sp)

    def load_session_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", str(self._default_sessions_dir()), "Veilforge session (*.json)")
        if not path:
            return
        self._load_session_path(path)

    # ---------- Player screen ----------
    def toggle_player_screen(self, enabled: bool):
        self.player_enabled = enabled
        self.btn_player.setText(f"Player Screen: {'ON' if enabled else 'OFF'}")

        if not enabled:
            self.player.showNormal()
            self.player.hide()
            try:
                self.canvas.set_player_overlay(False, None, None, 0, 0)
            except Exception:
                pass
            try:
                self.player.stop_video()
            except Exception:
                pass
            try:
                self.player.use_external_video_stream(False)
            except Exception:
                pass
            return

        idx = self.cmb_screen.currentData()
        idx = int(idx) if idx is not None else 0
        if idx < 0 or idx >= len(self.screens):
            idx = 0
        screen = self.screens[idx] if self.screens else self.screen()
        geo = screen.geometry()

        self.player.show()
        if self.player_mode == "Fullscreen":
            self.player.setGeometry(geo)
            self.player.showFullScreen()
        else:
            w = int(geo.width() * 0.8)
            h = int(geo.height() * 0.8)
            x = geo.left() + (geo.width() - w) // 2
            y = geo.top() + (geo.height() - h) // 2
            self.player.setGeometry(x, y, w, h)
            self.player.showNormal()

        # If the currently loaded map is a video, start playback on the player
        if getattr(self, 'loaded', None) and getattr(self.loaded, 'is_video', False):
            try:
                self.player.use_external_video_stream(True)
            except Exception:
                pass
            # sync fog state (player overlay will use mask or None)
            mask = self.canvas.mask_img if getattr(self, 'fog_enabled', True) else None
            self.player.set_images(None, mask)
            try:
                self.player.set_external_video_frame(self.current_video_frame_img)
            except Exception:
                pass
            self.player.set_tokens([])
        else:
            self.player.use_external_video_stream(False)
            self.player.stop_video()
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.player.set_drawings(self.canvas.drawings)
            self.player.set_tokens(self.canvas.tokens)
        self.on_grid_changed()
        self.update_player_view()

    def closeEvent(self, e):
        # Ask to save before exiting (safest behavior)
        try:
            if not self._maybe_prompt_save_before_exit():
                e.ignore()
                return
        except Exception:
            # If something weird happens, do not risk data loss
            e.ignore()
            return

        try:
            self.player.close()
        except Exception:
            pass
        super().closeEvent(e)
