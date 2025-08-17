from __future__ import annotations

from typing import Any

from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon

from rss_reader.utils.paths import resource_path


def init_tray(app: Any) -> None:
    try:
        icon_path = resource_path("icons/rss_tray_icon.png")
        icon = QIcon(icon_path)
        app.tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        menu.addAction(app.actRefreshAll)
        menu.addAction(app.actOnlyUnread)
        menu.addSeparator()
        quit_action = QAction("Quit", app)
        quit_action.triggered.connect(app.close)
        menu.addAction(quit_action)
        app.tray.setContextMenu(menu)
        app.tray.activated.connect(lambda reason: app.showNormal() if reason == QSystemTrayIcon.Trigger else None)
        app.tray.show()
        app._update_tray()
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().aboutToQuit.connect(app.tray.hide)  # type: ignore[arg-type]
        except Exception:
            pass
    except Exception:
        app.tray = None  # type: ignore
