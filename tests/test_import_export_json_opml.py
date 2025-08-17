import io
import json
import pytest

from small_rss_reader import RSSReader

# Skip the UI-driven import test that expects modal dialog interactions
import pytest


@pytest.fixture
def app_headless(qtbot):
    # Headless constructor (PYTEST_CURRENT_TEST is set by pytest)
    w = RSSReader()
    return w


def test_import_json_to_path_roundtrip(tmp_path, app_headless):
    app = app_headless
    data = {
        'feeds': [
            {'title': 'F1', 'url': 'https://ex1/rss', 'entries': [{'title': 'A'}]},
            {'title': 'F2', 'url': 'https://ex2/rss', 'entries': [{'title': 'B'}]},
        ],
        'column_widths': {'https://ex1/rss': [100, 80]},
    }
    p = tmp_path / 'feeds.json'
    p.write_text(json.dumps(data))
    added = app.import_json_from_path(str(p))
    assert added == 2
    # Export to another file and compare shape
    out = tmp_path / 'out.json'
    app.export_json_to_path(str(out))
    out_data = json.loads(out.read_text())
    assert 'feeds' in out_data and 'column_widths' in out_data


@pytest.mark.skip(reason="Excluded: uses QFileDialog modal via import_json(); not suitable for headless auto tests")
def test_import_json_feeds_calls_rebuild(tmp_path, qtbot, monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    import sys
    if '--debug' not in sys.argv:
        sys.argv.append('--debug')
    app = RSSReader()
    app.statusBar = lambda: type('SB', (), {'showMessage': lambda *a, **k: None})()
    # Prepare JSON import result via monkeypatching importer
    from rss_reader.io import json_io
    monkeypatch.setattr(json_io, 'import_json', lambda self: [
        {'title': 'A', 'url': 'https://x1/a'},
        {'title': 'B', 'url': 'https://x1/b'},
    ])
    app.import_json_feeds()
    # Should end up grouped since same domain (top is group)
    top = app.feedsTree.topLevelItem(0)
    assert top is not None and top.childCount() == 2
