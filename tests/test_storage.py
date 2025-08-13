import os
import json
import hashlib
from datetime import datetime

import pytest

from storage import Storage, compute_article_id


def make_entry(title="Hello", link="https://example.org/a", published="2024-01-01"):
    return {
        "title": title,
        "link": link,
        "published": published,
    }


def test_compute_article_id_stable():
    e = make_entry()
    a = compute_article_id(e)
    b = compute_article_id(e.copy())
    assert isinstance(a, str) and len(a) == 32 and a == b


def test_storage_roundtrip_feeds_and_entries(tmp_path):
    db = tmp_path / "db.sqlite3"
    s = Storage(str(db))

    # Upsert feed and replace entries
    url = "https://feed.example.org/rss"
    s.upsert_feed("Feed", url)
    entries = [make_entry(title="A", link="https://site/a"), make_entry(title="B", link="https://site/b")]
    s.replace_entries(url, entries)

    feeds = s.get_all_feeds()
    assert len(feeds) == 1
    assert feeds[0]["url"] == url
    assert len(feeds[0]["entries"]) == 2


def test_storage_read_articles_roundtrip(tmp_path):
    s = Storage(str(tmp_path / "db.sqlite3"))
    ids = [hashlib.md5(f"id{i}".encode()).hexdigest() for i in range(3)]
    s.save_read_articles(ids)
    assert set(s.load_read_articles()) == set(ids)


def test_storage_group_settings_roundtrip(tmp_path):
    s = Storage(str(tmp_path / "db.sqlite3"))
    gs = {
        "example.org": {"omdb_enabled": True, "notifications_enabled": False},
        "other.org": {"omdb_enabled": False, "notifications_enabled": True},
    }
    s.save_group_settings(gs)
    loaded = s.load_group_settings()
    assert loaded == gs


def test_storage_column_widths_roundtrip(tmp_path):
    s = Storage(str(tmp_path / "db.sqlite3"))
    cw = {
        "https://feed.example.org/rss": [150, 120, 80],
        "https://another.example.org/rss": [200, 100],
    }
    s.save_column_widths(cw)
    loaded = s.load_column_widths()
    assert loaded == cw


def test_storage_movie_cache_roundtrip(tmp_path):
    s = Storage(str(tmp_path / "db.sqlite3"))
    cache = {
        "Inception": {"imdbrating": "8.8/10", "title": "Inception"},
        "Matrix": {"imdbrating": "8.7/10", "title": "The Matrix"},
    }
    s.save_movie_cache(cache)
    loaded = s.load_movie_cache()
    assert loaded == cache


def test_storage_icon_cache_roundtrip(tmp_path):
    s = Storage(str(tmp_path / "db.sqlite3"))
    data = b"\x89PNG..."
    s.save_icon("example.org", data)
    assert s.get_icon("example.org") == data


def test_migrate_from_json_if_needed_imports_and_deletes(tmp_path):
    # Prepare legacy JSON files
    feeds_json = tmp_path / "feeds.json"
    read_json = tmp_path / "read_articles.json"
    groups_json = tmp_path / "group_settings.json"
    movie_json = tmp_path / "movie_data_cache.json"

    entry = make_entry(title="Title1", link="https://ex/1")
    feeds_payload = {
        "feeds": [
            {"title": "F1", "url": "https://ex/feed", "entries": [entry], "sort_column": 1, "sort_order": 0}
        ],
        "column_widths": {"https://ex/feed": [100, 120]}
    }
    feeds_json.write_text(json.dumps(feeds_payload))
    read_json.write_text(json.dumps([compute_article_id(entry)]))
    groups_json.write_text(json.dumps({"ex": {"omdb_enabled": True, "notifications_enabled": False}}))
    movie_json.write_text(json.dumps({"Inception": {"imdbrating": "8.8/10"}}))

    s = Storage(str(tmp_path / "db.sqlite3"))
    s.migrate_from_json_if_needed(str(tmp_path))

    # JSON files should be removed
    for p in [feeds_json, read_json, groups_json, movie_json]:
        assert not p.exists()

    # Data should be present in SQLite
    feeds = s.get_all_feeds()
    assert len(feeds) == 1 and feeds[0]["url"] == "https://ex/feed"
    assert len(feeds[0]["entries"]) == 1
    assert set(s.load_read_articles()) == {compute_article_id(entry)}
    gs = s.load_group_settings()
    assert gs.get("ex", {}).get("omdb_enabled") is True
    cw = s.load_column_widths()
    assert cw.get("https://ex/feed") == [100, 120]
    mc = s.load_movie_cache()
    assert "Inception" in mc
