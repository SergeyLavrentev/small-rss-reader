from __future__ import annotations

from collections import deque
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from PyQt5.QtCore import QObject, QTimer, pyqtSlot


class OmdbQueueManager(QObject):
    """
    Manages background OMDb fetch requests with per-tick dispatch,
    limited concurrency, normalization and cache-awareness.

    Contract:
    - call set_worker(worker) with services.omdb.OmdbWorker
    - call set_thread_pool(pool) with QThreadPool
    - call set_get_api_key(fn) -> str to provide the current API key
    - call set_cache_proxy(dict_like) so we can check/update cache
    - call request_for_entries(entries: Iterable[dict]) to enqueue
    - connect signals from worker to on_movie_fetched/failed
    - use columns_visible flag to ensure IMDb column is visible before fetches
    """

    def __init__(self, parent=None, max_inflight: int = 3, tick_ms: int = 300):
        super().__init__(parent)
        self._inflight: Set[str] = set()
        self._queued: Set[str] = set()
        self._queue: deque[str] = deque()
        self._max_inflight = max_inflight
        self._timer = QTimer(self)
        self._timer.setInterval(tick_ms)
        self._timer.timeout.connect(self._process)
        # external deps
        self._worker = None
        self._pool = None
        self._get_api_key = lambda: ''
        self._cache: Dict[str, Any] = {}
        self._columns_visible = True

    # wiring
    def set_worker(self, worker):
        self._worker = worker

    def set_thread_pool(self, pool):
        self._pool = pool

    def set_get_api_key(self, fn):
        self._get_api_key = fn or (lambda: '')

    def set_cache_proxy(self, cache: Dict[str, Any]):
        self._cache = cache

    def set_columns_visible(self, visible: bool):
        self._columns_visible = bool(visible)

    # API
    def request_for_entries(self, entries: Iterable[Dict[str, Any]]):
        if not self._columns_visible:
            return
        api_key = self._get_api_key() or ''
        if not api_key or not self._worker or not self._pool:
            return
        enqueued = False
        for e in entries:
            raw_title = (e.get('title') or e.get('link') or '').strip()
            if not raw_title:
                continue
            norm = self._norm_title(raw_title)
            if raw_title in self._cache or norm in self._cache:
                continue
            if norm in self._inflight or norm in self._queued:
                continue
            self._queue.append(raw_title)
            self._queued.add(norm)
            enqueued = True
        if enqueued and not self._timer.isActive():
            self._timer.start()

    @pyqtSlot()
    def _process(self):
        api_key = self._get_api_key() or ''
        if not api_key:
            self._timer.stop()
            return
        progressed = False
        while self._queue and len(self._inflight) < self._max_inflight:
            title = self._queue.popleft()
            norm = self._norm_title(title)
            self._queued.discard(norm)
            if title in self._cache or norm in self._cache:
                continue
            if norm in self._inflight:
                continue
            try:
                from rss_reader.services.omdb import FetchOmdbRunnable
                runnable = FetchOmdbRunnable(title, api_key, self._worker)
                self._inflight.add(norm)
                self._pool.start(runnable)
                progressed = True
            except Exception:
                pass
        if not self._queue and not progressed:
            self._timer.stop()

    def on_movie_fetched(self, title: str):
        self._inflight.discard(self._norm_title(title))
        self._process()

    def on_movie_failed(self, title: str):
        self._inflight.discard(self._norm_title(title))
        self._process()

    # helpers
    @staticmethod
    def _norm_title(title: str) -> str:
        s = (title or '').strip().lower()
        s = ' '.join(s.split())
        m = re.match(r"^(.*)\s*\((\d{4})\)$", s)
        if m:
            return m.group(1).strip()
        return s
