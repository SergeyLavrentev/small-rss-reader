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
from rss_reader.utils.settings import qsettings
from rss_reader.utils.paths import resource_path
from rss_reader.utils.proxy import apply_proxy_env_from_settings


def get_user_data_path(filename: str) -> str:
    return _app_get_user_data_path(filename)


def main() -> int:
    app = QApplication(sys.argv)
    try:
        apply_proxy_env_from_settings()
    except Exception:
        pass
    debug = ('--debug' in sys.argv)
    # Show splash screen only in non-debug runs to avoid perceived hangs during heavy init
    try:
        if not debug:
            splash_path = resource_path('icons/splash.png')
            pix = QPixmap(splash_path)
            splash = QSplashScreen(pix) if not pix.isNull() else QSplashScreen()
            splash.show()
            app.processEvents()
        else:
            splash = None  # type: ignore
    except Exception:
        splash = None  # type: ignore

    w = RSSReader()
    # First run: maximize window even if geometry exists from older versions; then mark as done
    try:
        s = qsettings()
        first_done = s.value('first_run_done', False, type=bool)
        if not first_done:
            w.showMaximized()
            s.setValue('first_run_done', True)
        else:
            w.show()
    except Exception:
        w.show()
    # Ensure toolbar visible in entrypoint
    try:
        if hasattr(w, 'toolbar') and w.toolbar:
            w.toolbar.setVisible(True)
            w.toolbar.setEnabled(True)
    except Exception:
        pass
    try:
        if splash:
            splash.finish(w)
    except Exception:
        pass
    rc = app.exec_()

    # Ensure widgets are torn down before QApplication destruction.
    # This helps avoid macOS shutdown hangs/crashes (notably with QtWebEngine).
    try:
        try:
            w.close()
        except Exception:
            pass
        try:
            if hasattr(w, 'deleteLater'):
                w.deleteLater()
        except Exception:
            pass
        try:
            app.processEvents()
            app.processEvents()
        except Exception:
            pass
    except Exception:
        pass
    try:
        w = None  # type: ignore
    except Exception:
        pass

    return int(rc)


if __name__ == "__main__":
    sys.exit(main())

