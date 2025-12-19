import pytest
from PyQt5.QtCore import Qt

from small_rss_reader import RSSReader
from rss_reader.app import FAVORITES_FEED_URL


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    # Force full UI path (articlesTree/feedsTree exist)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setenv('SMALL_RSS_TESTS', '1')
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def _find_favorites_item(app: RSSReader):
    for i in range(app.feedsTree.topLevelItemCount()):
        it = app.feedsTree.topLevelItem(i)
        if it and it.data(0, Qt.UserRole) == FAVORITES_FEED_URL:
            return it
    return None


def test_favorites_node_shows_only_favorites(ui_app):
    app = ui_app

    e1 = {"title": "A", "link": "https://example.org/a", "published": "2024-01-01"}
    e2 = {"title": "B", "link": "https://example.org/b", "published": "2024-01-02"}
    feed_url = "https://feed.example.org/rss"

    app.feeds = [{"title": "F", "url": feed_url, "entries": [e1, e2]}]
    app.favorite_articles = {app.get_article_id(e2)}

    app._rebuild_feeds_tree()

    fav = _find_favorites_item(app)
    assert fav is not None

    app.feedsTree.setCurrentItem(fav)
    app._on_feed_selected()

    assert app.articlesTree.topLevelItemCount() == 1

    # Validate title has a star and contains the favorited entry title.
    hdr = app.articlesTree.headerItem()
    title_col = 0
    for i in range(app.articlesTree.columnCount()):
        if hdr.text(i) == "Title":
            title_col = i
            break

    it = app.articlesTree.topLevelItem(0)
    assert it is not None
    assert it.text(title_col) == "B"
    assert not it.icon(0).isNull()
