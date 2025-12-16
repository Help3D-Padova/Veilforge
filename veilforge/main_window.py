from __future__ import annotations

from pathlib import Path
import json

from PyQt6.QtCore import Qt, QSettings, QTimer, QPointF, QEvent, QUrl
from PyQt6.QtGui import QImage, QGuiApplication, QColor, QIcon, QTransform, QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QSlider, QMessageBox, QComboBox, QCheckBox, QSpinBox, QColorDialog,
    QFrame, QDialog, QTextEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget
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
)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Veilforge {__version__} – Fog of War")
        try:
            self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "veilforge.png")))
        except Exception:
            pass

        self.settings = QSettings("HELP3D", "Veilforge")
        self.ask_overwrite = self.settings.value("ask_overwrite", True, type=bool)

        # Recent sessions (most recent first)
        self.RECENT_SESSIONS_KEY = "recent_sessions"
        self.RECENT_MAX = 8
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

        # Windows
        self.canvas = DMCanvas()
        self.player = PlayerWindow()
        self.player_enabled = False
        self.player_mode = "Fullscreen"
        self.screens = []

        self.statusBar().showMessage("Ready")

        # ---------- UI ----------
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        row1 = QHBoxLayout()
        v.addLayout(row1)
        self.btn_open = QPushButton("Open Map")
        self.btn_rot_l = QPushButton("⟲ Rotate")
        self.btn_rot_r = QPushButton("⟳ Rotate")
        self.btn_zoom_reset = QPushButton("Reset zoom")
        self.btn_zoom_reset.installEventFilter(self)
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save As")
        self.btn_load = QPushButton("Load Session")
        self.btn_recent = QPushButton("Recent…")
        self.btn_help = QPushButton("Help")
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

        row1.addWidget(QLabel("Target screen"))
        self.cmb_screen = QComboBox()
        row1.addWidget(self.cmb_screen)

        row1.addWidget(QLabel("Player mode"))
        self.cmb_player_mode = QComboBox()
        self.cmb_player_mode.addItems(["Fullscreen", "Window"])
        row1.addWidget(self.cmb_player_mode)

        # Player toggle + donate (DM side)
        self.btn_player = QPushButton("Player Screen: OFF")
        self.btn_player.setCheckable(True)

        self.btn_donate = QPushButton("Donate ❤")
        self.btn_donate.setToolTip("Support Veilforge development")
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)

        # Keep top bar height consistent: same min height as the other buttons (no vertical stacking here)
        try:
            _h = self.btn_help.sizeHint().height()
        except Exception:
            _h = 26
        self.btn_player.setMinimumHeight(_h)
        self.btn_donate.setMinimumHeight(_h)

        # Simple, visible, cross-platform styling
        self.btn_donate.setStyleSheet(
            "QPushButton{background:#ff4d8d;color:white;border:none;border-radius:8px;padding:4px 10px;font-weight:700;}"
            "QPushButton:hover{background:#ff2f79;}"
            "QPushButton:pressed{background:#e6286b;}"
        )

        # Put Player + Donate on the same row so the top bar doesn't grow taller
        _right_box = QWidget()
        _right_lay = QHBoxLayout(_right_box)
        _right_lay.setSpacing(6)
        _right_lay.setContentsMargins(0, 0, 0, 0)
        _right_lay.addWidget(self.btn_player)
        _right_lay.addWidget(self.btn_donate)
        row1.addWidget(_right_box)

        row2 = QHBoxLayout()
        v.addLayout(row2)
        self.btn_undo = QPushButton("Undo Fog")
        self.btn_redo = QPushButton("Redo Fog")
        self.btn_reset = QPushButton("Reset Fog")
        row2.addWidget(self.btn_undo)
        row2.addWidget(self.btn_redo)
        row2.addWidget(self.btn_reset)
        row2.addStretch(1)

        row3 = QHBoxLayout()
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
        v.addLayout(row4)

        # Grid controls
        self.chk_grid = QCheckBox("Grid")
        self.cmb_grid = QComboBox()
        self.cmb_grid.addItems(["None", "Square", "Hex"])
        self.spin_grid = QSpinBox()
        self.spin_grid.setRange(5, 500)
        self.spin_grid.setValue(70)
        self.grid_alpha = QSlider(Qt.Orientation.Horizontal)
        self.grid_alpha.setRange(0, 255)
        self.grid_alpha.setValue(130)
        self.chk_grid_player = QCheckBox("Show on Player")
        self.chk_grid_player.setChecked(True)
        self.btn_grid_cal = QPushButton("Calibrate")

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
        row4.addWidget(self.btn_del_anno)
        row4.addStretch(1)

        # Player physical calibration + pan
        row5 = QHBoxLayout()
        v.addLayout(row5)
        self.btn_calib_display = QPushButton('Calibrate 10"')
        self.lbl_ppi = QLabel(f"ppi: {self.px_per_inch_real:.2f}")
        self.btn_pl_left = QPushButton("⟵")
        self.btn_pl_right = QPushButton("⟶")
        self.btn_pl_up = QPushButton("⟰")
        self.btn_pl_down = QPushButton("⟱")
        self.btn_pl_center = QPushButton("Center Player")
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
        self.canvas_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(self.canvas_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.canvas)
        v.addWidget(self.canvas_frame, 1)

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

        self.resize(1340, 920)
        self._update_cta_visibility()
        self.btn_color.setStyleSheet("background: rgba(255,0,0,180);")
        self._update_window_title()
        QTimer.singleShot(0, self._sync_overlay_geometry)
    
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_overlay_geometry()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._sync_overlay_geometry)
        if not getattr(self, "_restore_prompt_shown", False):
            self._restore_prompt_shown = True
            QTimer.singleShot(50, self._prompt_autoload_recent)

    def _update_cta_visibility(self):
        self.cta_overlay.setVisible(self.map_img is None)

    def _update_window_title(self):
        base = "Veilforge – Fog of War"
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
            p = str(Path(session_path).resolve())
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
                if Path(s).exists():
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
        box.setInformativeText(f"Last session:\n{Path(last).name}")

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
        try:
            data = load_session(path)
            self.loaded = load_map(data.map_path, pdf_page=data.pdf_page, pdf_dpi=data.pdf_dpi)
        except Exception as e:
            QMessageBox.critical(self, "Load error", f"Couldn't load session:\n{e}")
            return

        self.map_rotation_deg = int(getattr(data, "map_rotation_deg", 0) or 0) % 360
        self.map_img = self.loaded.qimage
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

        g = data.grid or {}
        if g:
            self.chk_grid.setChecked(bool(g.get("enabled", False)))
            self.cmb_grid.setCurrentText(str(g.get("type", "None")))
            self.spin_grid.setValue(int(g.get("cell", 70)))
            self.grid_alpha.setValue(int(g.get("alpha", 130)))
            self.chk_grid_player.setChecked(bool(g.get("show_on_player", True)))
            self.on_grid_changed()

        self.current_session_path = Path(path)
        self._add_recent_session(self.current_session_path)
        self._update_window_title()
        self.statusBar().showMessage(f"Session loaded: {self.current_session_path.name}", 2600)
        self._update_cta_visibility()

        if self.player_enabled:
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.player.set_drawings(self.canvas.drawings)
            self.update_player_view()

    def open_recent_sessions(self) -> None:
        items = self._get_recent_sessions()
        existing, missing = [], []
        for s in items:
            try:
                (existing if Path(s).exists() else missing).append(s)
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
            if not Path(str(pth)).exists():
                QMessageBox.warning(dlg, "Missing", "That session file no longer exists.")
                return
            dlg.accept()
            self._load_session_path(str(pth))

        def do_browse():
            dlg.accept()
            self.load_session_dialog()

        def do_clean():
            cleaned = [p for p in self._get_recent_sessions() if p and Path(p).exists()]
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
            readme_path = Path(__file__).resolve().parent.parent / "README.md"
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

    def on_grid_changed(self):
        show = self.chk_grid.isChecked()
        gtype = self.cmb_grid.currentText()
        cell = self.spin_grid.value()
        alpha = self.grid_alpha.value()
        self.canvas.set_grid(show, gtype, cell, alpha)
        self.player.set_grid(self.chk_grid_player.isChecked() and show, gtype, cell, alpha)
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
        if self.player_enabled:
            self.player.set_images(self.map_img, self.canvas.mask_img)
            self.update_player_view()

    def sync_player_drawings(self):
        if self.player_enabled:
            self.player.set_drawings(self.canvas.drawings)

    # ---------- Player physical view ----------
    def _compute_player_zoom(self) -> float | None:
        # Needs calibrated display (px_per_inch_real) and a grid cell size in map pixels.
        if not self.px_per_inch_real:
            return None
        if not self.chk_grid.isChecked():
            return None
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
        """
        If a map/session is already loaded, ask the user whether to save before opening a new map.
        Returns True to continue, False to abort the action.
        """
        # Nothing loaded → nothing to discard
        if self.map_img is None or self.loaded is None:
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Save current session?")
        box.setText("A map is already loaded.")
        box.setInformativeText("Do you want to save the current session before opening a new map?")

        btn_save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        btn_no = box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)

        box.exec()
        clicked = box.clickedButton()

        if clicked == btn_cancel:
            return False
        if clicked == btn_save:
            # Save (quick if we have a path, otherwise Save As)
            try:
                self.save_session_quick()
            except Exception:
                # best-effort; don't brick Open Map
                pass
        return True


