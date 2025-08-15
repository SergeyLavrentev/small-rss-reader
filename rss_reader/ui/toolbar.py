from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QToolBar, QCheckBox, QLabel, QLineEdit, QSizePolicy
from PyQt5.QtWidgets import QWidget, QHBoxLayout


def setup_toolbar(app: Any) -> None:
    app.toolbar = QToolBar("Main", app)
    app.toolbar.setMovable(False)
    try:
        app.toolbar.setIconSize(QSize(16, 16))
    except Exception:
        pass
    app.addToolBar(app.toolbar)
    try:
        app.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
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
        "QToolBar QToolButton{padding:4px 8px;border-radius:6px;margin:0 2px;}"
        "QToolBar QToolButton[intent='primary']{background:#2ecc71;color:black;}"
        "QToolBar QToolButton[intent='info']{background:#3498db;color:white;}"
        "QToolBar QToolButton[intent='danger']{background:#e74c3c;color:white;}"
        "QToolBar QToolButton[intent='success']{background:#27ae60;color:white;}"
        "QToolBar QToolButton[intent='warning']{background:#f39c12;color:black;}"
        "QToolBar QToolButton:hover{filter:brightness(1.1);}"
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
