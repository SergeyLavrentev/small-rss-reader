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
        try:
            feed = feedparser.parse(self.url)
            if feed.bozo and feed.bozo_exception:
                raise feed.bozo_exception
            self.worker.feed_fetched.emit(self.url, feed)
        except Exception as e:
            logging.error(f"Failed to fetch feed {self.url}: {e}")
            self.worker.feed_fetched.emit(self.url, None)
