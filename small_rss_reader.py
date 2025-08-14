#!/usr/bin/env python3
"""Compatibility shim for Small RSS Reader.

Keeps `from small_rss_reader import RSSReader` working while the
implementation lives in `rss_reader.app`. Also exposes
`get_user_data_path` for tests to monkeypatch.
"""

import sys
from PyQt5.QtWidgets import QApplication

from rss_reader.app import (
    RSSReader as RSSReader,
    get_user_data_path as _app_get_user_data_path,
)


def get_user_data_path(filename: str) -> str:
    return _app_get_user_data_path(filename)


def main() -> int:
    app = QApplication(sys.argv)
    w = RSSReader()
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
