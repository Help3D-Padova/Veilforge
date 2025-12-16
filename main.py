from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from pathlib import Path

from veilforge.main_window import MainWindow


def main():
    app = QApplication([])
    # App-wide icon (DM + Player)
    for cand in [
        Path("assets/veilforge.ico"),
        Path("veilforge/assets/veilforge.ico"),
        Path("assets/veilforge.png"),
        Path("veilforge/assets/veilforge.png"),
        Path("veilforge/icon.ico"),
        Path("icon.ico"),
    ]:
        if cand.exists():
            app.setWindowIcon(QIcon(str(cand)))
            break

    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
