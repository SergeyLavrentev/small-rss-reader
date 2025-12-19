import logging
import feedparser
from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot


class Worker(QObject):
    feed_fetched = pyqtSignal(str, object)  # Emits (url, feed)


class FetchFeedRunnable(QRunnable):
    def __init__(self, url, worker: Worker):
        super().__init__()
        self.url = url
        self.worker = worker

    @pyqtSlot()
    def run(self):
        def _safe_emit(feed_obj):
            try:
                self.worker.feed_fetched.emit(self.url, feed_obj)
            except RuntimeError:
                # Can happen during app shutdown: QObject is already deleted.
                logging.debug("feed_fetched dropped: worker deleted")
            except Exception:
                # Never let exceptions escape QRunnable.run(); PyQt/Qt can abort the process.
                logging.debug("feed_fetched dropped: unexpected emit error", exc_info=True)

        try:
            feed = feedparser.parse(self.url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            _safe_emit(feed)
        except Exception as e:
            logging.error(f"Failed to fetch feed {self.url}: {e}")
            _safe_emit(None)
