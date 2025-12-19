from __future__ import annotations

import os
from typing import Optional, Dict, Any

from PyQt5.QtCore import Qt, QUrl, QEvent
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextBrowser, QShortcut
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# Do not import QtWebEngine at module import time to avoid crashes in tests
QWebEngineView = None  # type: ignore
WebEnginePage = None  # type: ignore


class QuickPreview(QWidget):
    """Frameless minimalist preview window for full-page article view.

    - Toggle with Space (close if open)
    - Navigate with Up/Down to previous/next article (delegates to parent app)
    - Close with Esc
    """

    def __init__(self, app_window, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._app = app_window  # RSSReader
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        # Frameless, minimal, floating on top
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # Thin visible border and solid background so it stands out a bit
        try:
            self.setObjectName("QuickPreview")
            self.setAttribute(Qt.WA_StyledBackground, True)
            # Minimal, but noticeable thin border
            self.setStyleSheet("#QuickPreview { border: 1px solid rgba(0,0,0,140); background: #ffffff; }")
        except Exception:
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # Lazily decide content engine
        self._use_web = False
        try:
            if not (os.environ.get('SMALL_RSS_TESTS') or os.environ.get('PYTEST_CURRENT_TEST')):
                # Import here to avoid loading QtWebEngine during tests
                from PyQt5.QtWebEngineWidgets import QWebEngineView as _QWebEngineView  # type: ignore
                from rss_reader.ui.widgets import WebEnginePage as _WebEnginePage  # type: ignore
                self._use_web = True
        except Exception:
            self._use_web = False
        if self._use_web:
            # Re-import inside branch to get symbols
            from PyQt5.QtWebEngineWidgets import QWebEngineView as _QWebEngineView  # type: ignore
            from rss_reader.ui.widgets import WebEnginePage as _WebEnginePage  # type: ignore
            self.view = _QWebEngineView(self)
            try:
                # Use our custom page to handle external links/target=_blank
                self.view.setPage(_WebEnginePage(self.view))
            except Exception:
                pass
        else:
            view = QTextBrowser(self)
            try:
                view.setOpenExternalLinks(True)
                # Ensure clicked anchors open externally in tests
                from PyQt5.QtGui import QDesktopServices
                view.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))
            except Exception:
                pass
            self.view = view

        lay.addWidget(self.view)
        # Intercept keys on the window and on the inner view to avoid default scrolling
        try:
            self.installEventFilter(self)
            self.view.installEventFilter(self)
            # Also add shortcuts with WidgetWithChildren context to override internal page scrolling
            # Note: Space is handled via eventFilter/keyPressEvent to ensure event.accept() and prevent propagation
            sc_close_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
            sc_close_esc.setContext(Qt.WidgetWithChildrenShortcut)
            sc_close_esc.activated.connect(self.close)
            sc_up = QShortcut(QKeySequence(Qt.Key_Up), self)
            sc_up.setContext(Qt.WidgetWithChildrenShortcut)
            sc_up.activated.connect(lambda: self._nav(-1))
            sc_down = QShortcut(QKeySequence(Qt.Key_Down), self)
            sc_down.setContext(Qt.WidgetWithChildrenShortcut)
            sc_down.activated.connect(lambda: self._nav(+1))
        except Exception:
            pass
        self.resize(900, 620)

        # Subtle drop shadow only in QTextBrowser mode.
        # On macOS, applying QGraphicsEffect to a window that hosts QWebEngineView can make it render blank.
        try:
            if not self._use_web:
                shadow = QGraphicsDropShadowEffect(self)
                shadow.setBlurRadius(16)
                shadow.setOffset(0, 0)
                from PyQt5.QtGui import QColor
                shadow.setColor(QColor(0, 0, 0, 64))
                self.setGraphicsEffect(shadow)
        except Exception:
            pass

    # -------- Content loading --------
    def load_entry(self, entry: Dict[str, Any]) -> None:
        link = (entry or {}).get('link') or ''
        if not link:
            try:
                self._set_html("<html><body><p style='margin:16px'>No link</p></body></html>")
            except Exception:
                pass
            return
        if self._use_web:
            try:
                self.view.load(QUrl(link))
                return
            except Exception:
                pass
        # Fallback: fetch raw HTML and show in QTextBrowser
        try:
            import requests
            resp = requests.get(link, timeout=8, headers={
                'User-Agent': 'SmallRSSReader/1.0 (+https://github.com/SergeyLavrentev)'
            })
            txt = resp.text if hasattr(resp, 'text') else ''
            if txt:
                try:
                    self._set_html(txt, base=link)
                except Exception:
                    self._set_html(txt)
            else:
                self._set_html(f"<html><body><p style='margin:16px'>Failed to load: {link}</p></body></html>")
        except Exception:
            try:
                self._set_html(f"<html><body><p style='margin:16px'>Failed to load: {link}</p></body></html>")
            except Exception:
                pass

    def _set_html(self, html: str, base: str = '') -> None:
        try:
            if hasattr(self.view, 'setHtml'):
                if base:
                    self.view.setHtml(html, QUrl(base))
                else:
                    self.view.setHtml(html)
        except Exception:
            try:
                if hasattr(self.view, 'setText'):
                    self.view.setText(html)
            except Exception:
                pass

    # -------- Window positioning --------
    def show_centered(self) -> None:
        try:
            parent = self._app
            if parent and parent.isVisible():
                pg = parent.geometry()
                x = pg.x() + (pg.width() - self.width()) // 2
                y = pg.y() + (pg.height() - self.height()) // 2
                self.move(max(0, x), max(0, y))
        except Exception:
            pass
        self.show()
        try:
            self.raise_()
            self.activateWindow()
            try:
                self.setFocus(Qt.ActiveWindowFocusReason)
            except Exception:
                pass
        except Exception:
            pass

    # -------- Keys handling --------
    def keyPressEvent(self, event):  # noqa: N802
        try:
            key = event.key()
            if key in (Qt.Key_Escape, Qt.Key_Space):
                self.close()
                return
            if key == Qt.Key_Down:
                if hasattr(self._app, '_quick_move_selection'):
                    self._app._quick_move_selection(+1)
                    self._app._update_quick_preview()
                return
            if key == Qt.Key_Up:
                if hasattr(self._app, '_quick_move_selection'):
                    self._app._quick_move_selection(-1)
                    self._app._update_quick_preview()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802
        try:
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Escape, Qt.Key_Space):
                    try:
                        event.accept()
                    except Exception:
                        pass
                    self.close()
                    return True
                if key == Qt.Key_Down:
                    self._nav(+1)
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                if key == Qt.Key_Up:
                    self._nav(-1)
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    # no-op helper removed; Space shortcut closes directly

    def _nav(self, delta: int) -> None:
        try:
            if hasattr(self._app, '_quick_move_selection'):
                self._app._quick_move_selection(int(delta or 0))
                self._app._update_quick_preview()
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        # Best-effort cleanup for QtWebEngine.
        # On macOS especially, leaving a QWebEnginePage alive during application shutdown
        # can lead to crashes ("WebEnginePage still not deleted").
        try:
            if getattr(self, '_use_web', False):
                view = getattr(self, 'view', None)
                try:
                    if view is not None and hasattr(view, 'stop'):
                        view.stop()
                except Exception:
                    pass
                try:
                    if view is not None and hasattr(view, 'setUrl'):
                        view.setUrl(QUrl('about:blank'))
                except Exception:
                    pass
                try:
                    page = view.page() if view is not None and hasattr(view, 'page') else None
                    if page is not None and hasattr(page, 'deleteLater'):
                        page.deleteLater()
                except Exception:
                    pass
                try:
                    if view is not None and hasattr(view, 'deleteLater'):
                        view.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(self._app, '_preview'):
                self._app._preview = None
        except Exception:
            pass
        super().closeEvent(event)
