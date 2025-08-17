from PyQt5.QtCore import pyqtSlot, QRunnable
import requests


class FaviconFetchRunnable(QRunnable):
    def __init__(self, domain: str, reader):
        super().__init__()
        self.domain = domain
        self.reader = reader

    @pyqtSlot()
    def run(self):
        try:
            for scheme in ("https", "http"):
                url = f"{scheme}://{self.domain}/favicon.ico"
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200 and resp.content:
                        self.reader.icon_fetched.emit(self.domain, resp.content)
                        return
                except Exception:
                    continue
            try:
                s2 = f"https://www.google.com/s2/favicons?sz=64&domain={self.domain}"
                resp = requests.get(s2, timeout=5)
                if resp.status_code == 200 and resp.content:
                    self.reader.icon_fetched.emit(self.domain, resp.content)
                    return
            except Exception:
                pass
            try:
                self.reader.icon_fetch_failed.emit(self.domain)
            except Exception:
                pass
        except Exception:
            try:
                self.reader.icon_fetch_failed.emit(self.domain)
            except Exception:
                pass
