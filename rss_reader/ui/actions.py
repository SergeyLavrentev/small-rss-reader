from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMessageBox, QStyle


def create_actions(app: Any) -> None:
    """Create and attach QAction instances on the app.

    Mirrors the previous RSSReader._create_actions implementation but
    keeps logic in a separate module to slim down app.py.
    """
    # Core actions
    app.actAddFeed = QAction("Add Feed", app)
    app.actAddFeed.triggered.connect(app.add_feed)
    app.actRemoveFeed = QAction("Remove Feed", app)
    app.actRemoveFeed.triggered.connect(app.remove_selected_feed)
    app.actRefreshAll = QAction("Refresh All", app)
    app.actRefreshAll.triggered.connect(app.refresh_all_feeds)
    app.actRefreshFeed = QAction("Refresh Feed", app)
    app.actRefreshFeed.triggered.connect(app.refresh_selected_feed)
    app.actMarkAllRead = QAction("Mark All as Read", app)
    app.actMarkAllRead.triggered.connect(app.mark_all_as_read)
    app.actMarkAllUnread = QAction("Mark All as Unread", app)
    app.actMarkAllUnread.triggered.connect(app.mark_all_as_unread)
    app.actSettings = QAction("Settings", app)
    app.actSettings.triggered.connect(app.open_settings)
    app.actBackup = QAction("Backup to iCloud", app)
    app.actBackup.triggered.connect(app.backup_to_icloud)
    app.actRestore = QAction("Restore from iCloud", app)
    app.actRestore.triggered.connect(app.restore_from_icloud)
    app.actQuit = QAction("Quit", app)
    app.actQuit.triggered.connect(app.close)
    app.actOnlyUnread = QAction("Show Only Unread", app)
    app.actOnlyUnread.setCheckable(True)
    app.actOnlyUnread.toggled.connect(app._toggle_unread_filter)
    app.actImportOPML = QAction("Import OPML…", app)
    app.actImportOPML.triggered.connect(app.import_opml)
    app.actExportOPML = QAction("Export OPML…", app)
    app.actExportOPML.triggered.connect(app.export_opml)
    app.actImportJSON = QAction("Import JSON…", app)
    app.actImportJSON.triggered.connect(app.import_json_feeds)
    app.actExportJSON = QAction("Export JSON…", app)
    app.actExportJSON.triggered.connect(app.export_json_feeds)

    # View toggles
    app.actToggleToolbar = QAction("Show Toolbar", app)
    app.actToggleToolbar.setCheckable(True)
    app.actToggleToolbar.setChecked(True)
    app.actToggleToolbar.toggled.connect(app._toggle_toolbar)
    app.actToggleMenuBar = QAction("Show Menu Bar", app)
    app.actToggleMenuBar.setCheckable(True)
    app.actToggleMenuBar.setChecked(True)
    app.actToggleMenuBar.toggled.connect(app._toggle_menubar)

    # Tooltips for toolbar hover text (best-effort)
    for act in [
        app.actAddFeed, app.actRemoveFeed, app.actRefreshAll, app.actRefreshFeed,
        app.actMarkAllRead, app.actMarkAllUnread, app.actSettings, app.actBackup,
        app.actRestore, app.actQuit, app.actOnlyUnread, app.actImportOPML,
        app.actExportOPML, app.actImportJSON, app.actExportJSON
    ]:
        try:
            act.setToolTip(act.text())
        except Exception:
            pass

    # Icons
    try:
        app.actAddFeed.setIcon(app._theme_icon(["list-add", "contact-new", "add"], QStyle.SP_FileDialogNewFolder))
        app.actRemoveFeed.setIcon(app._theme_icon(["list-remove", "edit-delete", "user-trash"], QStyle.SP_TrashIcon))
        app.actRefreshAll.setIcon(app._theme_icon(["view-refresh", "reload"], QStyle.SP_BrowserReload))
        app.actRefreshFeed.setIcon(app._theme_icon(["media-playback-start", "system-run"], QStyle.SP_MediaPlay))
        app.actMarkAllRead.setIcon(app._theme_icon(["mail-mark-read", "emblem-ok"], QStyle.SP_DialogApplyButton))
        app.actMarkAllUnread.setIcon(app._theme_icon(["mail-mark-unread", "edit-undo"], QStyle.SP_DialogResetButton))
        app.actSettings.setIcon(app._theme_icon(["preferences-system", "settings"], QStyle.SP_FileDialogDetailedView))
        app.actBackup.setIcon(app._theme_icon(["cloud-upload", "go-up"], QStyle.SP_ArrowUp))
        app.actRestore.setIcon(app._theme_icon(["cloud-download", "go-down"], QStyle.SP_ArrowDown))
        app.actQuit.setIcon(app._theme_icon(["application-exit", "window-close"], QStyle.SP_TitleBarCloseButton))
        try:
            app.actOnlyUnread.setIcon(QIcon(app._unread_dot_pixmap(10)))
        except Exception:
            pass
        app.actImportOPML.setIcon(app._theme_icon(["document-import", "document-open"], QStyle.SP_DialogOpenButton))
        app.actExportOPML.setIcon(app._theme_icon(["document-export", "document-save"], QStyle.SP_DialogSaveButton))
        app.actImportJSON.setIcon(app._theme_icon(["document-import", "document-open"], QStyle.SP_DialogOpenButton))
        app.actExportJSON.setIcon(app._theme_icon(["document-export", "document-save"], QStyle.SP_DialogSaveButton))
    except Exception:
        pass

    # Shortcuts
    try:
        from PyQt5.QtGui import QKeySequence
        app.actRefreshAll.setShortcut(QKeySequence.Refresh)
        app.actQuit.setShortcut(QKeySequence.Quit)
    except Exception:
        pass
    try:
        app.actAddFeed.setShortcut('Ctrl+N')
        app.actRemoveFeed.setShortcut('Delete')
        app.actOnlyUnread.setShortcut('Ctrl+U')
        app.actMarkAllRead.setShortcut('Ctrl+Shift+R')
        app.actMarkAllUnread.setShortcut('Ctrl+Shift+U')
        # Focus search: Cmd+F on macOS, Ctrl+F elsewhere
        app.actFocusSearch = QAction("Focus Search", app)
        app.actFocusSearch.triggered.connect(lambda: getattr(app, 'searchEdit', None) and app.searchEdit.setFocus())
        app.addAction(app.actFocusSearch)
        try:
            # Prefer QKeySequence.Find if present
            from PyQt5.QtGui import QKeySequence as _QS
            app.actFocusSearch.setShortcut(_QS.Find)
        except Exception:
            app.actFocusSearch.setShortcut('Ctrl+F')
    except Exception:
        pass

    # macOS Quit role
    try:
        from PyQt5.QtWidgets import QAction as _QA
        app.actQuit.setMenuRole(_QA.QuitRole)
    except Exception:
        pass

    # Help/About
    app.actAbout = QAction("About", app)
    app.actAbout.triggered.connect(app.show_about)
    app.actAboutQt = QAction("About Qt", app)
    app.actAboutQt.triggered.connect(lambda: QMessageBox.aboutQt(app))
