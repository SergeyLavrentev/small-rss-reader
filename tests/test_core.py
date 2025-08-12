import pytest

from small_rss_reader import RSSReader


class DummyStatusBar:
    def showMessage(self, *_args, **_kwargs):
        pass


class DummyItem:
    def __init__(self, url):
        self._data = url

    def data(self, _col, _role):
        return self._data

    def setData(self, _col, _role, val):
        self._data = val


@pytest.fixture
def app(qtbot):
    w = RSSReader()
    w.statusBar = lambda: DummyStatusBar()
    return w


def test_get_article_id_is_stable(app):
    entry = {
        'id': 'abc',
        'link': 'https://example.org/a',
        'title': 'Hello',
        'published': '2024-01-01'
    }
    a = app.get_article_id(entry)
    b = app.get_article_id(entry.copy())
    assert a == b and isinstance(a, str) and len(a) == 32


def test_prune_old_entries_removes_older_than_max_days(app):
    from datetime import datetime, timedelta

    def to_struct(dt):
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0, 0, -1)

    old_date = datetime.now() - timedelta(days=app.max_days + 10)
    recent_date = datetime.now() - timedelta(days=1)

    app.feeds = [{
        'title': 'T',
        'url': 'https://example.org/feed',
        'entries': [
            {'title': 'old', 'published_parsed': to_struct(old_date)},
            {'title': 'recent', 'published_parsed': to_struct(recent_date)},
        ]
    }]
    app.prune_old_entries()
    entries = app.feeds[0]['entries']
    assert len(entries) == 1 and entries[0]['title'] == 'recent'


def test_update_feed_url_validates_and_updates(app, qtbot):
    feed = {'title': 'T', 'url': 'https://old.example.org/feed', 'entries': []}
    app.feeds = [feed]
    item = DummyItem(feed['url'])

    assert app.update_feed_url(item, feed['url']) is True

    app.feeds.append({'title': 'Other', 'url': 'https://new.example.org/feed'})
    assert app.update_feed_url(item, 'https://new.example.org/feed') is False

    assert app.update_feed_url(item, 'https://another.example.org/feed') is True
    assert feed['url'] == 'https://another.example.org/feed'
