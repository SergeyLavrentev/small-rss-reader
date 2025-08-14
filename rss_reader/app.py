"""Application-level API for Small RSS Reader.

Temporary shim that re-exports UI classes from the legacy module, plus
provides a dynamic get_user_data_path() that respects tests monkeypatching
small_rss_reader.get_user_data_path.
"""
from __future__ import annotations

import sys
from typing import Optional

# Dynamic adapter that prefers small_rss_reader.get_user_data_path if present
try:
    from rss_reader.utils.paths import get_user_data_path as _default_get_user_data_path
except Exception:  # pragma: no cover
    _default_get_user_data_path = lambda name: name  # fallback


def get_user_data_path(filename: str) -> str:
    mod = sys.modules.get("small_rss_reader")
    if mod is not None:
        fn = getattr(mod, "get_user_data_path", None)
        if callable(fn):
            try:
                return fn(filename)
            except Exception:
                pass
    return _default_get_user_data_path(filename)

# Export legacy classes for now; next step: host full implementation here
from small_rss_reader import (  # type: ignore E402  # noqa: E402
    RSSReader as RSSReader,  # re-export
    PopulateArticlesThread as PopulateArticlesThread,
    FetchMovieDataThread as FetchMovieDataThread,
)
