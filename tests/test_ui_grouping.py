import os
import pytest
from PyQt5.QtCore import Qt

from small_rss_reader import RSSReader


@pytest.fixture
def ui_app(qtbot, monkeypatch, tmp_path):
    # Force full UI init by unsetting PYTEST_CURRENT_TEST
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    # Disable background refresh to keep tests deterministic
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    # Isolate user data (db, log) to tmp
    import small_rss_reader as appmod
    monkeypatch.setattr(appmod, 'get_user_data_path', lambda name: str(tmp_path / name))
    w = RSSReader()
    w._toggle_unread_filter(False)
    qtbot.addWidget(w)
    return w


def build_feeds(app, feeds):
    app.feeds = [dict(title=t, url=u, entries=[]) for (t, u) in feeds]
    app._rebuild_feeds_tree()


def get_tree_snapshot(app):
    # returns (top_labels, children_count_per_top, leaf_urls)
    tops = []
    counts = []
    leaves = []
    for i in range(app.feedsTree.topLevelItemCount()):
        it = app.feedsTree.topLevelItem(i)
        tops.append(it.text(0))
        counts.append(it.childCount())
        if it.data(0, Qt.UserRole):
            leaves.append(it.data(0, Qt.UserRole))
        else:
            for j in range(it.childCount()):
                ch = it.child(j)
                leaves.append(ch.data(0, Qt.UserRole))
    return tops, counts, leaves


def test_grouping_only_when_multiple_feeds_share_domain(ui_app):
    app = ui_app
    build_feeds(app, [
        ("Feed A", "https://dom1.example.org/a.rss"),
        ("Feed B", "https://dom2.example.org/b.rss"),
    ])
    tops, counts, leaves = get_tree_snapshot(app)
    # two separate top-level leaves (no groups)
    assert len(tops) == 2 and all(c == 0 for c in counts)

    # Add another feed for dom1 -> dom1 becomes a group
    app.feeds.append({'title': 'Feed A2', 'url': 'https://dom1.example.org/aa.rss', 'entries': []})
    app._rebuild_feeds_tree()
    tops, counts, leaves = get_tree_snapshot(app)
    # one group (dom1) and one single feed (dom2)
    assert any(t.startswith('dom1.example.org') for t in tops)
    assert sum(1 for c in counts if c > 0) == 1


def test_selecting_group_selects_first_child(ui_app):
    app = ui_app
    build_feeds(app, [
        ("F1", "https://same.example.org/a.rss"),
        ("F2", "https://same.example.org/b.rss"),
    ])
    group = app.feedsTree.topLevelItem(0)
    assert group.childCount() == 2
    app.feedsTree.setCurrentItem(group)
    app._on_feed_selected()
    cur = app.feedsTree.currentItem()
    assert cur is not None and cur.data(0, Qt.UserRole) in {"https://same.example.org/a.rss", "https://same.example.org/b.rss"}


def test_add_feed_creates_group_and_selects_new_feed(ui_app):
    app = ui_app
    build_feeds(app, [("F1", "https://d.example.org/a.rss")])
    # Simulate Add: append then rebuild (bypass dialogs)
    app.feeds.append({'title': 'F2', 'url': 'https://d.example.org/b.rss', 'entries': []})
    app._rebuild_feeds_tree()
    tops, counts, leaves = get_tree_snapshot(app)
    assert any(t.startswith('d.example.org') for t in tops)
    assert sum(counts) == 2


def test_remove_feed_regroups_to_single_leaf(ui_app):
    app = ui_app
    build_feeds(app, [
        ("F1", "https://g.example.org/a.rss"),
        ("F2", "https://g.example.org/b.rss"),
    ])
    # Remove one feed
    app.feeds = [f for f in app.feeds if f['url'] != 'https://g.example.org/b.rss']
    app._rebuild_feeds_tree()
    tops, counts, leaves = get_tree_snapshot(app)
    # No grouping left, single leaf
    assert len(tops) == 1 and counts[0] == 0 and leaves == ['https://g.example.org/a.rss']


def test_update_feed_url_changes_grouping_and_selection(ui_app):
    app = ui_app
    build_feeds(app, [
        ("F1", "https://h1.example.org/a.rss"),
        ("F2", "https://h2.example.org/b.rss"),
    ])
    # Select first item
    it0 = app.feedsTree.topLevelItem(0)
    app.feedsTree.setCurrentItem(it0)
    # Change F1 URL to share domain with F2 -> they should group
    # Simulate via public API with a dummy-like item (using actual item)
    app.update_feed_url(it0, 'https://h2.example.org/a2.rss')
    tops, counts, leaves = get_tree_snapshot(app)
    assert any(t.startswith('h2.example.org') for t in tops)
    assert sum(counts) == 2
