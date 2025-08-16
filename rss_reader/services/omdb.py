import logging
from typing import Any, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot


class OmdbWorker(QObject):
    movie_fetched = pyqtSignal(str, dict)  # title -> data
    movie_failed = pyqtSignal(str, Exception)


class FetchOmdbRunnable(QRunnable):
    def __init__(self, title: str, api_key: str, worker: OmdbWorker, year: Optional[int] = None):
        super().__init__()
        self.title = title
        self.api_key = api_key
        self.worker = worker
        self.year = year

    @pyqtSlot()
    def run(self):
        try:
            # Use omdbapi like in main branch
            from omdbapi.movie_search import GetMovie
            movie = GetMovie(api_key=self.api_key)
            data: Optional[Dict[str, Any]] = None
            # Try multiple signatures to be compatible across omdbapi versions and dummies
            # Preference order keeps 'year' when possible and requests full plot when supported
            attempts = []
            if self.year is not None:
                attempts.extend([
                    dict(title=self.title, plot='full', year=self.year),
                    dict(title=self.title, plot='full', y=self.year),
                    dict(title=self.title, year=self.year),
                    dict(title=self.title, y=self.year),
                ])
            # Without year
            attempts.extend([
                dict(title=self.title, plot='full'),
                dict(title=self.title),
            ])

            for kwargs in attempts:
                try:
                    data = movie.get_movie(**kwargs)  # type: ignore[call-arg]
                    break
                except TypeError:
                    continue
            if data is None:
                data = movie.get_movie(title=self.title)  # final fallback
            if not isinstance(data, dict) or not data:
                raise RuntimeError('Invalid OMDb response')
            try:
                self.worker.movie_fetched.emit(self.title, data)
            except RuntimeError:
                # Worker might be deleted during app shutdown; drop signal quietly
                logging.debug("OMDb movie_fetched dropped: worker deleted")
        except Exception as e:
            logging.error(f"OMDb fetch failed for '{self.title}': {e}")
            try:
                self.worker.movie_failed.emit(self.title, e)
            except RuntimeError:
                logging.debug("OMDb movie_failed dropped: worker deleted")
