#!/usr/bin/env python3
"""Compatibility shim for Small RSS Reader.

Keeps `from small_rss_reader import RSSReader` working while the
implementation lives in `rss_reader.app`. Also exposes
`get_user_data_path` for tests to monkeypatch.
"""

import sys
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QPixmap

from rss_reader.app import (
    RSSReader as RSSReader,
    get_user_data_path as _app_get_user_data_path,
)
from rss_reader.utils.paths import resource_path


def get_user_data_path(filename: str) -> str:
    return _app_get_user_data_path(filename)


def main() -> int:
    app = QApplication(sys.argv)
    # Show splash screen with app logo while initializing the main window
    try:
        splash_path = resource_path('icons/splash.png')
        pix = QPixmap(splash_path)
        splash = QSplashScreen(pix) if not pix.isNull() else QSplashScreen()
        splash.show()
        app.processEvents()
    except Exception:
        splash = None  # type: ignore

    w = RSSReader()
    w.show()
    try:
        if splash:
            splash.finish(w)
    except Exception:
        pass
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

