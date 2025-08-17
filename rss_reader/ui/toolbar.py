from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QToolBar, QCheckBox, QLabel, QLineEdit, QSizePolicy
from PyQt5.QtWidgets import QWidget, QHBoxLayout


def setup_toolbar(app: Any) -> None:
    app.toolbar = QToolBar("Main", app)
    try:
        app.toolbar.setObjectName("mainToolbar")
    except Exception:
        pass
    app.toolbar.setMovable(False)
    try:
        app.toolbar.setIconSize(QSize(16, 16))
    except Exception:
        pass
    app.addToolBar(app.toolbar)
    try:
        app.toolbar.setVisible(True)
    except Exception:
        pass
    try:
        app.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    except Exception:
        pass
    try:
        app.toolbar.setFloatable(False)
        app.toolbar.setAllowedAreas(Qt.TopToolBarArea | Qt.BottomToolBarArea)
        # Ensure buttons show as flat but react on hover/press
        for act in []:
            btn = app.toolbar.widgetForAction(act)
            if btn:
                btn.setAutoRaise(True)
    except Exception:
        pass

    # Group 1: Feed CRUD
    app.toolbar.addAction(app.actAddFeed)
    app.toolbar.addAction(app.actRemoveFeed)
    app.toolbar.addSeparator(); _add_toolbar_spacer(app, 8)
    # Group 2: Refresh
    app.toolbar.addAction(app.actRefreshAll)
    app.toolbar.addAction(app.actRefreshFeed)
    app.toolbar.addSeparator(); _add_toolbar_spacer(app, 8)
    # Group 3: Read state
    app.toolbar.addAction(app.actMarkAllRead)
    app.toolbar.addAction(app.actMarkAllUnread)
    # Ensure actions are enabled
    try:
        for act in [app.actAddFeed, app.actRemoveFeed, app.actRefreshAll, app.actRefreshFeed, app.actMarkAllRead, app.actMarkAllUnread]:
            act.setEnabled(True)
    except Exception:
        pass

    # Small visual gap before the center group
    app.toolbar.addSeparator(); _add_toolbar_spacer(app, 6)
    # Center group: Unread checkbox + Search field (immediately after last button)
    center = QWidget(app)
    # Ensure no margins/padding inside the center group so checkbox and search are flush
    try:
        center.setStyleSheet(
            "*{margin:0;padding:0;}"
            "QCheckBox{margin:0;padding:0;}"
            "QCheckBox::indicator{margin:0;padding:0;}"
            "QLineEdit{margin:0;}"
        )
    except Exception:
        pass
    hl = QHBoxLayout(center)
    hl.setContentsMargins(0, 0, 0, 0)
    # Small gap between checkbox text and search field
    hl.setSpacing(20)

    # Unread checkbox (single widget with text, like in main)
    app.unreadCheck = QCheckBox("Show only unread", center)
    app.unreadCheck.setToolTip("Show only unread")
    try:
        app.unreadCheck.setContentsMargins(0, 0, 0, 0)
        app.unreadCheck.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    except Exception:
        pass
    try:
        app.unreadCheck.setChecked(app.actOnlyUnread.isChecked())
    except Exception:
        pass
    app.unreadCheck.toggled.connect(lambda c: app.actOnlyUnread.setChecked(c))
    try:
        app.actOnlyUnread.toggled.connect(lambda c: (app.unreadCheck.blockSignals(True), app.unreadCheck.setChecked(c), app.unreadCheck.blockSignals(False)))
    except Exception:
        pass
    hl.addWidget(app.unreadCheck, 0)

    app.searchEdit = QLineEdit(center)
    app.searchEdit.setPlaceholderText("Search…")
    app.searchEdit.textChanged.connect(app._on_search_changed)
    try:
        app.searchEdit.setContentsMargins(0, 0, 0, 0)
        app.searchEdit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    except Exception:
        pass
    try:
        app.searchEdit.setFixedWidth(280)
    except Exception:
        pass
    hl.addWidget(app.searchEdit)

    app.toolbar.addWidget(center)
    _add_toolbar_spacer(app, 0, expand=True)

    # Styling
    try:
        apply_toolbar_styles(app)
    except Exception:
        pass


def _add_toolbar_spacer(app: Any, width: int = 8, expand: bool = False) -> None:
    from PyQt5.QtWidgets import QWidget
    try:
        spacer = QWidget(app)
        if expand:
            spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            spacer.setFixedWidth(max(0, width))
        app.toolbar.addWidget(spacer)
    except Exception:
        pass


def apply_toolbar_styles(app: Any) -> None:
    qss = (
        # Base button look + clear hover/pressed feedback
        "QToolBar QToolButton{padding:4px 8px;border-radius:6px;margin:0 2px;"
        "background:transparent;color:inherit;}"
        "QToolBar QToolButton:hover{background:rgba(255,255,255,0.10);}"
        "QToolBar QToolButton:pressed{background:rgba(0,0,0,0.18);}"
        "QToolBar QToolButton:disabled{background:rgba(0,0,0,0.06);color:#9aa0a6;}"

        # Intents with explicit hover/pressed shades
        "QToolBar QToolButton[intent='primary']{background:#2ecc71;color:black;}"
        "QToolBar QToolButton[intent='primary']:hover{background:#3ee07f;}"
        "QToolBar QToolButton[intent='primary']:pressed{background:#28b765;}"

        "QToolBar QToolButton[intent='info']{background:#3498db;color:white;}"
        "QToolBar QToolButton[intent='info']:hover{background:#3ea7ef;}"
        "QToolBar QToolButton[intent='info']:pressed{background:#2d86c4;}"

        "QToolBar QToolButton[intent='danger']{background:#e74c3c;color:white;}"
        "QToolBar QToolButton[intent='danger']:hover{background:#ee5b50;}"
        "QToolBar QToolButton[intent='danger']:pressed{background:#cf4437;}"

        "QToolBar QToolButton[intent='success']{background:#27ae60;color:white;}"
        "QToolBar QToolButton[intent='success']:hover{background:#2fbe6d;}"
        "QToolBar QToolButton[intent='success']:pressed{background:#229955;}"

        "QToolBar QToolButton[intent='warning']{background:#f39c12;color:black;}"
        "QToolBar QToolButton[intent='warning']:hover{background:#f6a42b;}"
        "QToolBar QToolButton[intent='warning']:pressed{background:#da8c0b;}"
    )
    app.toolbar.setStyleSheet(qss)

    def set_intent(act, name: str) -> None:
        try:
            btn = app.toolbar.widgetForAction(act)
            if btn:
                btn.setProperty('intent', name)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        except Exception:
            pass

    set_intent(app.actAddFeed, 'primary')
    set_intent(app.actRefreshAll, 'info')
    set_intent(app.actRefreshFeed, 'info')
    set_intent(app.actRemoveFeed, 'danger')
    set_intent(app.actMarkAllRead, 'success')
    set_intent(app.actMarkAllUnread, 'warning')
