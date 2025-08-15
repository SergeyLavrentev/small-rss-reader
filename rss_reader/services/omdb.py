import logging
from typing import Any, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot


class OmdbWorker(QObject):
    movie_fetched = pyqtSignal(str, dict)  # title -> data
    movie_failed = pyqtSignal(str, Exception)


class FetchOmdbRunnable(QRunnable):
    def __init__(self, title: str, api_key: str, worker: OmdbWorker):
        super().__init__()
        self.title = title
        self.api_key = api_key
        self.worker = worker

    @pyqtSlot()
    def run(self):
        try:
            import omdb
            if self.api_key:
                try:
                    omdb.set_default('apikey', self.api_key)
                except Exception:
                    pass
            # Use simple title lookup; the UI already maps row by title
            data: Optional[Dict[str, Any]] = omdb.get(title=self.title)  # type: ignore
            if not isinstance(data, dict):
                raise RuntimeError('Invalid OMDb response')
            self.worker.movie_fetched.emit(self.title, data)
        except Exception as e:
            logging.error(f"OMDb fetch failed for '{self.title}': {e}")
            self.worker.movie_failed.emit(self.title, e)
