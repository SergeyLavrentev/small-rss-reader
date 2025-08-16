from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem, QTreeWidget
try:
    from PyQt5.QtWebEngineWidgets import QWebEnginePage
except Exception:  # pragma: no cover - not available in test-light mode
    QWebEnginePage = object  # type: ignore
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
        try:
            if isinstance(data1, float) and isinstance(data2, float):
                return data1 < data2
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
