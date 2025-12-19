import os
import sys
import tempfile
from pathlib import Path
import hashlib


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
        # project root (rss_reader/utils -> ../..)
        base_path = os.path.abspath(os.path.join(base_path, os.pardir, os.pardir))
    return os.path.join(base_path, relative_path)


def get_user_data_path(filename: str) -> str:
    # Under pytest we want isolation from repo root and real user data.
    try:
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('SMALL_RSS_TESTS') or ('pytest' in (sys.modules or {})):
            test_id = os.environ.get('SMALL_RSS_TEST_ID')
            run_id = os.environ.get('SMALL_RSS_TEST_RUN_ID')
            if not test_id:
                # Fall back to PYTEST_CURRENT_TEST (strip phase suffix like " (call)")
                current = os.environ.get('PYTEST_CURRENT_TEST')
                if current:
                    test_id = current.split(' ')[0]
            # Stable per-test directory to avoid state leaking across tests (db.sqlite3, settings, etc.)
            if test_id:
                digest = hashlib.sha1(test_id.encode('utf-8', errors='ignore')).hexdigest()[:12]
                base = os.path.join(tempfile.gettempdir(), "SmallRSSReaderTests", run_id or f"pid-{os.getpid()}", digest)
            else:
                # Last-resort: isolate per-process
                base = os.path.join(tempfile.gettempdir(), "SmallRSSReaderTests", run_id or f"pid-{os.getpid()}", f"pid-{os.getpid()}")
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                pass
            return os.path.join(base, filename)
    except Exception:
        pass
    if getattr(sys, 'frozen', False):
        if sys.platform == "darwin":
            return os.path.join(Path.home(), "Library", "Application Support", "SmallRSSReader", filename)
        elif sys.platform == "win32":
            return os.path.join(os.getenv('APPDATA'), "SmallRSSReader", filename)
        else:
            return os.path.join(Path.home(), ".smallrssreader", filename)
    else:
        return os.path.join(os.path.abspath("."), filename)
