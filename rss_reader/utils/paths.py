import os
import sys
from pathlib import Path


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
        # project root (rss_reader/utils -> ../..)
        base_path = os.path.abspath(os.path.join(base_path, os.pardir, os.pardir))
    return os.path.join(base_path, relative_path)


def get_user_data_path(filename: str) -> str:
    if getattr(sys, 'frozen', False):
        if sys.platform == "darwin":
            return os.path.join(Path.home(), "Library", "Application Support", "SmallRSSReader", filename)
        elif sys.platform == "win32":
            return os.path.join(os.getenv('APPDATA'), "SmallRSSReader", filename)
        else:
            return os.path.join(Path.home(), ".smallrssreader", filename)
    else:
        return os.path.join(os.path.abspath("."), filename)
