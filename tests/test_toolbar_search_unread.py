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


def test_unread_toggle_persists_and_filters(ui_app, monkeypatch):
    app = ui_app
    # Prepare entries: first read, second unread
    e1 = {'title': 'A', 'link': 'x1'}
    e2 = {'title': 'B', 'link': 'x2'}
    app.feeds = [{'title': 'F', 'url': 'https://s.example.org/rss', 'entries': [e1, e2]}]
    # mark first as read
    app.read_articles.add(app.get_article_id(e1))
    app._rebuild_feeds_tree()
    app.feedsTree.setCurrentItem(app.feedsTree.topLevelItem(0))
    app._on_feed_selected()

    # Initially both columns exist but both rows present
    assert app.articlesTree.topLevelItemCount() == 2
    # Toggle unread-only
    app._toggle_unread_filter(True)
    assert app.articlesTree.topLevelItemCount() == 1
    # Toggle back
    app._toggle_unread_filter(False)
    assert app.articlesTree.topLevelItemCount() == 2


def test_search_filters_in_title_summary_link(ui_app):
    app = ui_app
    e1 = {'title': 'Alpha', 'link': 'link1', 'summary': 'foo'}
    e2 = {'title': 'Beta', 'link': 'search-me', 'summary': 'bar'}
    e3 = {'title': 'Gamma', 'link': 'l3', 'summary': 'baz has term'}
    app.feeds = [{'title': 'F', 'url': 'https://ss.example.org/rss', 'entries': [e1, e2, e3]}]
    app._rebuild_feeds_tree()
    app.feedsTree.setCurrentItem(app.feedsTree.topLevelItem(0))
    app._on_feed_selected()

    # No filter
    assert app.articlesTree.topLevelItemCount() == 3
    app._on_search_changed('search')
    assert app.articlesTree.topLevelItemCount() == 1
    app._on_search_changed('term')
    assert app.articlesTree.topLevelItemCount() == 1
    app._on_search_changed('ALPHA')
    assert app.articlesTree.topLevelItemCount() == 1
