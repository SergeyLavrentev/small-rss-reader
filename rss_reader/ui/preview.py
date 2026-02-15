from __future__ import annotations

import os
import time
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
        self._current_entry: Dict[str, Any] = {}
        self._reader_mode_enabled = False
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
                page = _WebEnginePage(self.view)
                if hasattr(page, 'enable_preview_dom_cleanup'):
                    page.enable_preview_dom_cleanup()
                self.view.setPage(page)
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
            sc_reader = QShortcut(QKeySequence(Qt.Key_R), self)
            sc_reader.setContext(Qt.WidgetWithChildrenShortcut)
            sc_reader.activated.connect(self._toggle_reader_mode)
        except Exception:
            pass
        self.resize(900, 620)
        # Prevent immediate close when the same Space key event that opened preview
        # is still propagating in the event loop.
        self._ignore_space_until = 0.0

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
        self._current_entry = dict(entry or {})
        if not link:
            try:
                self._set_html("<html><body><p style='margin:16px'>No link</p></body></html>")
            except Exception:
                pass
            return
        try:
            if self._reader_mode_enabled:
                html = self._fetch_reader_html(link, (entry or {}).get('title') or '')
                if html:
                    self._set_html(html, base=link)
                    return
        except Exception:
            pass
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

    def _toggle_reader_mode(self) -> None:
        try:
            self._reader_mode_enabled = not bool(self._reader_mode_enabled)
        except Exception:
            self._reader_mode_enabled = False
        try:
            if self._current_entry:
                self.load_entry(self._current_entry)
        except Exception:
            pass

    def _fetch_reader_html(self, link: str, title: str) -> str:
        try:
            import requests
            resp = requests.get(link, timeout=10, allow_redirects=True, headers={
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://habr.com/',
            })
            txt = resp.text if hasattr(resp, 'text') else ''
            if not txt:
                return ''
            return self._extract_reader_content(txt, link, title)
        except Exception:
            return ''

    def _extract_reader_content(self, html: str, link: str, title: str) -> str:
        try:
            import re
            import html as _html
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html or '', 'html.parser')
            for t in soup(['script', 'style', 'noscript', 'svg']):
                try:
                    t.decompose()
                except Exception:
                    pass

            for sel in [
                'header', 'footer', 'nav', 'aside',
                '.tm-layout__header', '.tm-layout__sidebar', '.tm-page__top',
                '.tm-article-sticky-panel', '.tm-article-presenter__meta',
                '.tm-article-snippet__hubs', '.tm-article-body__tags',
                '.tm-article-presenter__footer', '.tm-comment',
                '.tm-comment-thread', '.tm-page-width',
                '.banner-slider',
                '.promo', '.adfox', '.sponsored',
                '[id*="adfox"]', '[class*="adfox"]',
                '[id*="sponsored"]', '[class*="sponsored"]',
            ]:
                try:
                    for n in soup.select(sel):
                        n.decompose()
                except Exception:
                    pass

            noisy_re = re.compile(r'(ad|ads|banner|promo|adfox|sponsored|native-ad|advert|related|share|comments?|toolbar|footer|header|menu|sidebar|subscription|recommend)', re.I)
            for n in list(soup.find_all(True)):
                try:
                    cl = ' '.join(n.get('class') or [])
                    nid = n.get('id') or ''
                    if noisy_re.search(cl) or noisy_re.search(nid):
                        n.decompose()
                except Exception:
                    pass

            container = None
            selectors = [
                'article.tm-article-presenter__content',
                'article.tm-article-snippet',
                '.tm-article-body',
                '.article-formatted-body',
                '[itemprop="articleBody"]',
                'article',
                'main',
            ]
            for sel in selectors:
                container = soup.select_one(sel)
                if container is not None:
                    break

            if container is None:
                return ''

            h1 = soup.select_one('h1')
            title_html = ''
            if h1 is not None:
                try:
                    title_html = f"<h1>{_html.escape(h1.get_text(' ', strip=True))}</h1>"
                except Exception:
                    title_html = ''
            elif title:
                title_html = f"<h1>{_html.escape(title)}</h1>"

            for n in list(container.find_all(True)):
                try:
                    cls = ' '.join(n.get('class') or [])
                    nid = n.get('id') or ''
                    lowered = (cls + ' ' + str(nid)).lower()
                    if any(tok in lowered for tok in ('banner-slider', 'promo', 'adfox', 'sponsored', 'native-ad', 'advert')):
                        n.decompose()
                        continue
                    if n.name in ('button', 'input', 'form', 'aside'):
                        n.decompose()
                        continue
                    attrs = dict(n.attrs or {})
                    kept = {}
                    for k, v in attrs.items():
                        lk = str(k).lower()
                        if lk.startswith('on'):
                            continue
                        if lk in ('style', 'class', 'id', 'href', 'src', 'alt', 'title', 'width', 'height'):
                            kept[k] = v
                    n.attrs = kept
                except Exception:
                    pass

            mode_label = "Reader mode · R — full page"

            return (
                "<html><head><meta charset='utf-8'>"
                f"<base href='{link}'>"
                "<style>"
                "html,body{background:#f6f8fb;color:#1f2937;}"
                "body{font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.72;margin:0;}"
                ".wrap{max-width:860px;margin:18px auto;padding:28px 34px;background:#fff;border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,.08);}"
                ".mode{font-size:12px;color:#6b7280;margin-bottom:10px;}"
                "h1{font-size:30px;line-height:1.25;margin:0 0 16px 0;}"
                "p,li{font-size:17px;}"
                "img,video,iframe{max-width:100%;height:auto;border-radius:8px;}"
                "pre{white-space:pre-wrap;background:#f5f5f5;padding:10px;border-radius:8px;overflow:auto;}"
                "code{font-family:SFMono-Regular,Menlo,monospace;font-size:13px;}"
                "a{color:#2563eb;text-decoration:none;}"
                "a:hover{text-decoration:underline;}"
                "hr{border:none;border-top:1px solid #e5e7eb;margin:22px 0 14px;}"
                "</style></head><body>"
                "<div class='wrap'>"
                f"<div class='mode'>{mode_label}</div>"
                f"{title_html}"
                f"<article>{str(container)}</article>"
                f"<hr><p><a href='{link}' target='_blank'>Open original</a></p>"
                "</div>"
                "</body></html>"
            )
        except Exception:
            return ''

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
            # Ignore only the immediate propagated Space event right after opening.
            self._ignore_space_until = time.monotonic() + 0.06
        except Exception:
            self._ignore_space_until = 0.0
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
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Escape):
                self._ignore_space_until = 0.0
            if key == Qt.Key_R:
                self._toggle_reader_mode()
                try:
                    event.accept()
                except Exception:
                    pass
                return
            if key == Qt.Key_Space and time.monotonic() < float(getattr(self, '_ignore_space_until', 0.0) or 0.0):
                try:
                    event.accept()
                except Exception:
                    pass
                return
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
                if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Escape):
                    self._ignore_space_until = 0.0
                if key == Qt.Key_R:
                    self._toggle_reader_mode()
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                if key == Qt.Key_Space and time.monotonic() < float(getattr(self, '_ignore_space_until', 0.0) or 0.0):
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
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
