from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from pathlib import Path
import sys

from veilforge.main_window import MainWindow


def app_dir() -> Path:
    """Base directory for portable builds.
    - Frozen one-folder: folder containing the .exe
    - Frozen one-file: temporary _MEIPASS extraction dir (assets live there)
    - Source run: folder containing this file (repo root)
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main():
    app = QApplication([])

    base = app_dir()

    # App-wide icon (DM + Player)
    for cand in [
        base / "assets/veilforge.ico",
        base / "assets/veilforge.png",
        base / "veilforge/assets/veilforge.ico",
        base / "veilforge/assets/veilforge.png",
        base / "veilforge/icon.ico",
        base / "icon.ico",
        # fallback for "run from repo root"
        Path("assets/veilforge.ico"),
        Path("assets/veilforge.png"),
    ]:
        if cand.exists():
            app.setWindowIcon(QIcon(str(cand)))
            break

    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
