from __future__ import annotations

from typing import Any, Optional, Type

from PyQt5.QtCore import QSettings


ORG = 'rocker'
APP = 'SmallRSSReader'


def get_setting(key: str, default: Any = None, typ: Optional[Type] = str) -> Any:
    try:
        settings = QSettings(ORG, APP)
        if typ is None:
            return settings.value(key, default)
        return settings.value(key, default, type=typ)  # type: ignore[arg-type]
    except Exception:
        return default


def set_setting(key: str, value: Any) -> None:
    try:
        settings = QSettings(ORG, APP)
        settings.setValue(key, value)
    except Exception:
        pass


def load_window_state(app) -> None:
    """Restore window geometry/state and UI visibility.

    Safely applies saved window geometry/state, toolbar and menubar visibility.
    Expects attributes: toolbar, actToggleToolbar, actToggleMenuBar (optional).
    """
    try:
        settings = QSettings(ORG, APP)
        geom = settings.value('window_geometry')
        state = settings.value('window_state')
        tb_vis = settings.value('toolbar_visible', True, type=bool)
        mb_vis = settings.value('menubar_visible', True, type=bool)
        if geom:
            app.restoreGeometry(geom)
        if state:
            app.restoreState(state)
        try:
            if hasattr(app, 'toolbar') and app.toolbar:
                app.toolbar.setVisible(bool(tb_vis))
            if hasattr(app, 'actToggleToolbar') and app.actToggleToolbar:
                app.actToggleToolbar.setChecked(bool(tb_vis))
        except Exception:
            pass
        try:
            app.menuBar().setVisible(bool(mb_vis))
            if hasattr(app, 'actToggleMenuBar') and app.actToggleMenuBar:
                app.actToggleMenuBar.setChecked(bool(mb_vis))
        except Exception:
            pass
    except Exception:
        pass


def save_window_state(app) -> None:
    """Persist window geometry/state and UI visibility flags."""
    try:
        settings = QSettings(ORG, APP)
        settings.setValue('window_geometry', app.saveGeometry())
        settings.setValue('window_state', app.saveState())
        try:
            if hasattr(app, 'toolbar') and app.toolbar:
                settings.setValue('toolbar_visible', app.toolbar.isVisible())
        except Exception:
            pass
        try:
            settings.setValue('menubar_visible', app.menuBar().isVisible())
        except Exception:
            pass
    except Exception:
        pass
