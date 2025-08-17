import os
from PyQt5.QtCore import QUrl


def test_open_original_anchor_opens_external_qtextbrowser(qtbot, monkeypatch, tmp_path):
    # Force light content mode (QTextBrowser)
    monkeypatch.setenv('SMALL_RSS_TESTS', '1')
    # Ensure full UI is built (app checks PYTEST_CURRENT_TEST to skip UI)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    # Avoid auto-refresh in tests
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    # Isolate user data path
    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', lambda name: str(tmp_path / name))

    from rss_reader.app import RSSReader
    app = RSSReader()
    qtbot.addWidget(app)

    # Seed a single feed and entry with a link
    link = 'https://example.com/post1'
    app.feeds = [{
        'title': 'Feed A',
        'url': 'https://a.example/rss',
        'entries': [{
            'title': 'Hello',
            'link': link,
            # minimal date fields to avoid datetime.min sorting edge-cases
            'published_parsed': (2024, 1, 1, 0, 0, 0, 0, 1, 0),
        }],
    }]

    # Build the feeds tree and select the feed
    app._rebuild_feeds_tree()
    feed_item = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(feed_item)
    app._on_feed_selected()

    # Select first article and ensure content is shown (includes 'Open original' link)
    first = app.articlesTree.topLevelItem(0)
    app.articlesTree.setCurrentItem(first)
    app._on_article_selected()

    # Monkeypatch QDesktopServices.openUrl to capture calls
    from PyQt5.QtGui import QDesktopServices
    called = {'url': None}
    def _open(url):
        called['url'] = url
        return True
    monkeypatch.setattr(QDesktopServices, 'openUrl', _open)

    # Simulate clicking anchor: emit anchorClicked on QTextBrowser
    # Note: QTextBrowser emits anchorClicked(QUrl) on link click; our app connects it.
    app.webView.anchorClicked.emit(QUrl(link))
    qtbot.wait(10)

    assert called['url'] is not None, 'Expected QDesktopServices.openUrl to be called'
    assert str(called['url'].toString()) == link
