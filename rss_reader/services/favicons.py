from PyQt5.QtCore import pyqtSlot, QRunnable
import requests


class FaviconFetchRunnable(QRunnable):
    def __init__(self, domain: str, reader):
        super().__init__()
        self.domain = domain
        self.reader = reader

    @pyqtSlot()
    def run(self):
        def _safe_emit(signal, *args):
            try:
                signal.emit(*args)
            except RuntimeError:
                # Can happen during app shutdown: QObject is already deleted.
                return False
            except Exception:
                return False
            return True

        try:
            for scheme in ("https", "http"):
                url = f"{scheme}://{self.domain}/favicon.ico"
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200 and resp.content:
                        _safe_emit(self.reader.icon_fetched, self.domain, resp.content)
                        return
                except Exception:
                    continue
            try:
                s2 = f"https://www.google.com/s2/favicons?sz=64&domain={self.domain}"
                resp = requests.get(s2, timeout=5)
                if resp.status_code == 200 and resp.content:
                    _safe_emit(self.reader.icon_fetched, self.domain, resp.content)
                    return
            except Exception:
                pass
            try:
                _safe_emit(self.reader.icon_fetch_failed, self.domain)
            except Exception:
                pass
        except Exception:
            try:
                _safe_emit(self.reader.icon_fetch_failed, self.domain)
            except Exception:
                pass
