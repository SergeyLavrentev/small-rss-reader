from __future__ import annotations

from collections import deque
import re
from typing import Any, Dict, Iterable, Optional, Set, Tuple

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
        # queue holds tuples of (raw_title, query_title, year)
        self._queue: deque[Tuple[str, str, Optional[int]]] = deque()
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
        self._auth_failed = False

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

    def set_auth_failed(self, failed: bool):
        self._auth_failed = bool(failed)
        if self._auth_failed:
            try:
                self._timer.stop()
                self._queue.clear()
                self._queued.clear()
                self._inflight.clear()
            except Exception:
                pass
        else:
            # allow processing again
            pass

    def clear(self):
        try:
            self._queue.clear()
            self._queued.clear()
            self._inflight.clear()
        except Exception:
            pass

    # API
    def request_for_entries(self, entries: Iterable[Dict[str, Any]]):
        if not self._columns_visible:
            return
        api_key = self._get_api_key() or ''
        if not api_key or not self._worker or not self._pool or self._auth_failed:
            return
        enqueued = False
        for e in entries:
            raw_title = (e.get('title') or e.get('link') or '').strip()
            if not raw_title:
                continue
            query_title, year = self._extract_title_year(raw_title)
            norm = self._norm_title(query_title or raw_title)
            # If either raw or normalized key is cached, skip enqueue
            if (raw_title in self._cache) or (norm in self._cache):
                continue
            if norm in self._inflight or norm in self._queued:
                continue
            self._queue.append((raw_title, query_title or raw_title, year))
            self._queued.add(norm)
            enqueued = True
        if enqueued and not self._timer.isActive():
            self._timer.start()

    @pyqtSlot()
    def _process(self):
        api_key = self._get_api_key() or ''
        if not api_key or self._auth_failed:
            self._timer.stop()
            return
        progressed = False
        while self._queue and len(self._inflight) < self._max_inflight:
            raw_title, query_title, year = self._queue.popleft()
            norm = self._norm_title(query_title or raw_title)
            self._queued.discard(norm)
            # Skip dispatch if we already have data by raw or normalized key
            if (raw_title in self._cache) or (norm in self._cache):
                continue
            if norm in self._inflight:
                continue
            try:
                from rss_reader.services.omdb import FetchOmdbRunnable
                runnable = FetchOmdbRunnable(query_title or raw_title, api_key, self._worker, year=year)
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
        # Reuse the same heuristic as extraction to keep keys consistent
        best, _ = OmdbQueueManager._extract_title_year(title or '')
        s = (best or '').strip().lower()
        return ' '.join(s.split())

    @staticmethod
    def _extract_title_year(raw: str) -> Tuple[str, Optional[int]]:
        """
        Heuristically extract an English-ish title and optional year from noisy titles.
        - Drop bracketed [ ... ] parts (release info, sizes, tags)
        - If title has ' / ' parts, pick the part with more ASCII letters
        - Remove director names in parentheses; keep year if found
        - Trim trailing language/track tags like VO/MVO/AVO/Dub/Sub/Original Eng, etc.
        - Cut off tails after separators like " + ", " - ", " — ", " | " when they look like metadata
        - Extract a plausible year (1900..2100) from () or [] or commas
        """
        s = (raw or '').strip()
        # Try to capture a plausible year from the original string first
        year: Optional[int] = None
        for m in re.finditer(r"(19\d{2}|20\d{2}|2100)", s):
            try:
                y = int(m.group(0))
                if 1900 <= y <= 2100:
                    year = y
                    break
            except Exception:
                pass

        # remove [ ... ] blocks
        s = re.sub(r"\[[^\]]+\]", " ", s)
        # remove parentheses that are not pure year (to prevent splitting on ' / ' inside them)
        s = re.sub(r"\((?!\d{4}\))[^)]*\)", " ", s)
        # split by ' / ' and pick ASCII-heavier part (now safe; director names removed)
        parts = [p.strip() for p in s.split(' / ') if p.strip()] or [s]

        def ascii_score(t: str) -> int:
            return sum(1 for ch in t if ord(ch) < 128 and ch.isalpha())

        best = max(parts, key=ascii_score)
        # quick cut at explicit separators commonly used for metadata
        for sep in [" + ", " - ", " — ", " | ", " • ", " · "]:
            if sep in best:
                best = best.split(sep, 1)[0]
        # remove any lingering parentheses again (safety)
        best = re.sub(r"\((?!\d{4}\))[^)]*\)", " ", best)
        # if a stray closing parenthesis remains and tail contains metadata-ish tokens, drop the tail
        if ")" in best:
            head, tail = best.rsplit(")", 1)
            if any(tok in tail for tok in [
                "+", "VO", "MVO", "AVO", "Dub", "Sub", "Original", "Eng", "Ukr", "Rus", "Deu", "Ger", "Fra", "Ita"
            ]):
                best = head
        # remove lingering language/track tags from the end
        lang_tokens = r"VO|MVO|AVO|Dub|Sub|Eng|English|Ukr|Ukrainian|Rus|Russian|Deu|Ger|German|Fra|French|Ita|Italian|Spa|Spanish|Pol|Polish"
        best = re.sub(rf"\b(?:{lang_tokens})\b.*$", " ", best, flags=re.IGNORECASE)
        # remove 'Original <Lang>' pattern tails
        best = re.sub(rf"\bOriginal\s+(?:{lang_tokens})\b.*$", " ", best, flags=re.IGNORECASE)
        # remove trailing count markers like '3x', '5x' that refer to number of tracks left after tag removal
        best = re.sub(r"\b\d+\s*[xх]\b\s*$", " ", best, flags=re.IGNORECASE)
        # collapse spaces
        best = ' '.join(best.split())
        return best, year
