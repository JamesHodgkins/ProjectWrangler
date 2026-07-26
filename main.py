import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from coconut.ui.main_window import MainWindow
from coconut.ui.theme import apply_theme

_APP_ICON = Path(__file__).resolve().parent / "coconut" / "assets" / "icons" / "app_logo.ico"

if sys.platform == "win32":
    import ctypes

    # Without a distinct AppUserModelID, Windows groups this process under
    # python.exe's own taskbar identity/icon instead of showing ours.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JamesHodgkins.Coconut")


def main():
    app = QApplication(sys.argv)
    app_icon = QIcon(str(_APP_ICON))
    app.setWindowIcon(app_icon)
    apply_theme(app)
    window = MainWindow()
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
