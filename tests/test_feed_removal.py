import pytest
from PyQt5.QtCore import Qt

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch, tmp_path):
    # Force debug to avoid WebEngine usage in tests where applicable
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    w = RSSReader()
    qtbot.addWidget(w)
    # Use an in-memory storage by redirecting DB path if possible
    try:
        # Replace storage with temp db to isolate
        from storage import Storage
        w.storage = Storage(str(tmp_path / 'db.sqlite3'))
    except Exception:
        pass
    return w


def _first_leaf_item(app: RSSReader):
    it = app.feedsTree.topLevelItem(0)
    if it is None:
        return None
    url = it.data(0, Qt.UserRole)
    if url:
        return it
    if it.childCount() > 0:
        return it.child(0)
    return None


def test_remove_single_feed(ui_app, qtbot):
    app = ui_app
    url = 'https://one.example.org/rss'
    app.feeds = [{'title': 'One', 'url': url, 'entries': [{'title': 'A', 'link': 'http://a'}]}]
    app._rebuild_feeds_tree()
    item = _first_leaf_item(app)
    app.feedsTree.setCurrentItem(item)

    # Auto-confirm dialog: monkeypatch QMessageBox.question to return Yes
    from PyQt5.QtWidgets import QMessageBox
    qtbot.wait(10)
    orig = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        app.remove_selected_feed()
    finally:
        QMessageBox.question = orig

    assert all(f.get('url') != url for f in app.feeds)
    # Ensure tree reflects removal
    it = _first_leaf_item(app)
    if it:
        assert it.data(0, Qt.UserRole) != url


def test_remove_group_and_feeds(ui_app, qtbot):
    app = ui_app
    domain = 'group.example.org'
    feeds = [
        {'title': 'G1', 'url': f'https://{domain}/rss1', 'entries': []},
        {'title': 'G2', 'url': f'https://{domain}/rss2', 'entries': []},
        {'title': 'Other', 'url': 'https://other.org/rss', 'entries': []},
    ]
    app.feeds = feeds
    app._rebuild_feeds_tree()

    # Confirm dialog auto-Yes
    from PyQt5.QtWidgets import QMessageBox
    orig = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        app.remove_group_and_feeds(domain)
    finally:
        QMessageBox.question = orig

    # All domain feeds gone, other remains
    assert all((f.get('url') or '').startswith('https://other.org') for f in app.feeds)
    # UI should have at least the other feed
    it = _first_leaf_item(app)
    assert it is not None
    assert it.data(0, Qt.UserRole).startswith('https://other.org')
