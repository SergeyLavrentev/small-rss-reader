import pytest

from small_rss_reader import RSSReader
from rss_reader.ui.preview import extract_reader_content


@pytest.fixture
def ui_app(qtbot, monkeypatch, tmp_path):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.delenv('SMALL_RSS_TESTS', raising=False)
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', lambda name: str(tmp_path / name))
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_build_article_html_includes_preview_image_from_feed(ui_app):
    html, base_url = ui_app._build_article_html({
        'title': 'Previewed article',
        'link': 'https://example.org/articles/1',
        'summary': 'Only short text from feed',
        'media_thumbnail': [{'url': 'https://cdn.example.org/preview.jpg'}],
    })

    assert base_url == 'https://example.org/articles/1'
    assert 'https://cdn.example.org/preview.jpg' in html
    assert '<img' in html


def test_page_fetched_refreshes_current_article(ui_app, monkeypatch):
    entry = {'title': 'A1', 'link': 'https://example.org/articles/1'}
    aid = ui_app.get_article_id(entry)
    ui_app._page_fetching_aids.add(aid)
    calls = []

    monkeypatch.setattr(ui_app, '_current_entry', lambda: entry)
    monkeypatch.setattr(ui_app, '_show_article', lambda current: calls.append(current))

    ui_app._on_page_fetched(aid, entry['link'], '<html>Loaded later</html>')

    assert ui_app.article_html_cache[aid] == '<html>Loaded later</html>'
    assert aid not in ui_app._page_fetching_aids
    assert calls == [entry]


def test_page_fetch_failed_clears_inflight_marker(ui_app):
    aid = 'article-id-1'
    ui_app._page_fetching_aids.add(aid)

    ui_app._on_page_fetch_failed(aid)

    assert aid not in ui_app._page_fetching_aids


def test_populate_articles_prefetches_only_small_window(ui_app, monkeypatch):
    entries = [
        {'title': f'A{i}', 'link': f'https://example.org/articles/{i}'}
        for i in range(8)
    ]
    started = []

    monkeypatch.setattr(ui_app, '_start_preview_runnable', lambda runnable: started.append(runnable))

    ui_app._populate_articles('https://example.org/rss', entries)

    assert len(started) == ui_app._page_prefetch_window
    assert [r.aid for r in started] == [ui_app.get_article_id(e) for e in entries[:ui_app._page_prefetch_window]]


def test_populate_articles_skips_prefetch_when_inline_content_exists(ui_app, monkeypatch):
    entries = [
        {
            'title': 'Inline summary only',
            'link': 'https://example.org/articles/1',
            'summary': 'Short inline content from feed',
        },
        {
            'title': 'Needs full page',
            'link': 'https://example.org/articles/2',
        },
    ]
    started = []

    monkeypatch.setattr(ui_app, '_start_preview_runnable', lambda runnable: started.append(runnable))

    ui_app._populate_articles('https://example.org/rss', entries)

    assert len(started) == 1
    assert started[0].aid == ui_app.get_article_id(entries[1])


def test_article_html_cache_is_bounded_lru(ui_app):
    ui_app._article_html_cache_limit = 2

    ui_app._cache_article_html('a', '<html>A</html>')
    ui_app._cache_article_html('b', '<html>B</html>')
    assert ui_app._get_cached_article_html('a') == '<html>A</html>'

    ui_app._cache_article_html('c', '<html>C</html>')

    assert list(ui_app.article_html_cache.keys()) == ['a', 'c']


def test_build_article_html_sanitizes_remote_fragment_and_uses_safe_preview_image(ui_app):
    html, _base_url = ui_app._build_article_html({
        'title': 'Unsafe fragment',
        'link': 'https://example.org/articles/1',
        'summary': (
            '<p onclick="boom()">Hello</p>'
            '<script>alert(1)</script>'
            '<iframe src="https://evil.example/frame"></iframe>'
            '<img src="javascript:alert(1)" onerror="boom()">'
            '<a href="javascript:alert(2)">bad link</a>'
        ),
        'media_thumbnail': [{'url': 'https://cdn.example.org/preview.jpg'}],
    })

    lower = html.lower()
    assert '<script' not in lower
    assert '<iframe' not in lower
    assert 'onclick=' not in lower
    assert 'onerror=' not in lower
    assert 'javascript:' not in lower
    assert 'https://cdn.example.org/preview.jpg' in html


def test_extract_reader_content_sanitizes_scripts_iframes_and_js_urls():
    html = extract_reader_content(
        (
            '<html><body>'
            '<article class="tm-article-presenter__content">'
            '<h1>Reader title</h1>'
            '<div class="article-formatted-body">'
            '<p onclick="boom()">Reader body</p>'
            '<script>alert(1)</script>'
            '<iframe src="https://evil.example/frame"></iframe>'
            '<a href="javascript:alert(2)">bad link</a>'
            '<img src="/img/preview.jpg" onerror="boom()">'
            '</div>'
            '</article>'
            '</body></html>'
        ),
        'https://example.org/articles/reader',
        'Reader title',
    )

    lower = html.lower()
    assert '<script' not in lower
    assert '<iframe' not in lower
    assert 'onclick=' not in lower
    assert 'onerror=' not in lower
    assert 'javascript:' not in lower
    assert 'https://example.org/img/preview.jpg' in html