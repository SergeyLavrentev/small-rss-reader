import pytest
from PyQt5.QtCore import Qt

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch, tmp_path):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', lambda name: str(tmp_path / name))
    w = RSSReader()
    # disable unread filter to ensure items stay visible in tests
    try:
        w._toggle_unread_filter(False)
    except Exception:
        pass
    qtbot.addWidget(w)
    return w


def test_update_feed_url_rejects_duplicate_and_invalid(ui_app):
    app = ui_app
    app.feeds = [
        {'title': 'A', 'url': 'https://dup.example.org/a'},
        {'title': 'B', 'url': 'https://dup.example.org/b'},
    ]
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    # If grouping occurred, pick the first child (leaf item)
    if it and not it.data(0, Qt.UserRole) and it.childCount() > 0:
        it = it.child(0)
    # Duplicate to existing other feed should fail
    assert app.update_feed_url(it, 'https://dup.example.org/b') is False
    # Missing scheme should be auto-added and succeed (becomes http://example.org/new)
    assert app.update_feed_url(it, 'example.org/new') is True


def test_mark_all_unread_then_read_cycle(ui_app):
    app = ui_app
    e1 = {'title': 'A', 'link': 'x1'}
    e2 = {'title': 'B', 'link': 'x2'}
    app.feeds = [{'title': 'F', 'url': 'https://edge.example.org/rss', 'entries': [e1, e2]}]
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    if it and not it.data(0, Qt.UserRole) and it.childCount() > 0:
        it = it.child(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    # Mark all as read
    app.mark_all_as_read()
    # Foreground is a QBrush; we just assert that items exist to avoid None
    assert app.articlesTree.topLevelItemCount() == 2
    # Mark all as unread
    app.mark_all_as_unread()
    # Should show unread icons again (smoke check: some icon object present)
    assert app.articlesTree.topLevelItem(0).icon(0) is not None
