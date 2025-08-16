import pytest

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_omdb_enabled_shows_extended_omdb_columns(ui_app):
    app = ui_app
    app.feeds = [{'title': 'F', 'url': 'https://cols.example.org/rss', 'entries': [{'title': 'Inception'}]}]
    app.group_settings['https://cols.example.org/rss'] = {'omdb_enabled': True}
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    # Expanded OMDb columns
    hdr = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert hdr == ['Title', 'Date', 'Year', 'Director', 'Actors', 'Genre', 'Runtime', 'Rated']
    # Попытки изменить набор колонок игнорируются
    app.omdb_columns_by_feed['https://cols.example.org/rss'] = ['Title', 'Date', 'Year']
    app._on_feed_selected()
    hdr2 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert hdr2 == ['Title', 'Date', 'Year', 'Director', 'Actors', 'Genre', 'Runtime', 'Rated']
