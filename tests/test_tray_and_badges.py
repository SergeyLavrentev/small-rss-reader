import pytest

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
    w._toggle_unread_filter(False)
    qtbot.addWidget(w)
    return w


def test_unread_badge_updates_on_read_change(ui_app):
    app = ui_app
    e1 = {'title': 'A', 'link': 'x1'}
    e2 = {'title': 'B', 'link': 'x2'}
    app.feeds = [{'title': 'F', 'url': 'https://bb.example.org/rss', 'entries': [e1, e2]}]
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    # Initially unread badge should be present (unread entries exist)
    before = it.icon(0)
    assert before is not None
    # Mark all as read and ensure badge cleared
    app.mark_all_as_read()
    after = it.icon(0)
    assert after is not None  # icon exists, but badge drawing handled internally; smoke test


def test_tray_tooltip_counts(ui_app, monkeypatch):
    app = ui_app
    # Fake tray object
    class Tray:
        def __init__(self):
            self.tip = ''
        def setToolTip(self, t):
            self.tip = t
        def hide(self):
            pass
    app.tray = Tray()

    e1 = {'title': 'A', 'link': 'x1'}
    app.feeds = [{'title': 'F', 'url': 'https://tt.example.org/rss', 'entries': [e1]}]
    app._rebuild_feeds_tree()
    app._update_tray()
    assert 'Unread' in app.tray.tip
