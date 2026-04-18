import pytest

from small_rss_reader import RSSReader
from PyQt5.QtCore import Qt


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_enter_opens_in_browser_smoke(ui_app, monkeypatch):
    app = ui_app
    opened = {'c': 0}
    import sys
    if sys.platform == 'darwin':
        import subprocess
        monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: opened.__setitem__('c', opened['c'] + 1))
    else:
        monkeypatch.setattr('webbrowser.open', lambda *_args, **_kwargs: opened.__setitem__('c', opened['c'] + 1))
    app.feeds = [{'title': 'F', 'url': 'https://kb.example.org/rss', 'entries': [{'title': 'A', 'link': 'http://x'}]}]
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    if it and not it.data(0, Qt.UserRole) and it.childCount() > 0:
        it = it.child(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    # Simulate pressing Enter by directly calling method
    app._open_current_article_in_browser()
    assert opened['c'] == 1


def test_macos_background_open_schedules_focus_restore(ui_app, monkeypatch):
    app = ui_app
    import rss_reader.app as appmod

    launched = {'count': 0}
    delays = []

    monkeypatch.setattr(appmod.sys, 'platform', 'darwin')
    monkeypatch.setattr(appmod.subprocess, 'Popen', lambda *a, **k: launched.__setitem__('count', launched['count'] + 1))
    monkeypatch.setattr(appmod.QTimer, 'singleShot', lambda delay, callback: delays.append(delay))

    assert app._open_link_in_browser('https://example.org/post', prefer_background=True) is True
    assert launched['count'] == 1
    assert delays == [0, 120, 260, 520]
