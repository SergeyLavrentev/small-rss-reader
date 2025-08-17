import pytest
from PyQt5.QtCore import Qt


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    # Use UI mode but force QuickPreview to use QTextBrowser (no WebEngine in tests)
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


def test_quick_preview_space_opens_and_esc_closes(ui_app, qtbot, monkeypatch):
    app = ui_app
    _prepare_feed(app)

    # Stub requests.get so QuickPreview (QTextBrowser mode) loads predictable content
    calls = []

    class Resp:
        def __init__(self, text):
            self.text = text

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        return Resp('PAGE:' + url)

    monkeypatch.setitem(__import__('sys').modules, 'requests', type('R', (), {'get': staticmethod(fake_get)}))

    # Open preview
    app._toggle_quick_preview()
    assert app._preview is not None and app._preview.isVisible()

    # Content should be loaded for current article
    view = app._preview.view
    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'PAGE:http://x1' in view.toPlainText(), timeout=2000)

    # Esc closes
    qtbot.keyPress(app._preview, Qt.Key_Escape)
    qtbot.waitUntil(lambda: app._preview is None, timeout=2000)


def test_quick_preview_up_down_navigates_and_updates(ui_app, qtbot, monkeypatch):
    app = ui_app
    _prepare_feed(app)

    # Provide per-URL texts
    class Resp:
        def __init__(self, text):
            self.text = text

    texts = {
        'http://x1': 'P1',
        'http://x2': 'P2',
    }
    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        return Resp(texts.get(url, 'NONE'))

    monkeypatch.setitem(__import__('sys').modules, 'requests', type('R', (), {'get': staticmethod(fake_get)}))

    # Open preview on A1
    app._toggle_quick_preview()
    assert app._preview is not None and app._preview.isVisible()

    view = app._preview.view
    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'P1' in view.toPlainText(), timeout=2000)

    # Press Down -> select A2 and reload preview
    qtbot.keyPress(app._preview, Qt.Key_Down)

    # Selection moved to second item
    def _current_index():
        idx = -1
        for i in range(app.articlesTree.topLevelItemCount()):
            if app.articlesTree.topLevelItem(i) is app.articlesTree.currentItem():
                idx = i
                break
        return idx

    qtbot.waitUntil(lambda: _current_index() == 1, timeout=2000)

    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'P2' in view.toPlainText(), timeout=2000)

    # Space closes (and should not change selection)
    qtbot.keyPress(app._preview, Qt.Key_Space)
    prev_index = _current_index()
    qtbot.waitUntil(lambda: app._preview is None, timeout=2000)
    assert _current_index() == prev_index


def test_quick_preview_arrows_do_not_scroll_content(ui_app, qtbot, monkeypatch):
    app = ui_app
    _prepare_feed(app)

    class Resp:
        def __init__(self, text):
            self.text = text

    # Long HTML to ensure scroll bar appears
    long_html = "P1\n" + ("<p>line</p>\n" * 2000)
    long_html2 = "P2\n" + ("<p>row</p>\n" * 2000)

    def fake_get(url, *args, **kwargs):
        if url.endswith('x1'):
            return Resp(long_html)
        return Resp(long_html2)

    monkeypatch.setitem(__import__('sys').modules, 'requests', type('R', (), {'get': staticmethod(fake_get)}))

    app._toggle_quick_preview()
    assert app._preview is not None and app._preview.isVisible()
    view = app._preview.view

    # Wait until content loaded and scroll bar available
    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'P1' in view.toPlainText(), timeout=3000)
    sb = view.verticalScrollBar()
    qtbot.waitUntil(lambda: sb.maximum() > 0, timeout=3000)
    assert sb.value() == 0

    # Press Down on preview window: navigate to next article, should still be at top (no scroll inside page)
    qtbot.keyPress(app._preview, Qt.Key_Down)
    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'P2' in view.toPlainText(), timeout=3000)
    sb2 = view.verticalScrollBar()
    qtbot.waitUntil(lambda: sb2.maximum() > 0, timeout=3000)
    assert sb2.value() == 0

    # Press Up on the inner view directly: navigate back and still no scroll
    qtbot.keyPress(view, Qt.Key_Up)
    if hasattr(view, 'toPlainText'):
        qtbot.waitUntil(lambda: 'P1' in view.toPlainText(), timeout=3000)
    sb3 = view.verticalScrollBar()
    qtbot.waitUntil(lambda: sb3.maximum() > 0, timeout=3000)
    assert sb3.value() == 0
