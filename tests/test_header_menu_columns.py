import pytest
from PyQt5.QtCore import Qt

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
    assert hdr == ['Title', 'Date', 'Year', 'IMDb', 'Director', 'Actors', 'Genre', 'Runtime', 'Rated']
    # Persist custom visibility/order/sort for the feed
    app._persist_column_prefs(
        'https://cols.example.org/rss',
        visible=['Title', 'Date', 'IMDb'],
        order=['IMDb', 'Title', 'Date'],
        sort_column='Title',
        sort_order=int(Qt.AscendingOrder),
    )
    app._on_feed_selected()
    hdr2 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    # Custom order is respected (other columns follow)
    assert hdr2[:3] == ['IMDb', 'Title', 'Date']
    # Hidden column is actually hidden
    year_idx = hdr2.index('Year')
    assert app.articlesTree.isColumnHidden(year_idx) is True
    # Saved sort applied
    header = app.articlesTree.header()
    assert header.sortIndicatorSection() == hdr2.index('Title')
    assert header.sortIndicatorOrder() == Qt.AscendingOrder


def test_group_column_prefs_apply_to_feeds(ui_app):
    app = ui_app
    feed_url = 'https://cols.example.org/rss'
    app.feeds = [{'title': 'F', 'url': feed_url, 'entries': [{'title': 'Inception'}]}]
    app.group_settings[feed_url] = {'omdb_enabled': False}
    app._persist_column_prefs(feed_url, order=['Date', 'Title'], visible=['Date', 'Title'], scope='group')
    app._rebuild_feeds_tree()
    it = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    hdr = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert hdr[:2] == ['Date', 'Title']
    assert app.articlesTree.isColumnHidden(hdr.index('Date')) is False
    assert app.articlesTree.isColumnHidden(hdr.index('Title')) is False
