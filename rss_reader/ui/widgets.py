from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QTreeWidgetItem, QTreeWidget
import os as _os
# В тестовом окружении не импортируем QtWebEngine, чтобы не создавать профили/страницы
if _os.environ.get('SMALL_RSS_TESTS') or _os.environ.get('PYTEST_CURRENT_TEST'):
    QWebEnginePage = object  # type: ignore
    QWebEngineView = object  # type: ignore
else:  # pragma: no cover - UI path
    try:
        from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView
    except Exception:  # pragma: no cover
        QWebEnginePage = object  # type: ignore
        QWebEngineView = object  # type: ignore
from PyQt5.QtGui import QDesktopServices


class ArticleTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        data1 = self.data(column, Qt.UserRole)
        data2 = other.data(column, Qt.UserRole)

        if data1 is None or data1 == '':
            data1 = self.text(column)
        if data2 is None or data2 == '':
            data2 = other.text(column)

        if hasattr(data1, 'timestamp') and hasattr(data2, 'timestamp'):
            return data1 < data2
        # Numeric-aware sorting: ints/floats and numeric strings
        try:
            def _to_num(x):
                if isinstance(x, (int, float)):
                    return float(x)
                if isinstance(x, str):
                    s = x.strip().replace('\xa0', '')
                    s = s.replace('−', '-').replace('–', '-')
                    if s and (s.lstrip('+-').replace('.', '', 1).isdigit()):
                        try:
                            return float(s)
                        except Exception:
                            return None
                return None
            n1 = _to_num(data1)
            n2 = _to_num(data2)
            if n1 is not None and n2 is not None:
                return n1 < n2
        except Exception:
            pass
        return str(data1) < str(data2)


class FeedsTreeWidget(QTreeWidget):
    def dropEvent(self, event):
        source_item = self.currentItem()
        target_item = self.itemAt(event.pos())

        if target_item and source_item and target_item.parent() != source_item.parent():
            try:
                parent = self.parent()
                if hasattr(parent, 'warn'):
                    parent.warn("Invalid Move", "Feeds can only be moved within their own groups.")
            except Exception:
                pass
            event.ignore()
            return
        super().dropEvent(event)


class WebEnginePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if (_type == QWebEnginePage.NavigationTypeLinkClicked):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        pass

    def handleUnsupportedContent(self, reply):
        reply.abort()

    # Handle target=_blank and window.open() by opening externally
    def createWindow(self, _type):  # pragma: no cover - UI behavior
        try:
            # Return a transient page; open URL externally and dispose page
            page = QWebEnginePage(self.profile(), self)
            def _open(url):
                try:
                    QDesktopServices.openUrl(url)
                finally:
                    try:
                        page.deleteLater()
                    except Exception:
                        pass
            page.urlChanged.connect(_open)
            # Safety: if no URL ever arrives (popup without navigation), delete the page later
            try:
                QTimer.singleShot(2000, page.deleteLater)
            except Exception:
                pass
            return page
        except Exception:
            return None
