from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QTreeWidgetItem, QTreeWidget
import os as _os
# В тестовом окружении не импортируем QtWebEngine, чтобы не создавать профили/страницы
if _os.environ.get('SMALL_RSS_TESTS') or _os.environ.get('PYTEST_CURRENT_TEST'):
    QWebEnginePage = object  # type: ignore
    QWebEngineView = object  # type: ignore
else:  # pragma: no cover - UI path
    try:
        from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView, QWebEngineScript
    except Exception:  # pragma: no cover
        QWebEnginePage = object  # type: ignore
        QWebEngineView = object  # type: ignore
        QWebEngineScript = object  # type: ignore
from PyQt5.QtGui import QDesktopServices


class ArticleTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        data1 = self.data(column, Qt.UserRole)
        data2 = other.data(column, Qt.UserRole)

        # If we stored a full entry dict in UserRole (common for Title column),
        # fall back to visible text to keep sorting stable and intuitive.
        if isinstance(data1, dict):
            data1 = ''
        if isinstance(data2, dict):
            data2 = ''

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            profile = self.profile()
            if profile and hasattr(profile, 'setHttpUserAgent'):
                profile.setHttpUserAgent(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                )
        except Exception:
            pass
        try:
            script = QWebEngineScript()
            script.setName('polyfill-at')
            script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            script.setWorldId(QWebEngineScript.MainWorld)
            script.setRunsOnSubFrames(True)
            script.setSourceCode(
                "(function(){"
                "if(!Array.prototype.at){Object.defineProperty(Array.prototype,'at',{value:function(n){n=Math.trunc(n)||0;if(n<0)n+=this.length;return this[n];},writable:true,configurable:true});}"
                "if(!String.prototype.at){Object.defineProperty(String.prototype,'at',{value:function(n){n=Math.trunc(n)||0;if(n<0)n+=this.length;return this[n];},writable:true,configurable:true});}"
                "if(typeof Int8Array!=='undefined' && !Int8Array.prototype.at){"
                "var types=[Int8Array,Uint8Array,Uint8ClampedArray,Int16Array,Uint16Array,Int32Array,Uint32Array,Float32Array,Float64Array];"
                "if(typeof BigInt64Array!=='undefined')types.push(BigInt64Array);"
                "if(typeof BigUint64Array!=='undefined')types.push(BigUint64Array);"
                "for(var i=0;i<types.length;i++){try{Object.defineProperty(types[i].prototype,'at',{value:function(n){n=Math.trunc(n)||0;if(n<0)n+=this.length;return this[n];},writable:true,configurable:true});}catch(e){}}"
                "}"
                "})();"
            )
            self.scripts().insert(script)
        except Exception:
            pass
        self._preview_cleanup_enabled = False

    def enable_preview_dom_cleanup(self) -> None:
        try:
            if self._preview_cleanup_enabled:
                return
        except Exception:
            pass
        try:
            script = QWebEngineScript()
            script.setName('preview-dom-cleanup')
            script.setInjectionPoint(QWebEngineScript.DocumentReady)
            script.setWorldId(QWebEngineScript.MainWorld)
            script.setRunsOnSubFrames(True)
            script.setSourceCode(
                "(function(){"
                "var sels=["
                "'.banner-slider','[class*=\\\"banner-slider\\\"]','[id*=\\\"banner-slider\\\"]',"
                "'.promo','[class*=\\\"promo\\\"]','[id*=\\\"promo\\\"]',"
                "'.adfox','[class*=\\\"adfox\\\"]','[id*=\\\"adfox\\\"]',"
                "'.sponsored','[class*=\\\"sponsored\\\"]','[id*=\\\"sponsored\\\"]',"
                "'[class*=\\\"native-ad\\\"]','[id*=\\\"native-ad\\\"]',"
                "'[class*=\\\"advert\\\"]','[id*=\\\"advert\\\"]'"
                "];"
                "var joined=sels.join(',');"
                "function sweep(root){"
                "try{(root||document).querySelectorAll(joined).forEach(function(n){try{n.remove();}catch(e){}});}catch(e){}"
                "}"
                "sweep(document);"
                "try{new MutationObserver(function(){sweep(document);}).observe(document.documentElement||document,{subtree:true,childList:true});}catch(e){}"
                "try{setTimeout(function(){sweep(document);},350);}catch(e){}"
                "try{setTimeout(function(){sweep(document);},1200);}catch(e){}"
                "})();"
            )
            self.scripts().insert(script)
            self._preview_cleanup_enabled = True
        except Exception:
            pass

    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if (_type == QWebEnginePage.NavigationTypeLinkClicked):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        return

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
