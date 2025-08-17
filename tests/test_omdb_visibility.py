import pytest

from small_rss_reader import RSSReader
from PyQt5.QtCore import Qt


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


def build_feed_with_entries(app, url, titles):
    app.feeds = [{'title': 'F', 'url': url, 'entries': [{'title': t, 'link': f'https://x/{i}'} for i, t in enumerate(titles)]}]
    app._rebuild_feeds_tree()
    # Select the single feed
    it = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()


def test_omdb_columns_hidden_by_default(ui_app):
    app = ui_app
    build_feed_with_entries(app, 'https://k.example.org/rss', ['Inception'])
    headers = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert 'Year' not in headers


def test_enable_omdb_per_feed_shows_columns_immediately(ui_app):
    app = ui_app
    build_feed_with_entries(app, 'https://k2.example.org/rss', ['Inception'])
    # Toggle per-feed OMDb
    app.group_settings['https://k2.example.org/rss'] = {'omdb_enabled': True}
    # Repopulate current feed
    app._on_feed_selected()
    headers = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert 'Year' in headers


def test_disable_omdb_per_feed_hides_columns_immediately(ui_app):
    app = ui_app
    build_feed_with_entries(app, 'https://k3.example.org/rss', ['Inception'])
    app.group_settings['https://k3.example.org/rss'] = {'omdb_enabled': True}
    # select the leaf feed item (handle grouping)
    it = app.feedsTree.topLevelItem(0)
    if it and not it.data(0, Qt.UserRole) and it.childCount() > 0:
        it = it.child(0)
    app.feedsTree.setCurrentItem(it)
    app._on_feed_selected()
    # Now disable
    app.group_settings['https://k3.example.org/rss'] = {'omdb_enabled': False}
    app._on_feed_selected()
    headers = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert 'Year' not in headers


def test_enable_omdb_on_group_applies_to_children(ui_app):
    app = ui_app
    app.feeds = [
        {'title': 'A', 'url': 'https://gg.example.org/a.rss', 'entries': [{'title': 'Inception'}]},
        {'title': 'B', 'url': 'https://gg.example.org/b.rss', 'entries': [{'title': 'Matrix'}]},
    ]
    app._rebuild_feeds_tree()
    # Set domain-level flag only
    app.group_settings['gg.example.org'] = {'omdb_enabled': True}
    # Selecting children should inherit enabled
    # child 0
    ch0 = app.feedsTree.topLevelItem(0).child(0)
    app.feedsTree.setCurrentItem(ch0)
    app._on_feed_selected()
    headers0 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    # child 1
    ch1 = app.feedsTree.topLevelItem(0).child(1)
    app.feedsTree.setCurrentItem(ch1)
    app._on_feed_selected()
    headers1 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert 'Year' in headers0 and 'Year' in headers1


def test_per_feed_overrides_domain_setting(ui_app):
    app = ui_app
    app.feeds = [
        {'title': 'A', 'url': 'https://dd.example.org/a.rss', 'entries': [{'title': 'Inception'}]},
        {'title': 'B', 'url': 'https://dd.example.org/b.rss', 'entries': [{'title': 'Matrix'}]},
    ]
    app._rebuild_feeds_tree()
    # Enable at domain and disable for one feed
    app.group_settings['dd.example.org'] = {'omdb_enabled': True}
    app.group_settings['https://dd.example.org/b.rss'] = {'omdb_enabled': False}
    # child A should see IMDb
    top = app.feedsTree.topLevelItem(0)
    ch0 = top.child(0) if (top.childCount() > 0 or not top.data(0, Qt.UserRole)) else top
    app.feedsTree.setCurrentItem(ch0)
    app._on_feed_selected()
    h0 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    # child B should not
    ch1 = top.child(1) if (top.childCount() > 1 or not top.data(0, Qt.UserRole)) else top
    app.feedsTree.setCurrentItem(ch1)
    app._on_feed_selected()
    h1 = [app.articlesTree.headerItem().text(i) for i in range(app.articlesTree.columnCount())]
    assert ('Year' in h0) and ('Year' not in h1)
