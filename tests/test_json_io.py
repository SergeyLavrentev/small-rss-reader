from rss_reader.app import RSSReader
import json


def test_export_import_json_roundtrip(tmp_path):
    w = RSSReader()
    # seed feeds and column widths
    w.feeds = [
        {"title": "Feed A", "url": "https://a.example/rss", "entries": [{"title": "t", "link": "https://a/1"}]},
        {"title": "Feed B", "url": "https://b.example/rss", "entries": []},
    ]
    w.column_widths = {"https://a.example/rss": [150, 120], "https://b.example/rss": [200, 100]}
    w.column_configs = {"https://a.example/rss": {"visible": ["Title", "Date"], "order": ["Date", "Title"], "sort_column": "Date", "sort_order": 1}}

    out_path = tmp_path / "feeds.json"
    w.export_json_to_path(str(out_path))

    # reset state, then import
    w.feeds = []
    w.column_widths = {}
    w.column_configs = {}
    added = w.import_json_from_path(str(out_path))

    assert added == 2
    urls = {f["url"] for f in w.feeds}
    assert "https://a.example/rss" in urls and "https://b.example/rss" in urls
    assert w.column_widths.get("https://a.example/rss") == [150, 120]
    assert w.column_configs.get("https://a.example/rss", {}).get("order") == ["Date", "Title"]

    # importing same file again shouldn't duplicate feeds
    added2 = w.import_json_from_path(str(out_path))
    assert added2 == 0
