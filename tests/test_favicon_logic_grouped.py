import pytest

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    w = RSSReader()
    qtbot.addWidget(w)
    return w


def test_on_icon_fetched_updates_children_in_group(ui_app, tmp_path):
    app = ui_app
    app.feeds = [
        {'title': 'A', 'url': 'https://icn.example.org/a', 'entries': []},
        {'title': 'B', 'url': 'https://icn.example.org/b', 'entries': []},
    ]
    app._rebuild_feeds_tree()
    # Build a tiny valid PNG
    from PyQt5.QtGui import QPixmap
    p = tmp_path / 'ico.png'
    pm = QPixmap(16, 16)
    pm.fill()
    pm.save(str(p), 'PNG')
    data = p.read_bytes()
    app.on_icon_fetched('icn.example.org', data)
    # Both children should have base icon set in UserRole+1
    group = app.feedsTree.topLevelItem(0)
    assert group.child(0).data(0, 257) is not None
    assert group.child(1).data(0, 257) is not None
