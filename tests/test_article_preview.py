import pytest

from small_rss_reader import RSSReader


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