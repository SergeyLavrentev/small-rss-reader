import pytest
from PyQt5.QtCore import Qt


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    # Full UI mode but use lightweight widgets (no WebEngine)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setenv('SMALL_RSS_TESTS', '1')
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    from small_rss_reader import RSSReader
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def _prepare_feed(app):
    app.feeds = [{
        'title': 'Feed',
        'url': 'https://kb.example.org/rss',
        'entries': [
            {'title': 'A1', 'link': 'http://x1'},
            {'title': 'A2', 'link': 'http://x2'},
        ],
    }]
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    if it and not it.data(0, Qt.UserRole) and it.childCount() > 0:
        it = it.child(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()


def test_mark_unread_context_menu_targets_clicked_item(ui_app, qtbot, monkeypatch):
    app = ui_app
    _prepare_feed(app)

    # Ensure layout is realized so visualItemRect/itemAt work reliably.
    app.resize(1000, 700)
    app.show()
    qtbot.wait(20)

    # Select second article and mark it as read (normally happens on selection/show)
    item = app.articlesTree.topLevelItem(1)
    assert item is not None
    app.articlesTree.setCurrentItem(item)
    entry = item.data(0, Qt.UserRole) or {}
    aid = app.get_article_id(entry)

    app._show_article(entry)
    assert aid in app.read_articles

    # Force context menu to "choose" Mark as Unread without real UI interaction.
    def fake_exec(menu, _global_pos):
        for act in menu.actions():
            if act.text() == 'Mark as Unread':
                return act
        return None

    monkeypatch.setattr(app, '_exec_menu', fake_exec)

    # Call handler as if right-click happened on that item
    rect = app.articlesTree.visualItemRect(item)
    pos = rect.center()

    # Sanity: position should resolve back to the same item (viewport coords)
    resolved = app.articlesTree.itemAt(pos)
    assert resolved is item

    app._on_articles_context_menu(pos)

    assert aid not in app.read_articles
