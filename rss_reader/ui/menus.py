from __future__ import annotations

from typing import Any


def create_menu(app: Any) -> None:
    """Build the menubar using actions already attached to app."""
    mb = app.menuBar()
    file_menu = mb.addMenu("File")
    file_menu.addAction(app.actAddFeed)
    file_menu.addAction(app.actRemoveFeed)
    file_menu.addSeparator()
    file_menu.addAction(app.actBackup)
    file_menu.addAction(app.actRestore)
    file_menu.addSeparator()
    file_menu.addAction(app.actImportJSON)
    file_menu.addAction(app.actExportJSON)
    file_menu.addSeparator()
    file_menu.addAction(app.actImportOPML)
    file_menu.addAction(app.actExportOPML)
    file_menu.addSeparator()
    file_menu.addAction(app.actQuit)

    act_menu = mb.addMenu("Actions")
    act_menu.addAction(app.actRefreshAll)
    act_menu.addAction(app.actRefreshFeed)
    act_menu.addAction(app.actMarkAllRead)
    act_menu.addAction(app.actMarkAllUnread)
    act_menu.addAction(app.actOnlyUnread)

    view_menu = mb.addMenu("View")
    view_menu.addAction(app.actToggleToolbar)
    view_menu.addAction(app.actToggleMenuBar)
    view_menu.addSeparator()
    view_menu.addAction(app.actFontIncrease)
    view_menu.addAction(app.actFontDecrease)

    settings_menu = mb.addMenu("Settings")
    settings_menu.addAction(app.actSettings)

    help_menu = mb.addMenu("Help")
    help_menu.addAction(app.actAbout)
    help_menu.addAction(app.actAboutQt)