# ---------- Map ----------

    def open_map(self):
        # If something is already loaded, offer to save before discarding it
        if not self._maybe_prompt_save_before_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Map", "", "Maps (*.png *.jpg *.jpeg *.tif *.tiff *.pdf);;All files (*.*)"
        )
        if not path:
            return
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
        self._update_cta_visibility()
        self.on_grid_changed()

        if self.player_enabled:
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

    def _do_save_to(self, session_path: Path):
        if not self.loaded or not self.map_img or self.canvas.mask_img is None:
            QMessageBox.information(self, "Nothing to save", "Load a map first.")
            return

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
            grid=grid,
        )
        try:
            save_session(str(session_path), data)
        except Exception as e:
            QMessageBox.critical(self, "Save error", f"Couldn't save session:\n{e}")
            return
        self.current_session_path = session_path
        self._add_recent_session(self.current_session_path)
        self._update_window_title()
        self.statusBar().showMessage(f"✅ Session saved: {session_path.name}", 3200)

    def save_session_quick(self):
        if self.current_session_path is None:
            self.save_session_as_dialog()
            return
        if not self._confirm_overwrite_if_needed():
            return
        self._do_save_to(self.current_session_path)

    def save_session_as_dialog(self):
        if not self.loaded or not self.map_img:
            QMessageBox.information(self, "Nothing to save", "Load a map first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Session As", "", "Veilforge session (*.json)")
        if not path:
            return
        sp = Path(path)
        if sp.exists() and self.ask_overwrite:
            if not self._confirm_overwrite_if_needed():
                return
        self._do_save_to(sp)

    def load_session_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", "", "Veilforge session (*.json)")
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

        self.player.set_images(self.map_img, self.canvas.mask_img)
        self.player.set_drawings(self.canvas.drawings)
        self.on_grid_changed()
        self.update_player_view()

    def closeEvent(self, e):
        try:
            self.player.close()
        except Exception:
            pass
        super().closeEvent(e)
